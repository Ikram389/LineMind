"""Provider failures, each mapped to one clear message for the user."""


class ProviderError(Exception):
    """Base class. `code` is what the API and the UI show."""

    code = "failed"


class ProviderBusy(ProviderError):
    """Rate limited (HTTP 429) and retries ran out: "busy, try again in a moment"."""

    code = "busy"

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message or "The model provider is rate limiting requests.")
        self.retry_after = retry_after


class ProviderUnreachable(ProviderError):
    """Not configured, wrong key/URL/model, or no network: "model unreachable"."""

    code = "unreachable"


class ProviderUnavailable(ProviderError):
    """Server errors or timeouts that persisted after a retry."""

    code = "timeout"


class ModelOutputError(ProviderError):
    """The server rejected what the model generated (e.g. Groq's `tool_use_failed`, a
    malformed tool call). Treated like an invalid tool call: the model may correct once."""

    code = "invalid_tool_call"

    def __init__(self, message: str, generation: str = "") -> None:
        super().__init__(message)
        self.generation = generation
