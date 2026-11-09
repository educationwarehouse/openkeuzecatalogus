"""Provider-neutral OpenAI-compatible chat completions."""

import os

import requests
from pydantic import BaseModel

from ...data_model import AnyDict
from .contracts import CompletionRequest, LLMService
from .limits import validate_completion_input


class OpenAICompatibleLLMService(LLMService):
    """Send standard chat-completions requests to a configured gateway."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        http_client: requests.Session | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        """Configure the API endpoint, model, and HTTP transport."""
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or requests.Session()
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        """A configured OpenAI-compatible client is ready to send requests."""
        return True

    def complete(self, request: CompletionRequest) -> str:
        """Generate plain text through the configured gateway."""
        return self._completion_content(request)

    def complete_structured[Response: BaseModel](
        self,
        request: CompletionRequest,
        response: type[Response],
    ) -> Response:
        """Request strict JSON-schema output and validate it as the requested model."""
        content = self._completion_content(
            request,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response.__name__,
                    "strict": True,
                    "schema": response.model_json_schema(),
                },
            },
        )
        return response.model_validate_json(content)

    def _completion_content(
        self,
        request: CompletionRequest,
        response_format: AnyDict | None = None,
        provider_options: AnyDict | None = None,
    ) -> str:
        """Submit one OpenAI-compatible chat-completions request."""
        validate_completion_input(request["context"], request["input_text"])
        user_content = request["context"]
        if request["input_text"]:
            user_content += f"\n\n{request['input_text']}"

        model = request.get("model") or self.model
        payload: AnyDict = {
            "model": model,
            "messages": [
                {"role": "system", "content": request["instructions"]},
                {"role": "user", "content": user_content},
            ],
        }
        if provider_options is not None:
            payload["provider"] = provider_options
        if response_format:
            payload["response_format"] = response_format
        api_response = self.http_client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout_seconds,
        )
        api_response.raise_for_status()
        body = api_response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError("OpenAI-compatible response has no completion content.") from exc
        if not isinstance(content, str):
            raise ValueError("OpenAI-compatible returned non-text completion content.")
        return content

    @classmethod
    def from_env(cls) -> OpenAICompatibleLLMService:
        """Build an OpenAI-compatible client from the shared AI environment settings."""
        api_key = os.environ.get("AI_API_KEY", "")
        model = os.environ.get("AI_MODEL", "")
        base_url = os.environ.get("AI_HOST", "")
        if not api_key or not model or not base_url:
            raise OSError("AI_API_KEY, AI_MODEL and AI_HOST are required for AI_PROVIDER=openai-compatible.")
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
