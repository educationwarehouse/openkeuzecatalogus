"""Provider-neutral contracts for text generation services."""

import abc
import os
import typing as t

from endow import Service
from pydantic import BaseModel

from shared_code.data_model import AnyDict


class CatalogueModel(t.TypedDict):
    """Provider model metadata for selection and optional ranking."""

    id: str
    canonical_slug: str
    name: str
    input_price: float | None
    output_price: float | None
    context_length: int
    intelligence: float | None
    dutch_tokens: float | None


class UsagePeriod(t.TypedDict):
    """Date range covered by aggregated token-usage rankings."""

    start_date: str
    end_date: str


class ModelCatalogue(t.TypedDict):
    """Optional provider catalogue; absence does not prevent manual model entry."""

    models: list[CatalogueModel]
    dutch_usage_period: UsagePeriod | None


class CompletionRequest(t.TypedDict):
    """The provider-neutral input for one text-completion request."""

    instructions: str
    context: str
    input_text: str

    model: t.NotRequired[str]

    mock_response: t.NotRequired[AnyDict]


class LLMUnavailableError(RuntimeError):
    """Raised when an unavailable LLM service is asked to generate text."""


class LLMService(Service, abc.ABC):
    """Synchronous contract for a configured text-generation provider."""

    def list_models(self) -> ModelCatalogue:
        """Default to manual model entry when a provider has no catalogue."""
        return ModelCatalogue(models=[], dutch_usage_period=None)

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """Return whether this deployment may submit LLM requests."""
        ...

    @abc.abstractmethod
    def complete(self, request: CompletionRequest) -> str:
        """Generate text from one provider-neutral completion request."""
        ...

    @abc.abstractmethod
    def complete_structured[Response: BaseModel](
        self, request: CompletionRequest, response: type[Response]
    ) -> Response:
        """Generate and validate one structured response of the requested model type."""
        ...

    @classmethod
    def from_env(cls) -> LLMService:
        """Build the configured LLM implementation, disabled by default."""
        provider = os.environ.get("AI_PROVIDER", "disabled").strip().lower()
        if provider == "mock":
            from .mock import MockLLMService

            return MockLLMService.from_env()
        elif provider in {"", "disabled", "none"}:
            from .disabled import DisabledLLMService

            return DisabledLLMService.from_env()
        elif provider == "openrouter":
            from .openrouter import OpenRouterLLMService

            return OpenRouterLLMService.from_env()

        elif provider == "openai-compatible":
            from .openai_compatible import OpenAICompatibleLLMService

            return OpenAICompatibleLLMService.from_env()

        else:
            raise ValueError(f"Unsupported AI_PROVIDER: {provider}")
