"""Typed exception classes for the Historical RAG Platform."""


class ChunkDeserializationError(ValueError):
    """Raised when a chunk dict cannot be deserialized into a Chunk model.

    Args:
        field: The name of the offending field.
        message: Human-readable description of the problem.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"ChunkDeserializationError on field '{field}': {message}")


class AnswerParseError(ValueError):
    """Raised when the raw LLM output cannot be parsed into an AnswerResponse."""

    def __init__(self, message: str, raw: str = "") -> None:
        self.raw = raw
        super().__init__(f"AnswerParseError: {message}")


class RetrievalUnavailableError(RuntimeError):
    """Raised when both BM25 and vector retrieval fail for the same query."""


class SynthesisError(RuntimeError):
    """Raised when the LLM synthesis step fails for a non-parse reason (e.g. 413 payload too large)."""
