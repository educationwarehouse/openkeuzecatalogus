"""Vision-enhancement request construction for decision processes."""

import typing as t
from inspect import cleandoc

from pydantic import BaseModel, model_validator

from shared_code.data_model import (
    DecisionMaterialSelection,
    DecisionProcess,
    DecisionProcessNote,
    DecisionProsAndCons,
)
from shared_code.services.llm import CompletionRequest
from shared_code.services.llm.limits import validate_user_input
from shared_code.util.types import MultiValue

if t.TYPE_CHECKING:
    from shared_code.modules.decision_processes import DecisionProcessContext


class MaterialAssessmentSummary(t.TypedDict):
    """The collected assessment context for one selected learning material."""

    name: str
    material_type: str
    strengths: list[str]
    weaknesses: list[str]


class VisionEnhancementResponse(BaseModel):
    """Structured response expected from the vision-enhancement prompt."""

    theme: str
    current_vision: str
    improved_vision: str


class VisionEnhancementContext(BaseModel):
    """Structured facts shared by live generation and the admin playground."""

    team_name: str
    courses: list[str]
    levels: list[str]
    years: list[str]
    theme: str
    theme_label: str
    board_advice: str
    school_advice: str
    materials: list[MaterialAssessmentSummary]
    current_vision: str

    @model_validator(mode="after")
    def validate_input_limits(self) -> t.Self:
        """Apply the same free-text limits to production and playground inputs."""
        validate_user_input(self.model_dump())
        return self


def build_vision_enhancement_instructions(theme_label: str) -> str:
    """Build Dutch instructions for generating an enhanced vision for a theme."""
    return cleandoc(f"""Je bent een onderwijskundige adviseur die docenten helpt bij het formuleren van
    een heldere en concrete visie op leermaterialen.

    BELANGRIJK: Gebruik ALLEEN de onderstaande informatie.
    Verzin GEEN extra pluspunten, minpunten of andere details die niet expliciet zijn vermeld.

    Taak: Schrijf een verbeterde visie die:
    1. ALLEEN de hierboven genoemde sterke punten benadrukt
    2. ALLEEN de hierboven genoemde aandachtspunten (minpunten) vermeldt
    3. Het advies van bestuur en/of school integreert (indien beschikbaar)
    4. De huidige visie aanvult en verbetert (indien beschikbaar)
    5. Concreet en praktisch toepasbaar is voor docenten
    6. Aansluit bij het thema \"{theme_label}\"

    HERHALING: Verzin GEEN extra informatie. Baseer je visie uitsluitend op de hierboven vermelde feiten.

    Genereer een professionele, bondige visie in het Nederlands (maximaal 150 woorden).

    Vul een JSON-object in met:
    - theme: \"{theme_label}\"
    - current_vision: de aangeleverde huidige visie
    - improved_vision: jouw gegenereerde visie""")


def get_guidance_notes_by_organisation(organisation_gids: MultiValue[str], theme: str) -> dict[str, str]:
    """Return guidance-note content for one theme, indexed by organisation."""
    notes = DecisionProcessNote.where(
        DecisionProcessNote.organisation_gid.belongs(list(organisation_gids)) & (DecisionProcessNote.theme == theme),
    ).select(DecisionProcessNote.organisation_gid, DecisionProcessNote.content)

    return {note.organisation_gid: note.content or "" for note in notes}


def build_vision_enhancement_context(
    process_context: DecisionProcessContext,
    *,
    theme: str,
    theme_label: str,
    current_summary: str,
) -> str:
    """Serialize process facts as JSON, preserving lists and text boundaries."""
    process = process_context["process"]
    team = process_context["team"]
    school = process_context["school"]
    board = process_context["board"]

    notes_by_organisation = get_guidance_notes_by_organisation([board.gid, school.gid], theme=theme)

    return VisionEnhancementContext(
        team_name=team.name,
        courses=process.courses or [],
        levels=process.levels or [],
        years=process.years or [],
        theme=theme,
        theme_label=theme_label,
        board_advice=notes_by_organisation.get(board.gid, ""),
        school_advice=notes_by_organisation.get(school.gid, ""),
        materials=collect_material_assessment_summaries(process, theme=theme),
        current_vision=current_summary,
    ).model_dump_json()


def format_material_assessment_summaries(
    material_assessment_summaries: list[MaterialAssessmentSummary],
) -> str:
    """Format material assessment summaries as Dutch text for the enhancement prompt."""
    materials_text = ""
    for material in material_assessment_summaries:
        materials_text += f"\n{material['material_type'].capitalize()}: {material['name']}\n"
        if material["strengths"]:
            materials_text += "Pluspunten: " + ", ".join(material["strengths"]) + "\n"
        if material["weaknesses"]:
            materials_text += "Minpunten: " + ", ".join(material["weaknesses"]) + "\n"

    return materials_text


def collect_material_selections_and_assessments(
    process: DecisionProcess, theme: str
) -> tuple[
    dict[str, DecisionMaterialSelection],
    dict[str, list[DecisionProsAndCons]],
]:
    """Collect process materials and their pros-and-cons entries for a theme."""
    selections = {
        selection.gid: selection
        for selection in DecisionMaterialSelection.where(DecisionMaterialSelection.process_gid == process.gid)
    }
    assessments_by_selection: dict[str, list[DecisionProsAndCons]] = {}
    for assessment in DecisionProsAndCons.where(
        (DecisionProsAndCons.process_gid == process.gid) & (DecisionProsAndCons.theme == theme),
    ):
        if assessment.material_selection_gid:
            assessments_by_selection.setdefault(assessment.material_selection_gid, []).append(assessment)

    return selections, assessments_by_selection


def collect_material_assessment_summaries(process: DecisionProcess, theme: str) -> list[MaterialAssessmentSummary]:
    """Return assessed material summaries for the process theme."""
    selections, assessments_by_selection = collect_material_selections_and_assessments(process, theme=theme)

    material_assessment_summaries: list[MaterialAssessmentSummary] = []
    for selection_gid, assessments in assessments_by_selection.items():
        selection = selections.get(selection_gid)
        if not selection:
            continue
        material_assessment_summaries.append(
            MaterialAssessmentSummary(
                name=selection.name,
                material_type=selection.material_type,
                strengths=[item.content for item in assessments if item.item_type == "pro" and item.content],
                weaknesses=[item.content for item in assessments if item.item_type == "con" and item.content],
            )
        )

    return material_assessment_summaries


def build_vision_enhancement_request(
    process_context: DecisionProcessContext,
    *,
    theme: str,
    theme_label: str,
    current_summary: str,
) -> CompletionRequest:
    """Snapshot the activated configuration and JSON facts before enqueueing."""
    from shared_code.modules.llm_playground import resolve_configuration

    configuration = resolve_configuration()
    return CompletionRequest(
        model=configuration["model"],
        instructions=configuration["instructions"].replace("{theme_label}", theme_label),
        context=build_vision_enhancement_context(
            process_context,
            theme=theme,
            theme_label=theme_label,
            current_summary=current_summary,
        ),
        input_text="",
        mock_response={
            "theme": theme_label,
            "current_vision": current_summary,
            "improved_vision": current_summary,
        },
    )
