"""Public synthetic credentials and transient, role-bound opaque sessions."""

import hashlib
import hmac
from datetime import datetime, timedelta
from threading import Lock

from src.core.catalogue import DemoAccount
from src.core.errors import DomainError
from src.models.banking import Actor, Session
from src.models.common import new_id, utc_now
from src.models.requests import SessionInput


class DemoSessions:
    def __init__(self, accounts: list[DemoAccount], lifetime_hours: int = 8):
        self.accounts = tuple(accounts)
        self.lifetime = timedelta(hours=lifetime_hours)
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(self, input: SessionInput, now: datetime | None = None) -> Session:
        now = now or utc_now()
        supplied = hashlib.sha256(input.password.encode("utf-8")).digest()
        matched = None
        for account in self.accounts:
            expected = hashlib.sha256(account.password.get_secret_value().encode("utf-8")).digest()
            password_matches = hmac.compare_digest(supplied, expected)
            if account.email == input.email and account.actor.role == input.role and password_matches:
                matched = account
        if matched is None:
            raise DomainError(
                "INVALID_CREDENTIALS", "The email or password does not match this demo workspace.", 401
            )
        session = Session(token=new_id(), actor=matched.actor.model_copy(deep=True), expires_at=now + self.lifetime)
        with self._lock:
            expired = [token for token, value in self._sessions.items() if value.expires_at <= now]
            for token in expired:
                del self._sessions[token]
            self._sessions[session.token] = session
        return session.model_copy(deep=True)

    def require(self, token: str, now: datetime | None = None) -> Actor:
        now = now or utc_now()
        with self._lock:
            session = self._sessions.get(token)
            if session is None or session.expires_at <= now:
                self._sessions.pop(token, None)
                raise DomainError("UNAUTHORIZED", "Your demo session has ended. Sign in again.", 401)
            return session.actor.model_copy(deep=True)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)