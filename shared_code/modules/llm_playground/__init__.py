"""Admin-managed vision configuration and shared playground request building."""

import os
import re
import typing as t

from shared_code.data_model import LLMConfiguration, LLMPlaygroundScenario, LLMPrompt
from shared_code.modules.decision_processes.ai import (
    VisionEnhancementContext,
    build_vision_enhancement_instructions,
)
from shared_code.services.llm import CompletionRequest

DEFAULT_PROMPT_NAME = "Standaard visieprompt"
MAX_COMBINATIONS = 16
MODEL_ID_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9./:_-]{0,254}")


class ConfigurationSnapshot(t.TypedDict):
    """Immutable values used to build or activate one request."""

    model: str
    prompt_gid: str | None
    prompt_name: str
    instructions: str


def default_instructions() -> str:
    """Retain the existing instructions with a documented theme placeholder."""
    return build_vision_enhancement_instructions("{theme_label}")


def resolve_configuration(scope_gid: str | None = None) -> ConfigurationSnapshot:
    """Resolve an explicit scope first, then the global activation or env default."""
    configuration = None
    if scope_gid:
        configuration = LLMConfiguration.where(LLMConfiguration.scope_gid == scope_gid).first()
    if configuration is None:
        configuration = LLMConfiguration.where(LLMConfiguration.scope_gid == None).first()
    if configuration is None:
        return ConfigurationSnapshot(
            model=os.environ.get("AI_MODEL", ""),
            prompt_gid=None,
            prompt_name=DEFAULT_PROMPT_NAME,
            instructions=default_instructions(),
        )
    return ConfigurationSnapshot(
        model=configuration.model,
        prompt_gid=configuration.prompt_gid,
        prompt_name=configuration.prompt_name,
        instructions=configuration.instructions,
    )


def default_scenario() -> VisionEnhancementContext:
    """Return fresh synthetic data for the single editable playground scenario."""
    return VisionEnhancementContext(
        team_name="Vakgroep Nederlands (voorbeeld)",
        courses=["Nederlands"],
        levels=["havo"],
        years=["2"],
        theme="didactiek",
        theme_label="Didactiek",
        board_advice="Stimuleer zelfstandig leren en bied ruimte voor verschillen tussen leerlingen.",
        school_advice="Gebruik herkenbare opdrachten en geef leerlingen regelmatig feedback.",
        materials=[
            {
                "name": "Voorbeeldmethode Taal",
                "material_type": "bought",
                "strengths": ["Heldere uitleg", "Opdrachten op verschillende niveaus"],
                "weaknesses": ["Weinig feedback bij digitale oefeningen"],
            },
            {
                "name": "Eigen leesopdrachten",
                "material_type": "created",
                "strengths": ["Herkenbare onderwerpen", "Leerlingen kiezen zelf een tekst"],
                "weaknesses": ["Veel voorbereiding nodig"],
            },
        ],
        current_vision="We willen leerlingen zelfstandig laten werken met duidelijke uitleg en passende opdrachten.",
    )


def saved_scenario() -> VisionEnhancementContext:
    """Load the global scenario without writing on a page visit."""
    scenario = LLMPlaygroundScenario.where(LLMPlaygroundScenario.scope_gid == None).first()
    if scenario:
        return VisionEnhancementContext.model_validate(scenario.context_json)
    return default_scenario()


def validate_model(model: str) -> str:
    """Accept a provider model identifier, rejecting whitespace and oversized input."""
    model = model.strip()
    if model.endswith(":free") or model == "openrouter/free":
        raise ValueError("Gratis modellen zijn uitgesloten. Kies een betaald model met zero data retention.")
    if not MODEL_ID_PATTERN.fullmatch(model):
        raise ValueError("Vul een geldig model-ID in, bijvoorbeeld openai/gpt-4.1-mini.")
    return model


def build_playground_request(
    scenario: VisionEnhancementContext, configuration: ConfigurationSnapshot
) -> CompletionRequest:
    """Use the production context schema and response shape with synthetic facts."""
    return CompletionRequest(
        model=validate_model(configuration["model"]),
        instructions=configuration["instructions"].replace("{theme_label}", scenario.theme_label),
        context=scenario.model_dump_json(),
        input_text="",
        mock_response={
            "theme": scenario.theme_label,
            "current_vision": scenario.current_vision,
            "improved_vision": scenario.current_vision,
        },
    )


def prompt_snapshot(prompt: LLMPrompt, model: str) -> ConfigurationSnapshot:
    """Freeze a saved prompt for a comparison and later explicit activation."""
    return ConfigurationSnapshot(
        model=validate_model(model),
        prompt_gid=str(prompt.gid),
        prompt_name=prompt.name,
        instructions=prompt.instructions,
    )


def save_prompt_draft(name: str, instructions: str, gid: str | None = None) -> LLMPrompt:
    """Save a validated draft without modifying any activated snapshot."""
    name = name.strip()
    if not name or len(name) > 120 or not instructions.strip() or len(instructions) > 20000:
        raise ValueError("Vul een naam en system prompt in (maximaal 120 en 20000 tekens).")
    if gid:
        prompt = LLMPrompt.where(LLMPrompt.gid == gid).first()
        if prompt is None:
            raise ValueError("Prompt niet gevonden.")
        prompt.update_record(name=name, instructions=instructions)
        return prompt
    return LLMPrompt.insert(name=name, instructions=instructions)


def delete_prompt_draft(gid: str) -> None:
    """Remove an inactive draft, preserving all activated configurations."""
    if LLMConfiguration.where(LLMConfiguration.prompt_gid == gid).first():
        raise ValueError("Deze prompt is actief. Activeer eerst een andere prompt.")
    prompt = LLMPrompt.where(LLMPrompt.gid == gid).first()
    if prompt is None:
        raise ValueError("Prompt niet gevonden.")
    prompt.delete_record()


def save_playground_scenario(scenario: VisionEnhancementContext) -> None:
    """Create or update the single global scenario through the ORM."""
    LLMPlaygroundScenario.update_or_insert(
        LLMPlaygroundScenario.scope_gid == None,
        scope_gid=None,
        context_json=scenario.model_dump(),
    )


def activate_snapshot(configuration: ConfigurationSnapshot) -> None:
    """Create or update the global activation with the exact tested snapshot."""
    LLMConfiguration.update_or_insert(
        LLMConfiguration.scope_gid == None,
        scope_gid=None,
        **configuration,
    )
