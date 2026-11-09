"""Tests for LLM service selection."""

import typing as t

import pytest
import requests

from shared_code.data_model import AnyDict
from shared_code.services.llm import DisabledLLMService, LLMService, MockLLMService
from shared_code.services.llm.catalogue import ZDR_ENDPOINTS_URL
from shared_code.services.llm.openrouter import OpenRouterLLMService


def test_default_llm_service_is_disabled() -> None:
    """The production DI path should construct the disabled default implementation."""
    service1 = LLMService.with_injected()
    service2 = DisabledLLMService.with_injected()
    service3 = MockLLMService.with_injected()

    assert isinstance(service1, DisabledLLMService)
    assert isinstance(service2, DisabledLLMService)
    assert isinstance(service3, MockLLMService)
    assert service1.available is False
    assert service3.available is True


def test_llm_service_from_env_builds_configured_openrouter_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter configuration selects the provider without making an HTTP request."""
    monkeypatch.setenv("AI_PROVIDER", " OpenRouter ")
    monkeypatch.setenv("AI_API_KEY", "test-api-key")
    monkeypatch.setenv("AI_MODEL", "openai/gpt-5")
    monkeypatch.setenv("AI_HOST", "https://gateway.example.test/api/v1/")

    service = LLMService.with_injected()

    assert isinstance(service, OpenRouterLLMService)
    assert service.available is True
    assert service.api_key == "test-api-key"
    assert service.model == "openai/gpt-5"
    assert service.base_url == "https://gateway.example.test/api/v1"


class OpenRouterResponse:
    """Minimal HTTP response double for the OpenRouter client boundary."""

    def __init__(self, body: object) -> None:
        self.body = body
        self.status_checked = False

    def raise_for_status(self) -> None:
        """Record that the service checked the provider response status."""
        self.status_checked = True

    def json(self) -> object:
        """Return the configured provider response body."""
        return self.body


class RecordingOpenRouterSession:
    """In-memory transport that records the request without contacting OpenRouter."""

    def __init__(self, response: OpenRouterResponse, endpoints: list[AnyDict] | None = None) -> None:
        self.response = response
        self.requests: list[AnyDict] = []
        self.metadata_requests: list[AnyDict] = []
        if endpoints is None:
            endpoints = [
                {
                    "model_id": model,
                    "tag": "private-provider",
                    "supported_parameters": ["structured_outputs", "response_format"],
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                }
                for model in ("openai/gpt-5", "openai/gpt-4.1-mini")
            ]
        self.endpoints = endpoints

    def get(self, url: str, **kwargs: object) -> OpenRouterResponse:
        """Return public privacy metadata through the injected transport."""
        self.metadata_requests.append({"url": url, **kwargs})
        return OpenRouterResponse({"data": self.endpoints})

    def post(self, url: str, **kwargs: object) -> OpenRouterResponse:
        """Record one completion request and return its configured response."""
        self.requests.append({"url": url, **kwargs})
        return self.response


def test_openrouter_completion_builds_request_and_returns_text() -> None:
    """OpenRouter sends provider-compatible messages and returns the completion text."""
    response = OpenRouterResponse({"choices": [{"message": {"content": "Aangescherpte visie"}}]})
    session = RecordingOpenRouterSession(response)
    service = OpenRouterLLMService(
        api_key="test-api-key",
        model="openai/gpt-5",
        base_url="https://gateway.example.test/api/v1/",
        http_client=t.cast(requests.Session, session),
        timeout_seconds=12,
    )

    completion = service.complete(
        {
            "instructions": "Schrijf een visie.",
            "context": "Team Rekenen",
            "input_text": "Bestaande visie",
        }
    )

    assert completion == "Aangescherpte visie"
    assert response.status_checked is True
    assert session.requests[0] == {
        "url": "https://gateway.example.test/api/v1/chat/completions",
        "json": {
            "model": "openai/gpt-5",
            "provider": {
                "only": ["private-provider"],
                "data_collection": "deny",
                "zdr": True,
                "require_parameters": True,
            },
            "messages": [
                {"role": "system", "content": "Schrijf een visie."},
                {"role": "user", "content": "Team Rekenen\n\nBestaande visie"},
            ],
        },
        "headers": {
            "Authorization": "Bearer test-api-key",
            "Content-Type": "application/json",
        },
        "timeout": 12,
    }

    assert (
        service._completion_content(
            {
                "model": "openai/gpt-4.1-mini",
                "instructions": "Schrijf JSON.",
                "context": "Team Rekenen",
                "input_text": "",
            },
            response_format={"type": "json_schema"},
        )
        == "Aangescherpte visie"
    )
    assert session.requests[1]["json"] == {
        "model": "openai/gpt-4.1-mini",
        "provider": {
            "only": ["private-provider"],
            "data_collection": "deny",
            "zdr": True,
            "require_parameters": True,
        },
        "messages": [
            {"role": "system", "content": "Schrijf JSON."},
            {"role": "user", "content": "Team Rekenen"},
        ],
        "response_format": {"type": "json_schema"},
    }
    assert session.metadata_requests == [{"url": ZDR_ENDPOINTS_URL, "timeout": 10}] * 2


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"choices": []}, "no completion content"),
        ({"choices": [{"message": {"content": None}}]}, "non-text completion content"),
    ],
)
def test_openrouter_completion_rejects_malformed_content(body: object, message: str) -> None:
    """Malformed provider payloads fail explicitly instead of becoming application text."""
    service = OpenRouterLLMService(
        api_key="test-api-key",
        model="openai/gpt-5",
        http_client=t.cast(
            requests.Session,
            RecordingOpenRouterSession(OpenRouterResponse(body)),
        ),
    )

    with pytest.raises(ValueError, match=message):
        service.complete({"instructions": "Instructie", "context": "Context", "input_text": ""})


@pytest.mark.parametrize(
    "endpoints",
    [
        [],
        [
            {
                "model_id": "openai/gpt-5",
                "tag": "free-provider",
                "supported_parameters": ["structured_outputs", "response_format"],
                "pricing": {"prompt": "0", "completion": "0"},
            }
        ],
    ],
)
def test_openrouter_rejects_models_without_paid_private_endpoints(endpoints: list[AnyDict]) -> None:
    """Missing or free-only privacy routes must fail before any prompt is sent."""
    session = RecordingOpenRouterSession(OpenRouterResponse({}), endpoints=endpoints)
    service = OpenRouterLLMService(
        api_key="test-api-key",
        model="openai/gpt-5",
        http_client=t.cast(requests.Session, session),
    )

    with pytest.raises(ValueError, match="geen betaalde JSON-provider met zero data retention"):
        service.complete({"instructions": "Instructie", "context": "Context", "input_text": ""})

    assert session.requests == []
