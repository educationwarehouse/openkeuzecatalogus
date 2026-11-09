"""Pure unit tests for decision-process vision AI request construction."""

import json
import typing as t
import uuid

import pytest

from shared_code.data_model import AuthUser, DecisionProsAndCons, AnyMapping, AnyDict, LLMConfiguration, LLMPrompt
from shared_code.data_model.constants import AI_QUERY_LIMIT, get_themes
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.modules.decision_processes.ai import (
    VisionEnhancementResponse,
    build_vision_enhancement_context,
    build_vision_enhancement_instructions,
    build_vision_enhancement_request,
    collect_material_assessment_summaries,
    format_material_assessment_summaries,
    get_guidance_notes_by_organisation,
)
from shared_code.services.deferred import DeferredJob, DeferredPoll, DeferredResult, DeferredWork
from shared_code.services.llm import DisabledLLMService, LLMUnavailableError, MockLLMService
from shared_code.modules.llm_playground import activate_snapshot, prompt_snapshot
from shared_code.util.olid import generate as generate_olid

VESTIGING_CENTRUM_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"


class _RecordingDeferredWork(DeferredWork):
    """Deferred-work contract double that records vision enhancement submissions."""

    def __init__(self) -> None:
        self.submissions: list[tuple[str, AnyMapping]] = []

    def enqueue(self, entrypoint: str, payload: AnyMapping) -> DeferredJob:
        """Record one submission and return an opaque job reference."""
        self.submissions.append((entrypoint, payload))
        return DeferredJob(key=uuid.uuid4(), entrypoint=entrypoint)

    def result(self, job: DeferredJob) -> DeferredResult:
        """The test only submits jobs, so no result is available."""
        return DeferredResult(status="pending")

    def create_poll_token[ContextT: AnyDict](self, job: DeferredJob, context: ContextT) -> str:
        """Polling is outside the scope of this submission-only double."""
        raise NotImplementedError

    def resolve_poll_token[ContextT: AnyDict](self, token: str) -> DeferredPoll[ContextT]:
        """Polling is outside the scope of this submission-only double."""
        raise NotImplementedError


@pytest.fixture()
def ai_backend(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> DecisionProcessBackend:
    """Return a decision-process backend acting as an admin."""
    return DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
    )


def test_build_vision_enhancement_instructions_includes_selected_theme() -> None:
    """The Dutch prompt pins the selected theme without inventing assessment details."""
    instructions = build_vision_enhancement_instructions("Rekenen")

    assert 'Aansluit bij het thema "Rekenen"' in instructions
    assert "BELANGRIJK: Gebruik ALLEEN de onderstaande informatie." in instructions
    assert "Verzin GEEN extra informatie." in instructions


def test_format_material_assessment_summaries_handles_empty_assessments() -> None:
    """No assessments render as an empty material block."""
    assert format_material_assessment_summaries([]) == ""


def test_format_material_assessment_summaries_renders_strengths_and_weaknesses() -> None:
    """Each assessment keeps its material type, strengths, and weaknesses in Dutch."""
    text = format_material_assessment_summaries(
        [
            {
                "name": "Methode Rekenen",
                "material_type": "methode",
                "strengths": ["Duidelijke opbouw"],
                "weaknesses": ["Beperkt differentiatiemateriaal"],
            }
        ]
    )

    assert text == (
        "\nMethode: Methode Rekenen\nPluspunten: Duidelijke opbouw\nMinpunten: Beperkt differentiatiemateriaal\n"
    )


def test_vision_enhancement_response_validates_structured_contract() -> None:
    """The LLM response model validates the three fields used by the prompt."""
    response = VisionEnhancementResponse.model_validate(
        {
            "theme": "Rekenen",
            "current_vision": "Bestaande visie",
            "improved_vision": "Aangescherpte visie",
        }
    )

    assert response.theme == "Rekenen"
    assert response.current_vision == "Bestaande visie"
    assert response.improved_vision == "Aangescherpte visie"


def test_collect_material_assessment_summaries_uses_theme_pros_and_cons(
    ai_backend: DecisionProcessBackend,
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
) -> None:
    """Material selections become summaries only when their pros/cons match the theme."""
    theme = next(iter(get_themes()))
    team = ai_backend.create_team(VESTIGING_CENTRUM_GID, "AI Materials Team")
    process = ai_backend.create_process(team.gid, "2026-2027")
    ai_backend.change_material_selection(
        process.gid, "add", "bought", "Methode Plus", generate_olid("product", "OLID-AI-1")
    )
    selection = ai_backend.material_selections(process.gid)[0]

    DecisionProsAndCons.insert(
        process_gid=process.gid,
        user_gid=admin_user.gid,
        material_selection_gid=selection.gid,
        item_type="pro",
        theme=theme,
        content="Duidelijke opbouw",
    )
    DecisionProsAndCons.insert(
        process_gid=process.gid,
        user_gid=admin_user.gid,
        material_selection_gid=selection.gid,
        item_type="con",
        theme=theme,
        content="Beperkt oefenmateriaal",
    )
    db_per_file.commit()

    summaries = collect_material_assessment_summaries(ai_backend.get_process(process.gid), theme)

    assert summaries == [
        {
            "name": "Methode Plus",
            "material_type": "bought",
            "strengths": ["Duidelijke opbouw"],
            "weaknesses": ["Beperkt oefenmateriaal"],
        }
    ]


