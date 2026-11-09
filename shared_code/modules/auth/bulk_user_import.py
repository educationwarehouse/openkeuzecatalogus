"""Location-scoped bulk user import support."""

import csv
import dataclasses as dc
import io
import typing as t

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from shared_code.data_model import DecisionTeam
from shared_code.modules.decision_processes import DecisionProcessBackend

from .module import AuthSupportBackend, InviteCandidate

CsvHeader = t.Literal["voornaam", "achternaam", "emailadres", "vakgroepen"]
CSV_HEADERS = t.get_args(CsvHeader)


class BulkUserImportError(t.TypedDict):
    """One validation error associated with a CSV row."""

    row_number: int | None
    message: str


class BulkUserCsvRow(BaseModel):
    """The public CSV contract, before location-specific resolution."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str = Field(validation_alias="voornaam", min_length=1)
    last_name: str = Field(validation_alias="achternaam", min_length=1)
    email: str = Field(validation_alias="emailadres", min_length=1)
    team_names: tuple[str, ...] = Field(validation_alias="vakgroepen")

    @field_validator("team_names", mode="before")
    @classmethod
    def split_team_names(cls, value: object) -> tuple[str, ...]:
        """Split semicolon-separated team names and reject missing values."""
        if not isinstance(value, str):
            raise ValueError("minstens één vakgroep is verplicht")
        names = tuple(name.strip() for name in value.split(";") if name.strip())
        if not names:
            raise ValueError("minstens één vakgroep is verplicht")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("elke vakgroep mag maar één keer voorkomen")
        return names


@dc.dataclass(frozen=True)
class BulkUserImportRow:
    """One validated CSV row ready to be applied."""

    row_number: int
    first_name: str
    last_name: str
    email: str
    team_names: tuple[str, ...]
    existing_candidate: InviteCandidate | None


@dc.dataclass(frozen=True)
class BulkUserImportPlan:
    """Validated import rows with no database changes applied yet."""

    rows: tuple[BulkUserImportRow, ...]
    location_gid: str
    missing_team_names: tuple[str, ...]


@dc.dataclass(frozen=True)
class BulkUserImportResult:
    """Summary of a successfully applied bulk import."""

    created_users: int
    updated_users: int
    granted_memberships: int
    invited_users: int
    failed_invitations: int


def _pydantic_errors(exc: ValidationError, row_number: int) -> list[BulkUserImportError]:
    labels = {
        "voornaam": "voornaam",
        "achternaam": "achternaam",
        "emailadres": "e-mailadres",
        "vakgroepen": "vakgroepen",
    }
    return [
        {
            "row_number": row_number,
            "message": f"{labels.get(str(error['loc'][0]), str(error['loc'][0]))}: {error['msg']}",
        }
        for error in exc.errors()
    ]


def _validate_row(
    raw_row: dict[str | None, str | None],
    row_number: int,
    teams_by_name: dict[str, DecisionTeam],
    seen_emails: set[str],
    auth_support: AuthSupportBackend,
    create_missing_teams: bool = False,
) -> tuple[BulkUserImportRow | None, list[BulkUserImportError]]:
    """Validate one CSV record and resolve its current memberships."""
    try:
        csv_row = BulkUserCsvRow.model_validate(raw_row)
    except ValidationError as exc:
        return None, _pydantic_errors(exc, row_number)

    email, email_error = auth_support.normalize_invite_email(csv_row.email)
    if email_error or not email:
        return None, [{"row_number": row_number, "message": email_error or "e-mailadres ontbreekt"}]
    if email in seen_emails:
        return None, [{"row_number": row_number, "message": "e-mailadres komt meerdere keren in het bestand voor"}]
    seen_emails.add(email)

    team_names_by_key = {name.casefold(): name for name in csv_row.team_names}
    missing_names = [name for key, name in team_names_by_key.items() if key not in teams_by_name]
    if missing_names and not create_missing_teams:
        return None, [
            {
                "row_number": row_number,
                "message": f"onbekende vakgroep(en) binnen deze vestiging: {', '.join(missing_names)}",
            }
        ]
    teams = tuple(teams_by_name[key] for key in team_names_by_key if key in teams_by_name)
    lookup = auth_support.lookup_invite_candidate(email, teams[0].gid if teams else None)
    if lookup["similar_match"]:
        return None, [
            {
                "row_number": row_number,
                "message": "e-mailadres lijkt op een bestaand account en kan niet veilig worden gekoppeld",
            }
        ]
    candidate = lookup["exact_match"]
    already_has_all_teams = (
        not missing_names
        and candidate
        and all(auth_support.has_direct_membership(candidate["subject_id"], team.gid) for team in teams)
    )
    if already_has_all_teams:
        return None, [{"row_number": row_number, "message": "gebruiker heeft al toegang tot alle opgegeven vakgroepen"}]
    return (
        BulkUserImportRow(
            row_number=row_number,
            first_name=csv_row.first_name,
            last_name=csv_row.last_name,
            email=email,
            team_names=csv_row.team_names,
            existing_candidate=candidate,
        ),
        [],
    )


def _missing_team_names(rows: list[BulkUserImportRow], teams_by_name: dict[str, DecisionTeam]) -> tuple[str, ...]:
    """Collect new team names in first-seen order with case-insensitive deduplication."""
    missing: dict[str, str] = {}
    for row in rows:
        for team_name in row.team_names:
            team_key = team_name.casefold()
            if team_key not in teams_by_name:
                missing.setdefault(team_key, team_name)
    return tuple(missing.values())


def validate_bulk_user_import(
    content: bytes,
    location_gid: str,
    auth_support: AuthSupportBackend,
    create_missing_teams: bool = False,
) -> tuple[BulkUserImportPlan | None, list[BulkUserImportError]]:
    """Parse and validate a complete CSV upload before any rows are changed."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, [{"row_number": None, "message": "Gebruik een CSV-bestand met UTF-8-codering."}]

    reader = csv.DictReader(io.StringIO(text))
    headers = tuple(reader.fieldnames or ())
    if headers != CSV_HEADERS:
        return None, [
            {
                "row_number": None,
                "message": "Gebruik de kolommen: voornaam, achternaam, emailadres en vakgroepen.",
            }
        ]

    teams_by_name = {
        str(team.name or "").strip().casefold(): team
        for team in DecisionTeam.where(DecisionTeam.location_gid == location_gid).collect()
    }
    errors: list[BulkUserImportError] = []
    rows: list[BulkUserImportRow] = []
    seen_emails: set[str] = set()
    for row_number, raw_row in enumerate(reader, start=2):
        if any(raw_row.values()):
            row, row_errors = _validate_row(
                raw_row,
                row_number,
                teams_by_name,
                seen_emails,
                auth_support,
                create_missing_teams=create_missing_teams,
            )
            errors.extend(row_errors)
            if row:
                rows.append(row)

    if not rows and not errors:
        errors.append({"row_number": None, "message": "Het bestand bevat geen gebruikers."})
    return (
        (
            BulkUserImportPlan(tuple(rows), location_gid, _missing_team_names(rows, teams_by_name)),
            errors,
        )
        if not errors
        else (None, errors)
    )


