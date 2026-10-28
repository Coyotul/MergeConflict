"""Local-only guardrails, bounded JSON bodies, correlation and structured logs."""

import json
import logging
import time
from collections import deque
from threading import Lock
from uuid import UUID

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.gateway.errors import error_response
from src.core.settings import Settings
from src.models.common import new_id


logger = logging.getLogger("banking.api")


class RateLimiter:
    def __init__(self):
        self._buckets: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def allow(self, identity: str, category: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        key = (identity, category)
        with self._lock:
            expired = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff]
            for old_key in expired:
                del self._buckets[old_key]
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


class GatewayMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.limiter = RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        supplied = request.headers.get("x-correlation-id")
        try:
            correlation_id = str(UUID(supplied)) if supplied else new_id()
        except (ValueError, AttributeError):
            correlation_id = new_id()
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = time.monotonic()
        status = 500

        async def send_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _ in headers}
                for name, value in (
                    (b"x-correlation-id", correlation_id.encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ):
                    if name not in names:
                        headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(status_code: int, code: str, message: str) -> None:
            await error_response(request, status_code, code, message)(scope, receive, send_response)

        try:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self.settings.allowed_origins:
                await reject(403, "FORBIDDEN", "This origin is not allowed by the local synthetic demo.")
                return
            if scope["method"] == "OPTIONS":
                requested_method = request.headers.get("access-control-request-method")
                requested_headers = {
                    header.strip().lower() for header in request.headers.get("access-control-request-headers", "").split(",")
                    if header.strip()
                }
                allowed_headers = {"accept", "accept-language", "content-language", "content-type", "authorization", "x-correlation-id"}
                if origin is not None and requested_method is not None and (
                    requested_method not in {"GET", "POST", "PATCH", "OPTIONS"}
                    or not requested_headers <= allowed_headers
                ):
                    await reject(403, "FORBIDDEN", "The requested cross-origin method or headers are not allowed.")
                    return
                await self.app(scope, receive, send_response)
                return
            path = scope["path"]
            if path.startswith("/api/"):
                identity = (scope.get("client") or ("unknown",))[0]
                if not self.limiter.allow(identity, "api", self.settings.requests_per_minute):
                    await reject(429, "RATE_LIMITED", "The local demo request limit was exceeded.")
                    return
                if path in {"/api/session", "/api/v1/session"} and not self.limiter.allow(identity, "login", self.settings.logins_per_minute):
                    await reject(429, "RATE_LIMITED", "Too many demo login attempts. Retry later.")
                    return
            if scope["method"] in {"POST", "PATCH", "PUT"}:
                length = request.headers.get("content-length")
                if length is not None:
                    try:
                        declared = int(length)
                    except ValueError:
                        await reject(400, "VALIDATION_ERROR", "Invalid Content-Length header.")
                        return
                    if declared < 0:
                        await reject(400, "VALIDATION_ERROR", "Invalid Content-Length header.")
                        return
                    if declared > self.settings.max_body_bytes:
                        await reject(413, "PAYLOAD_TOO_LARGE", "The JSON request exceeds the local demo size limit.")
                        return
                body = bytearray()
                more = True
                while more:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunk = event.get("body", b"")
                    if len(body) + len(chunk) > self.settings.max_body_bytes:
                        await reject(413, "PAYLOAD_TOO_LARGE", "The JSON request exceeds the local demo size limit.")
                        return
                    body.extend(chunk)
                    more = event.get("more_body", False)
                if body and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    await reject(400, "VALIDATION_ERROR", "Use application/json; binary document uploads are not supported.")
                    return
                consumed = False

                async def bounded_receive() -> Message:
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, bounded_receive, send_response)
            else:
                await self.app(scope, receive, send_response)
        finally:
            # Do not log URLs, query strings, bodies, tokens, passwords or document metadata.
            route = scope.get("route")
            logger.info(json.dumps({
                "event": "http_request", "method": scope["method"],
                "operation": getattr(route, "operation_id", None) or "gateway",
                "status": status, "correlationId": correlation_id,
                "durationMs": round((time.monotonic() - started) * 1000, 2),
            }))