def test_build_vision_enhancement_request_includes_guidance_and_material_context(
    ai_backend: DecisionProcessBackend,
) -> None:
    """The provider-neutral request combines team, guidance, materials, and mock output."""
    theme = next(iter(get_themes()))
    team = ai_backend.create_team(
        VESTIGING_CENTRUM_GID,
        "AI Request Team",
        courses=["Rekenen"],
        levels=["Havo"],
    )
    process = ai_backend.create_process(team.gid, "2026-2027")
    ai_backend.update_guidance_note(process.gid, "board", theme, "Bestuurskader")
    ai_backend.update_guidance_note(process.gid, "school", theme, "Schooladvies")

    context = ai_backend.get_process_context(process.gid)
    notes = get_guidance_notes_by_organisation([context["board"].gid, context["school"].gid], theme)
    request_context = build_vision_enhancement_context(
        context,
        theme=theme,
        theme_label="Rekenen",
        current_summary="Bestaande visie",
    )
    request = build_vision_enhancement_request(
        context,
        theme=theme,
        theme_label="Rekenen",
        current_summary="Bestaande visie",
    )

    assert notes == {
        context["board"].gid: "Bestuurskader",
        context["school"].gid: "Schooladvies",
    }
    assert json.loads(request_context) == {
        "team_name": "AI Request Team",
        "courses": ["Rekenen"],
        "levels": ["Havo"],
        "years": process.years or [],
        "theme": theme,
        "theme_label": "Rekenen",
        "board_advice": "Bestuurskader",
        "school_advice": "Schooladvies",
        "materials": [],
        "current_vision": "Bestaande visie",
    }
    assert request["context"] == request_context
    assert request["input_text"] == ""
    assert request["mock_response"] == {
        "theme": "Rekenen",
        "current_vision": "Bestaande visie",
        "improved_vision": "Bestaande visie",
    }


def test_enhance_vision_validates_availability_theme_and_usage_limit(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Vision enhancement queues one request only when AI is available and within its limit."""
    deferred = _RecordingDeferredWork()
    backend = DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
        llm=MockLLMService(),
        deferred=deferred,
    )
    team = backend.create_team(VESTIGING_CENTRUM_GID, "AI Enhancement Team")
    process = backend.create_process(team.gid, "2026-2027")
    theme = next(iter(get_themes()))

    job = backend.enhance_vision(process.gid, theme, "Bestaande visie")

    assert job.entrypoint == "enhance_vision"
    assert backend.get_process(process.gid).ai_usage == 1
    assert deferred.submissions[0][0] == "enhance_vision"
    assert deferred.submissions[0][1]["input_text"] == ""
    assert json.loads(deferred.submissions[0][1]["context"])["current_vision"] == "Bestaande visie"

    with pytest.raises(ValueError, match="Onbekend visiethema"):
        backend.enhance_vision(process.gid, "onbekend", "Bestaande visie")

    backend.get_process(process.gid).update_record(ai_usage=AI_QUERY_LIMIT)
    db_per_file.commit()
    with pytest.raises(LLMUnavailableError, match="AI-limiet bereikt"):
        backend.enhance_vision(process.gid, theme, "Bestaande visie")

    unavailable_backend = DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
        llm=DisabledLLMService(),
        deferred=deferred,
    )
    with pytest.raises(LLMUnavailableError, match="niet beschikbaar"):
        unavailable_backend.enhance_vision(process.gid, theme, "Bestaande visie")


def test_enhance_vision_uses_activated_model_and_frozen_prompt(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Live requests use the playground activation even after the draft is edited."""
    deferred = _RecordingDeferredWork()
    backend = DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
        llm=MockLLMService(),
        deferred=deferred,
    )
    team = backend.create_team(VESTIGING_CENTRUM_GID, "Activated AI Team")
    process = backend.create_process(team.gid, "2026-2027")
    theme, theme_label = next(iter(get_themes().items()))
    prompt = LLMPrompt.insert(name="Activated test prompt", instructions="Schrijf een visie voor {theme_label}.")
    try:
        activate_snapshot(prompt_snapshot(prompt, model="openai/gpt-4.1-mini"))
        prompt.update_record(instructions="Nog niet geactiveerde wijziging.")
        db_per_file.commit()

        backend.enhance_vision(process.gid, theme, "Bestaande visie")

        payload = deferred.submissions[0][1]
        assert payload["model"] == "openai/gpt-4.1-mini"
        assert payload["instructions"] == f"Schrijf een visie voor {theme_label}."
        assert json.loads(payload["context"])["theme"] == theme
    finally:
        LLMConfiguration.where(LLMConfiguration.prompt_gid == prompt.gid).delete()
        prompt.delete_record()
        db_per_file.commit()
