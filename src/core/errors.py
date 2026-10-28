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