def apply_bulk_user_import(
    plan: BulkUserImportPlan,
    *,
    auth_support: AuthSupportBackend,
    send_invitations: bool,
    login_url: str,
    decision_processes: DecisionProcessBackend,
) -> BulkUserImportResult:
    """Apply a validated import atomically and send requested invites afterwards."""
    created_users = 0
    updated_users = 0
    granted_memberships = 0
    invite_rows: list[tuple[BulkUserImportRow, tuple[DecisionTeam, ...]]] = []
    failed_invitations = 0
    teams_by_name = _resolve_import_teams(plan, decision_processes)

    for row in plan.rows:
        teams = tuple(teams_by_name[team_name.casefold()] for team_name in row.team_names)
        candidate = row.existing_candidate
        if candidate:
            subject_id = candidate["subject_id"]
            updated_users += 1
        else:
            candidate = auth_support.create_invited_identity(row.email, row.first_name, row.last_name)
            subject_id = candidate["subject_id"]
            created_users += 1
            invite_rows.append((row, teams))

        for team in teams:
            if not auth_support.has_direct_membership(subject_id, team.gid):
                auth_support.grant_invited_membership(subject_id, team.gid)
                granted_memberships += 1

    if send_invitations:
        for row, teams in invite_rows:
            team_labels = ", ".join(str(team.name) for team in teams)
            try:
                auth_support.send_membership_invite_email(
                    email=row.email,
                    membership_label=f"de vakgroepen {team_labels}",
                    invite_url=login_url,
                    first_name=row.first_name,
                )
            except Exception:
                failed_invitations += 1

    return BulkUserImportResult(
        created_users=created_users,
        updated_users=updated_users,
        granted_memberships=granted_memberships,
        invited_users=len(invite_rows) if send_invitations else 0,
        failed_invitations=failed_invitations,
    )


def _resolve_import_teams(
    plan: BulkUserImportPlan,
    decision_processes: DecisionProcessBackend,
) -> dict[str, DecisionTeam]:
    """Resolve existing teams and create the opted-in missing teams."""
    teams_by_name = {
        str(team.name or "").strip().casefold(): team
        for team in DecisionTeam.where(DecisionTeam.location_gid == plan.location_gid).collect()
    }
    for team_name in plan.missing_team_names:
        teams_by_name[team_name.casefold()] = decision_processes.create_team(plan.location_gid, team_name)
    return teams_by_name


__all__ = [
    "CSV_HEADERS",
    "BulkUserCsvRow",
    "BulkUserImportError",
    "BulkUserImportPlan",
    "BulkUserImportResult",
    "BulkUserImportRow",
    "CsvHeader",
    "apply_bulk_user_import",
    "validate_bulk_user_import",
]
