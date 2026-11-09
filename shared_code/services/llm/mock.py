"""Deterministic LLM implementation for local development."""

from pydantic import BaseModel

from .contracts import CompletionRequest, LLMService
from .limits import validate_completion_input


class MockLLMService(LLMService):
    """Return the original input text as a predictable generated response."""

    @property
    def available(self) -> bool:
        """The mock is always ready to accept requests."""
        return True

    def complete(self, request: CompletionRequest) -> str:
        """Return the original text so callers can exercise the full workflow."""
        validate_completion_input(request["context"], request["input_text"])
        return request["input_text"]

    def complete_structured[Response: BaseModel](
        self,
        request: CompletionRequest,
        response: type[Response],
    ) -> Response:
        """Validate the request's deterministic mock payload as the requested type."""
        validate_completion_input(request["context"], request["input_text"])
        return response.model_validate(request.get("mock_response", {}))

    @classmethod
    def from_env(cls) -> MockLLMService:
        """Build the mock implementation without recursing through the selector."""
        return cls()
