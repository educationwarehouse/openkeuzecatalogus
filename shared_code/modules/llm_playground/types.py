"""Typed values for the LLM playground configuration."""

import typing as t


class ConfigurationSnapshot(t.TypedDict):
    """Immutable values used to build or activate one request."""

    model: str
    prompt_gid: str | None
    prompt_name: str
    instructions: str
