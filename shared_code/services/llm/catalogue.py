"""Public OpenRouter model metadata for the admin comparison picker."""

import math
import typing as t

import requests

from shared_code.data_model import AnyDict

from .contracts import CatalogueModel

MODEL_CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
ZDR_ENDPOINTS_URL = "https://openrouter.ai/api/v1/endpoints/zdr"
DUTCH_USAGE_URL = "https://openrouter.ai/api/frontend/v1/rankings/natural-language"


class DutchUsage(t.TypedDict):
    """Estimated language-tagged usage from OpenRouter's rolling chart window."""

    tokens: dict[str, float]
    start_date: str
    end_date: str


def nonnegative_number(value: object) -> float | None:
    """Keep finite advertised metrics, treating missing and dynamic prices as unknown."""
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def parse_catalogue_model(raw: AnyDict) -> CatalogueModel | None:
    """Only offer synchronous text models advertising JSON schema and response format."""
    identifier = raw.get("id")
    parameters = raw.get("supported_parameters", [])
    architecture = raw.get("architecture") or {}
    if (
        not isinstance(identifier, str)
        or identifier.endswith(":batch")
        or not isinstance(parameters, list)
        or not {"structured_outputs", "response_format"}.issubset(parameters)
        or not isinstance(architecture, dict)
        or architecture.get("output_modalities") != ["text"]
        or "text" not in architecture.get("input_modalities", [])
    ):
        return None
    prices = raw.get("pricing") or {}
    if not isinstance(prices, dict):
        prices = {}
    input_price = nonnegative_number(prices.get("prompt"))
    output_price = nonnegative_number(prices.get("completion"))
    if (
        identifier.endswith(":free")
        or identifier == "openrouter/free"
        or input_price is None
        or output_price is None
        or input_price + output_price == 0
    ):
        return None
    benchmarks = raw.get("benchmarks") or {}
    intelligence = None
    if isinstance(benchmarks, dict) and isinstance(analysis := benchmarks.get("artificial_analysis"), dict):
        intelligence = nonnegative_number(analysis.get("intelligence_index"))
    return CatalogueModel(
        id=identifier,
        canonical_slug=str(raw.get("canonical_slug") or identifier),
        name=str(raw.get("name") or identifier),
        input_price=input_price * 1_000_000 if input_price is not None else None,
        output_price=output_price * 1_000_000 if output_price is not None else None,
        context_length=int(nonnegative_number(raw.get("context_length")) or 0),
        intelligence=intelligence,
        dutch_tokens=None,
    )


def fetch_private_endpoints(http_client: requests.Session | None = None) -> dict[str, list[AnyDict]]:
    """Fail closed unless OpenRouter advertises a paid, JSON-capable ZDR endpoint."""
    if http_client is None:
        response = requests.get(ZDR_ENDPOINTS_URL, timeout=10)
    else:
        response = http_client.get(ZDR_ENDPOINTS_URL, timeout=10)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("OpenRouter returned invalid privacy endpoint metadata.")
    endpoints: dict[str, list[AnyDict]] = {}
    for raw in body["data"]:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("model_id")
        parameters = raw.get("supported_parameters")
        prices = raw.get("pricing")
        if (
            not isinstance(identifier, str)
            or identifier.endswith(":free")
            or identifier == "openrouter/free"
            or not isinstance(raw.get("tag"), str)
            or not isinstance(parameters, list)
            or not {"structured_outputs", "response_format"}.issubset(parameters)
            or not isinstance(prices, dict)
        ):
            continue
        input_price = nonnegative_number(prices.get("prompt"))
        output_price = nonnegative_number(prices.get("completion"))
        if input_price is None or output_price is None or input_price + output_price == 0:
            continue
        endpoints.setdefault(identifier, []).append(raw)
    return endpoints


def fetch_model_catalogue() -> list[CatalogueModel]:
    """Fetch public metadata without credentials, excluding incompatible model variants."""
    response = requests.get(MODEL_CATALOGUE_URL, timeout=10)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("OpenRouter returned an invalid model catalogue.")
    private_endpoints = fetch_private_endpoints()
    models = []
    for raw in body["data"]:
        if isinstance(raw, dict) and (model := parse_catalogue_model(raw)) is not None:
            endpoints = private_endpoints.get(model["id"])
            if not endpoints:
                continue
            cheapest = min(
                endpoints,
                key=lambda endpoint: float(endpoint["pricing"]["prompt"]) + float(endpoint["pricing"]["completion"]),
            )
            model["input_price"] = float(cheapest["pricing"]["prompt"]) * 1_000_000
            model["output_price"] = float(cheapest["pricing"]["completion"]) * 1_000_000
            models.append(model)
    if not models:
        raise ValueError("OpenRouter returned no compatible text models.")
    return sorted(models, key=lambda model: model["name"].casefold())


def fetch_dutch_usage() -> DutchUsage:
    """Read the public website chart; callers must tolerate this non-versioned contract."""
    response = requests.get(DUTCH_USAGE_URL, params={"tag": "Dutch"}, timeout=5)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("OpenRouter returned invalid Dutch usage data.")
    tokens: dict[str, float] = {}
    dates: list[str] = []
    for row in body["data"]:
        if not isinstance(row, dict) or not isinstance(row.get("ys"), dict) or not isinstance(row.get("x"), str):
            continue
        dates.append(row["x"])
        for slug, value in row["ys"].items():
            count = nonnegative_number(value)
            if isinstance(slug, str) and slug.casefold() != "others" and count is not None:
                tokens[slug] = tokens.get(slug, 0) + count
    if not tokens or not dates:
        raise ValueError("OpenRouter returned no Dutch usage data.")
    return DutchUsage(tokens=tokens, start_date=min(dates), end_date=max(dates))
