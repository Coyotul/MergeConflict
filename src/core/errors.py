"""Shared errors: RAG and orchestrator exceptions, plus transport-independent banking capability errors."""


class RagError(Exception):
    """Base exception for RAG-related errors."""
    pass


class KnowledgeStoreUnavailable(RagError):
    """Database is unreachable or misconfigured."""
    pass


class EmbeddingModelUnavailable(RagError):
    """Embedding model failed to load or is missing."""
    pass


class IngestionError(RagError):
    """Document ingestion failed."""
    pass


class TemplateMismatch(RagError):
    """Document structure does not match expected template."""
    pass


class OrchestratorError(Exception):
    """Base exception for orchestrator-related errors."""
    pass


class SessionNotFound(OrchestratorError):
    """Requested session does not exist."""
    pass


class SessionAccessDenied(OrchestratorError):
    """User lacks permission to access this session."""
    pass


class SessionBusy(OrchestratorError):
    """Session is currently being modified by another request."""
    pass


class SessionVersionConflict(OrchestratorError):
    """Session was modified since it was read."""
    pass


class ModelUnavailable(OrchestratorError):
    """The requested model is not available."""
    pass


class ToolUnavailable(OrchestratorError):
    """The requested tool is not available."""
    pass


class InvalidUpload(OrchestratorError):
    """File upload validation failed."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ConfigurationError(OrchestratorError):
    """Orchestrator configuration is invalid or missing."""
    pass


class DomainError(Exception):
    """Safe, transport-independent error returned by banking capabilities."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
