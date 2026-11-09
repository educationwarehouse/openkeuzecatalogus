"""Database-backed coverage of playground persistence and configuration behavior."""

import json
import typing as t
import uuid

import pytest

from shared_code.data_model import LLMConfiguration, LLMPlaygroundScenario, LLMPrompt
from shared_code.infra.database import DatabaseContext
from shared_code.modules.llm_playground import (
    DEFAULT_PROMPT_NAME,
    activate_snapshot,
    build_playground_request,
    default_instructions,
    default_scenario,
    delete_prompt_draft,
    prompt_snapshot,
    resolve_configuration,
    save_playground_scenario,
    save_prompt_draft,
    saved_scenario,
    validate_model,
)


@pytest.fixture()
def playground_db(db_per_file: DatabaseContext) -> t.Iterator[DatabaseContext]:
    """Keep each test's configuration and draft edits in its own transaction."""
    try:
        yield db_per_file
    finally:
        db_per_file.rollback()


def test_configuration_falls_back_to_environment_without_writing(
    playground_db: DatabaseContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unconfigured scope uses the environment and leaves activation empty."""
    monkeypatch.setenv("AI_MODEL", "openai/gpt-4.1-mini")

    configuration = resolve_configuration(scope_gid=str(uuid.uuid4()))

    assert configuration == {
        "model": "openai/gpt-4.1-mini",
        "prompt_gid": None,
        "prompt_name": DEFAULT_PROMPT_NAME,
        "instructions": default_instructions(),
    }
    assert "{theme_label}" in configuration["instructions"]
    assert all(not line.startswith("    ") for line in configuration["instructions"].splitlines())
    assert len(LLMConfiguration.collect()) == 0


def test_global_activation_replaces_previous_snapshot(playground_db: DatabaseContext) -> None:
    """Repeated activation updates the one global row and preserves frozen drafts."""
    first = save_prompt_draft("First", "Visie voor {theme_label}.")
    second = save_prompt_draft("Second", "Andere instructies.")
    first_snapshot = prompt_snapshot(first, model="openai/gpt-4.1-mini")
    activate_snapshot(first_snapshot)
    assert resolve_configuration() == first_snapshot

    second_snapshot = prompt_snapshot(second, model="google/gemini-3.5-flash-lite")
    activate_snapshot(second_snapshot)
    save_prompt_draft("Edited second", "Nieuwe conceptinstructies.", gid=str(second.gid))

    assert resolve_configuration() == second_snapshot
    assert resolve_configuration(scope_gid=str(uuid.uuid4())) == second_snapshot
    assert len(LLMConfiguration.collect()) == 1


def test_scoped_configuration_takes_precedence_over_global(playground_db: DatabaseContext) -> None:
    """A scope override does not change the configuration used by other scopes."""
    prompt = save_prompt_draft("Global", "Globale instructies.")
    global_snapshot = prompt_snapshot(prompt, model="openai/gpt-4.1-mini")
    activate_snapshot(global_snapshot)
    scope_gid = str(uuid.uuid4())
    scoped_prompt = save_prompt_draft("Scoped", "Instructies voor deze scope.")
    scoped_snapshot = prompt_snapshot(scoped_prompt, model="google/gemini-3.5-flash-lite")
    LLMConfiguration.insert(scope_gid=scope_gid, **scoped_snapshot)

    assert resolve_configuration(scope_gid=scope_gid) == scoped_snapshot
    assert resolve_configuration() == global_snapshot
    assert resolve_configuration(scope_gid=str(uuid.uuid4())) == global_snapshot


def test_scenario_defaults_are_independent_and_loading_does_not_write(playground_db: DatabaseContext) -> None:
    """Editing an unsaved example does not alter later defaults or create a row."""
    scenario = saved_scenario()
    scenario.courses.append("Rekenen")
    scenario.materials[0]["strengths"].append("Een lokale wijziging")

    assert saved_scenario() == default_scenario()
    assert "Rekenen" not in default_scenario().courses
    assert "Een lokale wijziging" not in default_scenario().materials[0]["strengths"]
    assert len(LLMPlaygroundScenario.collect()) == 0


def test_scenario_save_round_trips_and_updates_one_global_row(playground_db: DatabaseContext) -> None:
    """Saved lists, multiline text and materials survive both insert and overwrite."""
    scenario = default_scenario()
    scenario.team_name = 'Team "Taal"'
    scenario.current_vision = "Eerste regel\nTweede regel"
    scenario.courses = ["Nederlands", "Rekenen"]
    save_playground_scenario(scenario)
    assert saved_scenario() == scenario

    scenario.materials = []
    scenario.current_vision = "Bijgewerkte visie"
    save_playground_scenario(scenario)

    assert saved_scenario() == scenario
    assert len(LLMPlaygroundScenario.collect()) == 1


def test_playground_request_preserves_json_boundaries_and_expands_theme(playground_db: DatabaseContext) -> None:
    """Comparison input preserves literal quotes and newlines and freezes the prompt."""
    scenario = default_scenario()
    scenario.theme_label = 'Taal "en" lezen'
    scenario.current_vision = "Bestaande visie\nMet een tweede regel"
    prompt = save_prompt_draft("Comparison", "Thema: {theme_label}. Herhaal {theme_label}.")
    snapshot = prompt_snapshot(prompt, model=" openai/gpt-4.1-mini ")
    save_prompt_draft("Edited", "Andere instructies.", gid=str(prompt.gid))

    request = build_playground_request(scenario, snapshot)

    assert request["model"] == "openai/gpt-4.1-mini"
    assert request["instructions"] == 'Thema: Taal "en" lezen. Herhaal Taal "en" lezen.'
    assert json.loads(request["context"]) == scenario.model_dump()
    assert request["input_text"] == ""
    assert request["mock_response"] == {
        "theme": scenario.theme_label,
        "current_vision": scenario.current_vision,
        "improved_vision": scenario.current_vision,
    }
    assert snapshot["prompt_name"] == "Comparison"


@pytest.mark.parametrize("model", ["", "openai/a b", "openai/a\nb", "a" * 256, "../model"])
def test_model_validation_rejects_invalid_ids(model: str) -> None:
    """Invalid identifiers fail before they can be queued or saved."""
    with pytest.raises(ValueError, match="geldig model-ID"):
        validate_model(model)


@pytest.mark.parametrize("model", ["openrouter/free", "meta-llama/llama-3.3-70b-instruct:free"])
def test_model_validation_rejects_free_routes(model: str) -> None:
    """Manual identifiers cannot bypass the free-model exclusion."""
    with pytest.raises(ValueError, match="Gratis modellen"):
        validate_model(model)


@pytest.mark.parametrize(
    ("name", "instructions"),
    [(" ", "Prompt"), ("a" * 121, "Prompt"), ("Name", " \n"), ("Name", "a" * 20001)],
)
def test_prompt_validation_rejects_empty_and_oversized_drafts(
    playground_db: DatabaseContext, name: str, instructions: str
) -> None:
    """Invalid drafts leave the saved prompt collection unchanged."""
    count = len(LLMPrompt.collect())
    with pytest.raises(ValueError, match="naam en system prompt"):
        save_prompt_draft(name, instructions)
    assert len(LLMPrompt.collect()) == count


def test_prompt_create_update_and_delete(playground_db: DatabaseContext) -> None:
    """Draft updates preserve identity and inactive drafts can be removed."""
    prompt = save_prompt_draft("  New prompt  ", "Instructies.")
    assert prompt.name == "New prompt"

    updated = save_prompt_draft("Renamed", "Bijgewerkte instructies.", gid=str(prompt.gid))
    assert updated.gid == prompt.gid
    persisted = LLMPrompt.where(LLMPrompt.gid == prompt.gid).first()
    assert persisted is not None
    assert persisted.name == "Renamed"
    assert persisted.instructions == "Bijgewerkte instructies."

    delete_prompt_draft(str(prompt.gid))
    assert LLMPrompt.where(LLMPrompt.gid == prompt.gid).first() is None


@pytest.mark.parametrize("scope_gid", [None, str(uuid.uuid4())])
def test_active_prompts_cannot_be_deleted(playground_db: DatabaseContext, scope_gid: str | None) -> None:
    """Deletion protects both global and scoped active configurations."""
    prompt = save_prompt_draft("Protected", "Instructies.")
    snapshot = prompt_snapshot(prompt, model="openai/gpt-4.1-mini")
    LLMConfiguration.insert(scope_gid=scope_gid, **snapshot)

    with pytest.raises(ValueError, match="prompt is actief"):
        delete_prompt_draft(str(prompt.gid))

    assert LLMPrompt.where(LLMPrompt.gid == prompt.gid).first() is not None
    assert len(LLMConfiguration.collect()) == 1


def test_missing_prompts_cannot_be_updated_or_deleted(playground_db: DatabaseContext) -> None:
    """A stale editor receives a useful error instead of creating another draft."""
    missing_gid = str(uuid.uuid4())
    with pytest.raises(ValueError, match="Prompt niet gevonden"):
        save_prompt_draft("Missing", "Instructies.", gid=missing_gid)
    with pytest.raises(ValueError, match="Prompt niet gevonden"):
        delete_prompt_draft(missing_gid)
