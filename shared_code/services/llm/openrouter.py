"""OpenRouter routing and public model metadata."""

import logging
import os

import requests

from ...data_model import AnyDict
from .catalogue import fetch_dutch_usage, fetch_model_catalogue, fetch_private_endpoints
from .contracts import CompletionRequest, ModelCatalogue, UsagePeriod
from .openai_compatible import OpenAICompatibleLLMService

logger = logging.getLogger(__name__)


class OpenRouterLLMService(OpenAICompatibleLLMService):
    """Add paid JSON-capable ZDR routing to shared chat completions."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        http_client: requests.Session | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        """Keep the OpenRouter default endpoint and injectable HTTP transport."""
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
        )

    def list_models(self) -> ModelCatalogue:
        """List paid private models and optionally enrich them with Dutch usage."""
        models = fetch_model_catalogue()

        dutch_usage_period = None
        try:
            usage = fetch_dutch_usage()
        except (ValueError, requests.RequestException) as exc:
            logger.warning("Dutch OpenRouter usage unavailable; using catalogue rankings: %s", exc)
        else:
            dutch_usage_period = UsagePeriod(start_date=usage["start_date"], end_date=usage["end_date"])
            for model in models:
                model["dutch_tokens"] = usage["tokens"].get(model["canonical_slug"])

        return ModelCatalogue(models=models, dutch_usage_period=dutch_usage_period)

    def _completion_content(
        self,
        request: CompletionRequest,
        response_format: AnyDict | None = None,
        provider_options: AnyDict | None = None,
    ) -> str:
        """Refresh privacy metadata before submitting any prompt to OpenRouter."""
        model = request.get("model") or self.model
        endpoints = fetch_private_endpoints(http_client=self.http_client).get(model)
        if not endpoints:
            raise ValueError(
                "Dit model heeft geen betaalde JSON-provider met zero data retention. Kies een ander model."
            )

        return super()._completion_content(
            request,
            response_format=response_format,
            provider_options={
                "only": sorted({endpoint["tag"] for endpoint in endpoints}),
                "data_collection": "deny",
                "zdr": True,
                "require_parameters": True,
            },
        )

    @classmethod
    def from_env(cls) -> OpenRouterLLMService:
        """Build an OpenRouter client from the shared AI environment settings."""
        api_key = os.environ.get("AI_API_KEY", "")
        model = os.environ.get("AI_MODEL", "")
        if not api_key or not model:
            raise OSError("AI_API_KEY and AI_MODEL are required for AI_PROVIDER=openrouter.")
        return cls(
            api_key=api_key,
            model=model,
            base_url=os.environ.get("AI_HOST") or "https://openrouter.ai/api/v1",
        )
