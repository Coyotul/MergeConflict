"""FastAPI application factory for the orchestrator."""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.agent.orchestration.orchestrator import Orchestrator
from src.api.application.chat import create_chat_router
from src.core.composition import build_orchestrator
from src.core.errors import (
    InvalidUpload,
    ModelUnavailable,
    SessionAccessDenied,
    SessionBusy,
    SessionNotFound,
    SessionVersionConflict,
    ToolUnavailable,
)
from src.core.settings import OrchestratorSettings, load_orchestrator_settings
from src.models.chat import ErrorBody
from src.storage.secure_documents.local import LocalDocumentStorage


logger = logging.getLogger("src.api")


def create_app(
    settings: OrchestratorSettings | None = None,
    *,
    orchestrator: Orchestrator | None = None
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional orchestrator settings. If None, loads from environment.
        orchestrator: Optional pre-built orchestrator (for testing). If provided,
                     settings is only used for upload configuration.

    Returns:
        Configured FastAPI application
    """
    # Load settings if not provided
    if settings is None:
        settings = load_orchestrator_settings()

    # Build orchestrator if not provided
    if orchestrator is None:
        orchestrator = build_orchestrator(settings)

    # Create app
    app = FastAPI(
        title="Credit Assistant API",
        version="1.0.0",
        description="AI-powered credit application assistant"
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Customer-Id"],
        allow_credentials=False,
    )

    # Document storage
    documents = LocalDocumentStorage(settings.uploads_dir)

    # Register chat router
    chat_router = create_chat_router(
        orchestrator=orchestrator,
        documents=documents,
        max_upload_bytes=settings.max_upload_bytes
    )
    app.include_router(chat_router)

    # Health endpoint
    @app.get("/health")
    def health():
        """Health check endpoint."""
        return {
            "status": "ok",
            "model": settings.model,
            "session_store": settings.session_store
        }

    # Domain exception handlers (ordered from most specific to least)
    @app.exception_handler(SessionNotFound)
    def handle_session_not_found(request: Request, exc: SessionNotFound):
        """Handle session not found errors."""
        return JSONResponse(
            status_code=404,
            content=ErrorBody(
                code="session_not_found",
                message="The requested session was not found.",
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(SessionAccessDenied)
    def handle_session_access_denied(request: Request, exc: SessionAccessDenied):
        """Handle session access denied errors."""
        return JSONResponse(
            status_code=403,
            content=ErrorBody(
                code="forbidden",
                message="You do not have access to this session.",
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(SessionBusy)
    def handle_session_busy(request: Request, exc: SessionBusy):
        """Handle session busy errors."""
        return JSONResponse(
            status_code=409,
            content=ErrorBody(
                code="session_busy",
                message="The session is currently processing another request.",
                retryable=True
            ).model_dump()
        )

    @app.exception_handler(SessionVersionConflict)
    def handle_session_version_conflict(request: Request, exc: SessionVersionConflict):
        """Handle session version conflict errors."""
        return JSONResponse(
            status_code=409,
            content=ErrorBody(
                code="version_conflict",
                message="The session was modified by another request.",
                retryable=True
            ).model_dump()
        )

    @app.exception_handler(ModelUnavailable)
    def handle_model_unavailable(request: Request, exc: ModelUnavailable):
        """Handle model unavailable errors."""
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="service_unavailable",
                message="The assistant is temporarily unavailable. Please try again.",
                retryable=True
            ).model_dump()
        )

    @app.exception_handler(ToolUnavailable)
    def handle_tool_unavailable(request: Request, exc: ToolUnavailable):
        """Handle tool unavailable errors."""
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="service_unavailable",
                message="The assistant is temporarily unavailable. Please try again.",
                retryable=True
            ).model_dump()
        )

    @app.exception_handler(InvalidUpload)
    def handle_invalid_upload(request: Request, exc: InvalidUpload):
        """Handle invalid upload errors."""
        # Map error code to HTTP status
        status_code = 422
        if exc.code == "upload_too_large":
            status_code = 413
        elif exc.code == "unsupported_media_type":
            status_code = 415

        return JSONResponse(
            status_code=status_code,
            content=ErrorBody(
                code=exc.code,
                message=exc.message,
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException):
        """Handle HTTP exceptions - if detail is a dict with our error structure, return it directly."""
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            # Already formatted as ErrorBody
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        # Default HTTP exception without our format
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorBody(
                code="http_error",
                message=str(exc.detail) if exc.detail else "An error occurred.",
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(RequestValidationError)
    def request_validation_error_handler(request: Request, exc: RequestValidationError):
        """Handle FastAPI request validation errors with sanitized field locations."""
        # Extract field locations without showing values
        field_errors = []
        for error in exc.errors():
            loc = " -> ".join(str(part) for part in error["loc"])
            field_errors.append(loc)

        if field_errors:
            message = f"Invalid request: {', '.join(field_errors)}"
        else:
            message = "Invalid request format."

        return JSONResponse(
            status_code=422,
            content=ErrorBody(
                code="invalid_request",
                message=message,
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(ValidationError)
    def validation_error_handler(request: Request, exc: ValidationError):
        """Handle Pydantic validation errors with sanitized messages."""
        # Extract field names without showing values
        field_errors = []
        for error in exc.errors():
            loc = " -> ".join(str(part) for part in error["loc"])
            field_errors.append(loc)

        if field_errors:
            message = f"Invalid data: {', '.join(field_errors)}"
        else:
            message = "Invalid data format."

        return JSONResponse(
            status_code=422,
            content=ErrorBody(
                code="invalid_request",
                message=message,
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exc: Exception):
        """Handle all unexpected errors with logging."""
        logger.exception("Unhandled exception in request")
        return JSONResponse(
            status_code=500,
            content=ErrorBody(
                code="internal_error",
                message="An internal error occurred. Please try again later.",
                retryable=False
            ).model_dump()
        )

    return app
