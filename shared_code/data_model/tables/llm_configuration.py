"""Saved vision prompts, scoped activation snapshots, and playground input."""

from typedal.fields import TextField, TypedField

from shared_code.data_model.fields import OptionalUUIDField
from shared_code.data_model.tables.base import BaseTable


class LLMPrompt(BaseTable):
    """An editable named system prompt, independent of its activation snapshot."""

    name = TypedField(str, length=120, required=True)
    instructions = TextField(required=True)


class LLMConfiguration(BaseTable):
    """The activated model and instructions for a scope, with null meaning global."""

    scope_gid = OptionalUUIDField()
    model = TypedField(str, length=255, required=True)
    prompt_gid = OptionalUUIDField()
    prompt_name = TypedField(str, length=120, required=True)
    instructions = TextField(required=True)


class LLMPlaygroundScenario(BaseTable):
    """One saved editable synthetic scenario per scope."""

    scope_gid = OptionalUUIDField()
    context_json = TypedField(dict[str, object], type="json", required=True)
