"""Disabled LLM implementation used when no provider is configured."""

from pydantic import BaseModel

from .contracts import CompletionRequest, LLMService, LLMUnavailableError


class DisabledLLMService(LLMService):
    """Refuse text generation while exposing an unavailable capability."""

    @property
    def available(self) -> bool:
        """A disabled provider never accepts requests."""
        return False

    def complete(self, request: CompletionRequest) -> str:
        """Reject generation attempts without inspecting the request content."""
        return ""

    def complete_structured[Response: BaseModel](
        self,
        request: CompletionRequest,
        response: type[Response],
    ) -> Response:
        """Reject structured generation because no provider is configured."""
        raise LLMUnavailableError("No LLM provider is configured.")

    @classmethod
    def from_env(cls) -> LLMService:
        """Build the disabled implementation without recursing through the selector."""
        return cls()
