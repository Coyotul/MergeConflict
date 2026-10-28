"""FastAPI factory with explicit lifespan and versioned tool contracts."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from src.api.application.router import router
from src.api.application.tool_contracts import operation_metadata
from src.api.gateway.dependencies import Services
from src.api.gateway.errors import install_error_handlers
from src.api.gateway.middleware import GatewayMiddleware
from src.core.container import Container
from src.core.settings import Settings
from src.models.common import Health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Corrupt config or storage fails startup; never silently reset application data.
        app.state.container = await run_in_threadpool(Container.build, settings)
        yield
        app.state.container = None

    app = FastAPI(
        title="Luma synthetic banking backend",
        version="1.0.0",
        description=(
            "Authenticated narrow tools for a future orchestrator. Synthetic data only; "
            "deterministic indicative calculations; customer confirmation and assigned human review. "
            "No live LLM, semantic RAG, OCR, bank inquiry, signing, payment or disbursement."
        ),
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": False},
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "Retry-After"],
    )
    # The outer guard supplies context/headers even for CORS preflights and errors.
    app.add_middleware(GatewayMiddleware, settings=settings)

    @app.get("/health", tags=["Health"], operation_id="get_backend_health", responses={503: {"model": Health}})
    def health(response: Response, services: Services) -> Health:
        available = services.repository.available()
        eligibility_available = services.evidence_eligibility.service.assessments.healthcheck()
        healthy = available and eligibility_available
        response.status_code = 200 if healthy else 503
        return Health(
            status="ok" if healthy else "degraded",
            dependencies={
                "database": "available" if available else "unavailable", "syntheticConfiguration": "loaded",
                "eligibilityStorage": "available" if eligibility_available else "unavailable",
                "orchestrator": "not-configured", "semanticRetrieval": "not-configured",
                "documentProcessing": "metadata-only", "bankIntegrations": "simulated-only",
            },
        )

    app.include_router(router, prefix="/api/v1")
    # Transitional /api aliases preserve resource naming, not the temporary Node chat engine.
    app.include_router(router, prefix="/api", include_in_schema=False)

    default_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = default_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
                    operation.update(operation_metadata(operation.get("operationId", "")))
        return schema

    app.openapi = openapi
    return app