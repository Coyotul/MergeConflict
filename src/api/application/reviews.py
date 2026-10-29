"""Customer and reviewer routes for submitted applications."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from src.core.errors import InvalidUpload
from src.services.human_review.models import (
    STATUS_LABELS, InvalidTransition, NotFound, ReviewApplication, ReviewStatus, StaleVersion,
)
from src.services.human_review.service import ReviewService
from src.storage.secure_documents.local import sanitize_filename

DEMO_REVIEWER_ID = "reviewer-demo"


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject", "request_document"]
    reason: str
    version: int
    doc_type: str | None = None


def _offer(app: ReviewApplication) -> dict[str, Any] | None:
    if app.current.get("offer"):
        return app.current["offer"]
    application = app.snapshot.get("application", {})
    offers = (application.get("offers") or {}).get("offers") or []
    return next((o for o in offers if o.get("offer_id") == application.get("selected_offer_id")), None)


def _field(application: dict, name: str) -> Any:
    value = (application.get("fields") or {}).get(name)
    return value.get("value") if value else None


def customer_view(app: ReviewApplication) -> dict[str, Any]:
    offer = _offer(app)
    application = app.current.get("application", {})
    request = app.open_request
    return {
        "id": app.id, "reference": app.reference, "product_code": app.product_code,
        "status": app.status.value, "status_label": STATUS_LABELS[app.status],
        "amount": (offer or {}).get("amount", {}).get("amount") or _field(application, "amount"),
        "term_months": (offer or {}).get("term_months") or _field(application, "term_months"),
        "monthly_installment": (offer or {}).get("monthly_installment", {}).get("amount"),
        "total_cost": (offer or {}).get("total_cost", {}).get("amount"),
        "offer_updated": app.current.get("offer") is not None,
        "history": [
            {"to_status": h.to_status.value, "status_label": STATUS_LABELS[h.to_status], "reason": h.reason,
             "at": h.at.isoformat()}
            for h in app.history
        ],
        "open_request": {"id": request.id, "doc_type": request.doc_type, "reason": request.reason} if request else None,
        "created_at": app.created_at.isoformat(), "updated_at": app.updated_at.isoformat(),
    }


def changed_fields(app: ReviewApplication) -> list[dict[str, Any]]:
    before = app.snapshot.get("application", {})
    after = app.current.get("application", {})
    names = sorted(set(before.get("fields") or {}) | set(after.get("fields") or {}))
    return [
        {"field": name, "before": _field(before, name), "after": _field(after, name)}
        for name in names if _field(before, name) != _field(after, name)
    ]


def create_review_router(service: ReviewService, *, max_upload_bytes: int) -> APIRouter:
    router = APIRouter(tags=["reviews"])

    def customer_id(x_customer_id: Annotated[str | None, Header()] = None) -> str:
        if not x_customer_id:
            raise HTTPException(401, {"code": "missing_customer_id", "message": "X-Customer-Id header is required"})
        return x_customer_id

    def reviewer_id(x_reviewer_id: Annotated[str | None, Header()] = None) -> str:
        if x_reviewer_id != DEMO_REVIEWER_ID:
            raise HTTPException(403, {"code": "forbidden", "message": "Only the demo reviewer can do this."})
        return x_reviewer_id

    def guarded(fn):
        try:
            return fn()
        except NotFound:
            raise HTTPException(404, {"code": "not_found", "message": "Application not found."})
        except (InvalidTransition, StaleVersion) as exc:
            raise HTTPException(409, {"code": "conflict", "message": str(exc)})
        except ValueError as exc:
            raise HTTPException(422, {"code": "invalid_request", "message": str(exc)})

    # ---- customer ---------------------------------------------------------

    @router.get("/applications")
    def list_mine(cid: Annotated[str, Depends(customer_id)]):
        return {"applications": [customer_view(a) for a in service.store.list(customer_id=cid)]}

    @router.get("/applications/{app_id}")
    def get_mine(app_id: str, cid: Annotated[str, Depends(customer_id)]):
        return guarded(lambda: customer_view(service.customer_application(app_id, cid)))

    @router.post("/applications/{app_id}/requests/{request_id}/document")
    def upload(app_id: str, request_id: str, file: Annotated[UploadFile, File()],
               cid: Annotated[str, Depends(customer_id)]):
        guarded(lambda: service.customer_application(app_id, cid))
        content = file.file.read(max_upload_bytes + 1)
        if len(content) > max_upload_bytes:
            raise InvalidUpload("upload_too_large", f"File size exceeds maximum of {max_upload_bytes} bytes")
        app, outcome = guarded(lambda: service.upload_requested(
            app_id, request_id, customer_id=cid, filename=sanitize_filename(file.filename or "upload"),
            content=content, mime_type=file.content_type or "",
        ))
        return {"application": customer_view(app), "accepted": outcome.accepted, "reasons": outcome.reasons}

    # ---- reviewer ---------------------------------------------------------

    @router.get("/review/applications")
    def queue(_: Annotated[str, Depends(reviewer_id)], status: ReviewStatus | None = None):
        return {"applications": [
            {"id": a.id, "reference": a.reference, "customer_name": a.snapshot.get("profile", {}).get("full_name"),
             "product_code": a.product_code, "amount": customer_view(a)["amount"], "status": a.status.value,
             "status_label": STATUS_LABELS[a.status], "updated_at": a.updated_at.isoformat()}
            for a in service.store.list(status=status)
        ]}

    @router.get("/review/applications/{app_id}")
    def detail(app_id: str, _: Annotated[str, Depends(reviewer_id)]):
        app = guarded(lambda: service.store.get(app_id))
        return {**app.model_dump(mode="json"), "status_label": STATUS_LABELS[app.status],
                "changed_fields": changed_fields(app), "customer": customer_view(app)}

    @router.post("/review/applications/{app_id}/decision")
    def decision(app_id: str, body: DecisionRequest, _: Annotated[str, Depends(reviewer_id)]):
        if body.action == "request_document":
            app = guarded(lambda: service.request_document(
                app_id, doc_type=body.doc_type or "", reason=body.reason, version=body.version))
        else:
            app = guarded(lambda: service.decide(app_id, action=body.action, reason=body.reason, version=body.version))
        return {**app.model_dump(mode="json"), "status_label": STATUS_LABELS[app.status]}

    @router.get("/review/applications/{app_id}/documents/{document_id}")
    def document_file(app_id: str, document_id: str, _: Annotated[str, Depends(reviewer_id)]):
        app = guarded(lambda: service.store.get(app_id))
        if all(d.document_id != document_id for d in app.documents):
            raise HTTPException(404, {"code": "not_found", "message": "Document not found."})
        try:
            content, record = service.documents.storage.get_document_bytes(document_id, customer_id=app.customer_id)
        except (FileNotFoundError, PermissionError, ValueError):
            raise HTTPException(404, {"code": "not_found", "message": "Document file is unavailable."})
        return Response(content, media_type=record["mime_type"])

    return router
