"""Chat API router for the orchestrator."""
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.agent.orchestration.events import (
    CustomerMessage,
    DocumentUploaded,
    OfferSelected,
    ConfirmationDecision,
)
from src.agent.orchestration.orchestrator import Orchestrator
from src.core.errors import (
    InvalidUpload,
    ModelUnavailable,
    SessionAccessDenied,
    SessionBusy,
    SessionNotFound,
    SessionVersionConflict,
    ToolUnavailable,
)
from src.models.chat import (
    ConfirmationRequest,
    ErrorBody,
    OfferSelectionRequest,
    SendMessageRequest,
    SessionView,
    TurnResponse,
)
from src.storage.secure_documents.local import LocalDocumentStorage, sanitize_filename


logger = logging.getLogger("src.api")

# Allowed upload content types
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


def error_response(status_code: int, code: str, message: str, retryable: bool) -> JSONResponse:
    """Create an error response with ErrorBody."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorBody(code=code, message=message, retryable=retryable).model_dump()
    )


def create_chat_router(
    orchestrator: Orchestrator,
    documents: LocalDocumentStorage,
    max_upload_bytes: int
) -> APIRouter:
    """Create the chat API router.

    Args:
        orchestrator: The orchestrator instance
        documents: Document storage
        max_upload_bytes: Maximum allowed upload size in bytes

    Returns:
        Configured APIRouter
    """
    router = APIRouter(prefix="/chat", tags=["chat"])

    async def get_customer_id(
        x_customer_id: Annotated[str | None, Header()] = None
    ) -> str:
        """Extract and validate customer ID from header.

        Raises:
            HTTPException: 401 if header is missing
        """
        if not x_customer_id:
            # Raise HTTPException - will be caught by exception handler
            raise HTTPException(
                status_code=401,
                detail={"code": "missing_customer_id", "message": "X-Customer-Id header is required", "retryable": False}
            )
        return x_customer_id

    @router.post("/sessions", status_code=201, response_model=TurnResponse)
    async def create_session(
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Create a new chat session.

        Returns:
            201 with TurnResponse containing greeting
        """
        try:
            return orchestrator.start_session(customer_id)
        except ModelUnavailable as e:
            raise HTTPException(
                status_code=503,
                detail={"code": "service_unavailable", "message": str(e), "retryable": True}
            )
        except Exception as e:
            logger.exception("Unhandled error in create_session")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    @router.post("/sessions/{session_id}/messages", response_model=TurnResponse)
    async def send_message(
        session_id: str,
        request: SendMessageRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Send a text message in the conversation.

        Returns:
            200 with TurnResponse
        """
        try:
            event = CustomerMessage(text=request.text)
            return orchestrator.handle(session_id, customer_id, event)
        except SessionNotFound:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": f"Session {session_id} not found", "retryable": False}
            )
        except SessionAccessDenied:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Access denied to this session", "retryable": False}
            )
        except SessionBusy:
            raise HTTPException(
                status_code=409,
                detail={"code": "session_busy", "message": "Session is currently busy", "retryable": True}
            )
        except SessionVersionConflict:
            raise HTTPException(
                status_code=409,
                detail={"code": "version_conflict", "message": "Session was modified concurrently", "retryable": True}
            )
        except ModelUnavailable as e:
            raise HTTPException(
                status_code=503,
                detail={"code": "service_unavailable", "message": str(e), "retryable": True}
            )
        except ToolUnavailable as e:
            raise HTTPException(
                status_code=503,
                detail={"code": "service_unavailable", "message": str(e), "retryable": True}
            )
        except ValidationError as e:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_request", "message": str(e), "retryable": False}
            )
        except Exception as e:
            logger.exception("Unhandled error in send_message")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    @router.post("/sessions/{session_id}/documents", response_model=TurnResponse)
    async def upload_document(
        session_id: str,
        doc_type: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Upload a document for the application.

        Returns:
            200 with TurnResponse
        """
        try:
            # 1. Validate content type
            if file.content_type not in ALLOWED_CONTENT_TYPES:
                raise HTTPException(
                    status_code=415,
                    detail={"code": "unsupported_media_type", "message": f"Content type {file.content_type} not allowed. Must be PDF, JPEG, or PNG.", "retryable": False}
                )

            # 2. Read file with size limit
            content = await file.read(max_upload_bytes + 1)
            if len(content) > max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "upload_too_large", "message": f"File size exceeds maximum of {max_upload_bytes} bytes", "retryable": False}
                )

            # 3. Check if document is requested (before storing)
            orchestrator.check_upload(session_id, customer_id, doc_type)

            # 4. Store document
            document_id = uuid4().hex
            sanitized_filename = sanitize_filename(file.filename or "upload")
            documents.save(session_id, document_id, sanitized_filename, content)

            # 5. Handle upload event
            event = DocumentUploaded(
                document_id=document_id,
                doc_type=doc_type,
                filename=sanitized_filename,
                size_bytes=len(content)
            )
            return orchestrator.handle(session_id, customer_id, event)

        except HTTPException:
            # Re-raise HTTPExceptions as-is
            raise
        except InvalidUpload as e:
            # Map InvalidUpload to appropriate HTTP status
            status_code = 422
            if e.code == "upload_too_large":
                status_code = 413
            elif e.code == "unsupported_media_type":
                status_code = 415

            raise HTTPException(
                status_code=status_code,
                detail={"code": e.code, "message": e.message, "retryable": False}
            )
        except SessionNotFound:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": f"Session {session_id} not found", "retryable": False}
            )
        except SessionAccessDenied:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Access denied to this session", "retryable": False}
            )
        except SessionBusy:
            raise HTTPException(
                status_code=409,
                detail={"code": "session_busy", "message": "Session is currently busy", "retryable": True}
            )
        except Exception as e:
            logger.exception("Unhandled error in upload_document")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    @router.post("/sessions/{session_id}/offer-selection", response_model=TurnResponse)
    async def select_offer(
        session_id: str,
        request: OfferSelectionRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Select a loan offer.

        Returns:
            200 with TurnResponse
        """
        try:
            event = OfferSelected(offer_id=request.offer_id)
            return orchestrator.handle(session_id, customer_id, event)
        except SessionNotFound:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": f"Session {session_id} not found", "retryable": False}
            )
        except SessionAccessDenied:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Access denied to this session", "retryable": False}
            )
        except SessionBusy:
            raise HTTPException(
                status_code=409,
                detail={"code": "session_busy", "message": "Session is currently busy", "retryable": True}
            )
        except Exception as e:
            logger.exception("Unhandled error in select_offer")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    @router.post("/sessions/{session_id}/confirmation", response_model=TurnResponse)
    async def confirm_application(
        session_id: str,
        request: ConfirmationRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Confirm or decline the application summary.

        Returns:
            200 with TurnResponse
        """
        try:
            event = ConfirmationDecision(
                summary_version=request.summary_version,
                decision=request.decision
            )
            return orchestrator.handle(session_id, customer_id, event)
        except SessionNotFound:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": f"Session {session_id} not found", "retryable": False}
            )
        except SessionAccessDenied:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Access denied to this session", "retryable": False}
            )
        except SessionBusy:
            raise HTTPException(
                status_code=409,
                detail={"code": "session_busy", "message": "Session is currently busy", "retryable": True}
            )
        except Exception as e:
            logger.exception("Unhandled error in confirm_application")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    @router.get("/sessions/{session_id}", response_model=SessionView)
    async def get_session(
        session_id: str,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> SessionView:
        """Get session view with messages and current state.

        Returns:
            200 with SessionView
        """
        try:
            return orchestrator.view(session_id, customer_id)
        except SessionNotFound:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": f"Session {session_id} not found", "retryable": False}
            )
        except SessionAccessDenied:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Access denied to this session", "retryable": False}
            )
        except Exception as e:
            logger.exception("Unhandled error in get_session")
            raise HTTPException(
                status_code=500,
                detail={"code": "internal_error", "message": "An internal error occurred", "retryable": False}
            )

    return router
