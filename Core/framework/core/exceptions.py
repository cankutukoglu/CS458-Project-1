class HealingError(RuntimeError):
    """Raised when selector healing fails."""


class SelectorValidationError(HealingError):
    """Raised when an LLM returns an unusable selector."""
