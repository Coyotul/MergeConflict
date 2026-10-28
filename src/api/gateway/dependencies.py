"""Resolve server-issued principals. No tool accepts an actor or role override."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.container import Container
from src.core.context import CallContext
from src.core.errors import DomainError


bearer = HTTPBearer(auto_error=False, scheme_name="DemoBearerSession")


def get_container(request: Request) -> Container:
    return request.app.state.container


Services = Annotated[Container, Depends(get_container)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def get_token(credentials: Credentials) -> str:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise DomainError("UNAUTHORIZED", "A valid bearer demo session is required.", 401)
    return credentials.credentials


Token = Annotated[str, Depends(get_token)]


def get_context(request: Request, services: Services, token: Token) -> CallContext:
    return CallContext(services.sessions.require(token), request.state.correlation_id)


Context = Annotated[CallContext, Depends(get_context)]