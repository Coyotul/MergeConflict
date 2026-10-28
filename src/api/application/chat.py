"""Chat API router for the orchestrator."""
import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile

from src.agent.orchestration.events import (
    CustomerMessage,
    DocumentUploaded,
    OfferSelected,
    ConfirmationDecision,
)
from src.agent.orchestration.orchestrator import Orchestrator
from src.core.errors import InvalidUpload
from src.models.chat import (
    ConfirmationRequest,
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

    def get_customer_id(
        x_customer_id: Annotated[str | None, Header()] = None
    ) -> str:
        """Extract and validate customer ID from header.

        Raises:
            HTTPException: 401 if header is missing
        """
        if not x_customer_id:
            raise HTTPException(
                status_code=401,
                detail={"code": "missing_customer_id", "message": "X-Customer-Id header is required", "retryable": False}
            )
        return x_customer_id

    @router.post("/sessions", status_code=201, response_model=TurnResponse)
    def create_session(
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Create a new chat session.

        Returns:
            201 with TurnResponse containing greeting
        """
        return orchestrator.start_session(customer_id)

    @router.post("/sessions/{session_id}/messages", response_model=TurnResponse)
    def send_message(
        session_id: str,
        request: SendMessageRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Send a text message in the conversation.

        Returns:
            200 with TurnResponse
        """
        event = CustomerMessage(text=request.text)
        return orchestrator.handle(session_id, customer_id, event)

    @router.post("/sessions/{session_id}/documents", response_model=TurnResponse)
    def upload_document(
        session_id: str,
        doc_type: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Upload a document for the application.

        Returns:
            200 with TurnResponse
        """
        # 1. Validate content type
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise InvalidUpload(
                "unsupported_media_type",
                f"Content type {file.content_type} not allowed. Must be PDF, JPEG, or PNG."
            )

        # 2. Read file with size limit (blocking read from threadpool)
        content = file.file.read(max_upload_bytes + 1)
        if len(content) > max_upload_bytes:
            raise InvalidUpload(
                "upload_too_large",
                f"File size exceeds maximum of {max_upload_bytes} bytes"
            )

        # 3. Check if document is requested (before storing)
        orchestrator.check_upload(session_id, customer_id, doc_type)

        # 4. Store document
        document_id = uuid4().hex
        sanitized_filename = sanitize_filename(file.filename or "upload")
        stored_path: Path | None = None

        try:
            stored_path = documents.save(session_id, document_id, sanitized_filename, content)

            # 5. Handle upload event
            event = DocumentUploaded(
                document_id=document_id,
                doc_type=doc_type,
                filename=sanitized_filename,
                size_bytes=len(content)
            )
            return orchestrator.handle(session_id, customer_id, event)
        except Exception:
            # If handle() fails after upload was stored, delete the file
            if stored_path and stored_path.exists():
                try:
                    stored_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup uploaded file {stored_path}: {cleanup_error}")
            raise

    @router.post("/sessions/{session_id}/offer-selection", response_model=TurnResponse)
    def select_offer(
        session_id: str,
        request: OfferSelectionRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Select a loan offer.

        Returns:
            200 with TurnResponse
        """
        event = OfferSelected(offer_id=request.offer_id)
        return orchestrator.handle(session_id, customer_id, event)

    @router.post("/sessions/{session_id}/confirmation", response_model=TurnResponse)
    def confirm_application(
        session_id: str,
        request: ConfirmationRequest,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> TurnResponse:
        """Confirm or decline the application summary.

        Returns:
            200 with TurnResponse
        """
        event = ConfirmationDecision(
            summary_version=request.summary_version,
            decision=request.decision
        )
        return orchestrator.handle(session_id, customer_id, event)

    @router.get("/sessions/{session_id}", response_model=SessionView)
    def get_session(
        session_id: str,
        customer_id: Annotated[str, Depends(get_customer_id)]
    ) -> SessionView:
        """Get session view with messages and current state.

        Returns:
            200 with SessionView
        """
        return orchestrator.view(session_id, customer_id)

    return router
