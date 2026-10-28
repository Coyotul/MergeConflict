"""Safe domain errors shared by the HTTP and agent-tool adapters."""


class EligibilityError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class AccessDenied(EligibilityError):
    def __init__(self) -> None:
        super().__init__("ACCESS_DENIED", "This assessment is not permitted.", 403)


class IdempotencyConflict(EligibilityError):
    def __init__(self) -> None:
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            "The key belongs to different inputs or an older snapshot; use a new key.",
            409,
        )


class StorageUnavailable(EligibilityError):
    def __init__(self) -> None:
        super().__init__("STORAGE_UNAVAILABLE", "Assessment storage is unavailable.", 503)