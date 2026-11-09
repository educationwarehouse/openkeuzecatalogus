"""Type definitions for decision-process application flows."""

import typing as t

from yatl import TAGGER as HTMLElement

from shared_code.data_model import (
    AuthUser,
    DecisionProcess,
    DecisionProsAndCons,
    DecisionTeam,
    DecisionThemeVision,
    Organisation,
)

ProsAndConsType = t.Literal["pro", "con"]
ProcessGuidanceLevel = t.Literal["board", "school"]
CriteriaField = t.Literal["courses", "levels", "years"]


class DecisionTeamContext(t.TypedDict):
    """The organisation hierarchy for one teaching team."""

    team: DecisionTeam
    school: Organisation
    board: Organisation


class DecisionProcessContext(t.TypedDict):
    """The organisation hierarchy and team for one decision process."""

    process: DecisionProcess
    team: DecisionTeam
    school: Organisation
    board: Organisation


class VisionContext(t.TypedDict):
    """Decision-process data used by the authorised results page and recommenders."""

    process: DecisionProcess
    team: DecisionTeam
    theme_visions: list[DecisionThemeVision]


class DecisionProcessListContext(t.TypedDict):
    """Batched lookups for rendering a list of processes without per-row queries.

    Keyed the way the caller already holds the data: a process knows its `team_gid`, a team
    knows its `location_gid`, and a process knows its `project_leader_gid`.
    """

    teams_by_gid: dict[str, DecisionTeam]
    school_gid_by_location_gid: dict[str, str]
    project_leaders_by_gid: dict[str, AuthUser]


class CriteriaContext(t.TypedDict):
    """Template context for the selection-criteria step of the wizard.

    `widgets` holds *rendered* multi-selects, one per criteria field, which is why the values
    are `Any`: they are py4web helper trees, not data. `process/criteria.html` indexes all three
    keys unconditionally, so all three must be present.
    """

    dm_process: DecisionProcess
    widgets: dict[CriteriaField, HTMLElement]
    readonly: bool


class ProsAndCons(t.TypedDict):
    """One process' assessments split by type, each list still in sort order.

    Both sides are always present, so callers and templates can index without guarding for an
    empty half.
    """

    pro: list[DecisionProsAndCons]
    con: list[DecisionProsAndCons]


class ProsAndConsByMaterialSelection(t.TypedDict):
    """One user's assessments, split by type and material selection."""

    pro: dict[str | None, list[DecisionProsAndCons]]
    con: dict[str | None, list[DecisionProsAndCons]]


__all__ = [
    "CriteriaContext",
    "CriteriaField",
    "DecisionProcessContext",
    "DecisionProcessListContext",
    "DecisionTeamContext",
    "ProcessGuidanceLevel",
    "ProsAndCons",
    "ProsAndConsByMaterialSelection",
    "ProsAndConsType",
    "VisionContext",
]
