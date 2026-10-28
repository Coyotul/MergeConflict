"""FastAPI application factory for the orchestrator."""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.agent.orchestration.orchestrator import Orchestrator
from src.api.application.chat import create_chat_router
from src.core.composition import build_orchestrator
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
    async def health():
        """Health check endpoint."""
        return {
            "status": "ok",
            "model": settings.model,
            "session_store": settings.session_store
        }

    # Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Handle HTTP exceptions - if detail is a dict with our error structure, return it directly."""
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            # Already formatted as ErrorBody
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        # Otherwise, wrap in ErrorBody format
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorBody(
                code="error",
                message=str(exc.detail),
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError):
        """Handle FastAPI request validation errors."""
        return JSONResponse(
            status_code=422,
            content=ErrorBody(
                code="invalid_request",
                message=str(exc),
                retryable=False
            ).model_dump()
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        """Handle Pydantic validation errors."""
        return JSONResponse(
            status_code=422,
            content=ErrorBody(
                code="invalid_request",
                message=str(exc),
                retryable=False
            ).model_dump()
        )

    return app
