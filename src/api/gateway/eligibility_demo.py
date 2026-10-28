"""Loopback synthetic API composition. Public demo keys are NOT production auth."""

import secrets
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.application.eligibility import eligibility_router
from src.core.eligibility_demo import build_demo_service
from src.core.eligibility_errors import EligibilityError
from src.security.eligibility import ActorContext, ActorRole
from src.services.eligibility.service import EligibilityService


@dataclass(frozen=True)
class DemoCredential:
    token: str
    actor: ActorContext


class DemoAuthenticator:
    def __init__(self, credentials: tuple[DemoCredential, ...]) -> None:
        if not credentials or len({c.token for c in credentials}) != len(credentials):
            raise ValueError("Demo credentials must be nonempty and unique.")
        self.credentials = credentials

    def authenticate(self, token: str | None) -> ActorContext:
        if token is not None and len(token) <= 256 and token.isascii():
            for credential in self.credentials:
                if secrets.compare_digest(token, credential.token):
                    return credential.actor
        raise EligibilityError("UNAUTHORIZED", "A valid synthetic demo credential is required.", 401)


def default_authenticator() -> DemoAuthenticator:
    permissions = frozenset({"eligibility:assess", "eligibility:read"})
    return DemoAuthenticator((
        DemoCredential("demo-customer-key", ActorContext("demo-customer-actor", ActorRole.CUSTOMER,
                       customer_id="demo-customer", permissions=permissions)),
        DemoCredential("demo-reviewer-key", ActorContext("demo-reviewer-actor", ActorRole.REVIEWER,
                       permissions=permissions, assigned_application_ids=frozenset({
                           "demo-app-eligible", "demo-app-high-dti", "demo-app-missing-id",
                           "demo-app-adverse-history", "demo-app-bureau-unavailable", "demo-app-missing-consent",
                       }))),
    ))


def create_app(
    service: EligibilityService | None = None, authenticator: DemoAuthenticator | None = None,
) -> FastAPI:
    service = service or build_demo_service()
    authenticator = authenticator or default_authenticator()
    app = FastAPI(
        title="Synthetic Eligibility Check", version="0.1.0",
        description="Independent local prototype. No Raiffeisen affiliation, real inquiries or final credit decisions.",
    )
    bearer = HTTPBearer(auto_error=False)

    async def actor_dependency(
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> ActorContext:
        return authenticator.authenticate(credential.credentials if credential else None)

    def error_body(code: str, message: str, request: Request) -> dict:
        return {"error": {"code": code, "message": message,
                          "correlationId": getattr(request.state, "correlation_id", str(uuid4()))}}

    @app.exception_handler(EligibilityError)
    async def domain_error(request: Request, exc: EligibilityError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.http_status == 401 else None
        return JSONResponse(error_body(exc.code, exc.message, request), status_code=exc.http_status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default response echoes invalid input; do not expose evidence/tokens.
        return JSONResponse(error_body("VALIDATION_ERROR", "Request fields are invalid.", request), status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(error_body("INTERNAL_ERROR", "The assessment could not be completed.", request), status_code=500)

    @app.get("/health")
    async def health() -> JSONResponse:
        healthy = service.assessments.healthcheck()
        return JSONResponse({"status": "ok" if healthy else "degraded", "mode": "synthetic-demo",
                             "persistence": "local-sqlite", "storageAvailable": healthy,
                             "simulatedProviders": True}, status_code=200 if healthy else 503)

    app.include_router(eligibility_router(service, actor_dependency))
    return app