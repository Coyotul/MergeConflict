"""Consistent typed errors without echoing inputs, passwords or database details."""

import json
import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.core.errors import DomainError
from src.models.common import ErrorDetail, ErrorResponse, ValidationIssue, new_id


logger = logging.getLogger("banking.api")
ERROR_RESPONSES = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Invalid tool input", 401: "Invalid, expired or revoked demo session",
        403: "Role or consent does not permit this action", 404: "Object not visible or route not found",
        405: "HTTP method not allowed", 409: "Workflow, evidence or idempotency conflict", 413: "Request body too large",
        429: "Local demo rate limit", 500: "Unexpected service error",
        501: "Capability intentionally not implemented", 503: "Local persistence unavailable",
    }.items()
}


def error_response(
    request: Request, status: int, code: str, message: str, issues: list[ValidationIssue] | None = None,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", new_id())
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, correlation_id=correlation_id, issues=issues))
    headers = {"X-Correlation-ID": correlation_id, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    origin = request.headers.get("origin")
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and origin in settings.allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Expose-Headers"] = "X-Correlation-ID, Retry-After"
        headers["Vary"] = "Origin"
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = "60"
    return JSONResponse(body.model_dump(mode="json", by_alias=True, exclude_none=True), status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        return error_response(request, error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        issues = []
        for item in error.errors()[:20]:
            # Only schema field names are exposed. Unknown keys/values may contain secrets.
            if item["type"] == "extra_forbidden":
                field = "request"
            else:
                field = ".".join(str(part) for part in item["loc"] if part not in {"body", "query", "path"}) or "request"
            issues.append(ValidationIssue(field=field, code=item["type"]))
        return error_response(request, 400, "VALIDATION_ERROR", "Request input does not match the documented schema.", issues)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}
        return error_response(request, error.status_code, codes.get(error.status_code, "REQUEST_FAILED"), "The requested endpoint or action is not available.")

    @app.exception_handler(sqlite3.Error)
    async def persistence_error(request: Request, error: sqlite3.Error) -> JSONResponse:
        logger.error(json.dumps({"event": "persistence_unavailable", "correlationId": request.state.correlation_id}))
        return error_response(request, 503, "PERSISTENCE_UNAVAILABLE", "Local demo persistence is unavailable. No successful state change was recorded.")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(json.dumps({
            "event": "unexpected_service_error", "type": type(error).__name__,
            "correlationId": getattr(request.state, "correlation_id", "unknown"),
        }))
        return error_response(request, 500, "INTERNAL_ERROR", "The demo service could not complete this action.")