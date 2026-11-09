"""Configurable limits for free text submitted to language models."""

import json
import os
import typing as t

FIELD_MAX_CHARS = int(os.getenv("LLM_FIELD_MAX_CHARS", "20000"))
CALL_MAX_CHARS = int(os.getenv("LLM_CALL_MAX_CHARS", "100000"))


class LLMInputError(ValueError):
    """User input exceeds a configured field or per-call budget."""


def validate_user_input(value: t.Any) -> None:
    """Reject oversized fields and combined user input without truncating text."""

    def count(item: t.Any) -> int:
        if isinstance(item, str):
            if len(item) > FIELD_MAX_CHARS:
                raise LLMInputError(f"AI-invoer mag maximaal {FIELD_MAX_CHARS} tekens per tekstveld bevatten.")

            return len(item)
        elif isinstance(item, dict):
            return sum(count(part) for part in item.values())
        elif isinstance(item, (tuple, list)):
            return sum(count(part) for part in item)

        return 0

    if count(value) > CALL_MAX_CHARS:
        raise LLMInputError(f"AI-invoer mag in totaal maximaal {CALL_MAX_CHARS} tekens per aanvraag bevatten.")


def validate_completion_input(context: str, input_text: str) -> None:
    """Check both structured process context and direct text before provider calls."""
    try:
        parsed_context = json.loads(context)
    except ValueError:
        parsed_context = context

    validate_user_input([parsed_context, input_text])
