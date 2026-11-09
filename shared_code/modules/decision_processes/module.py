"""Guided learning-material decision-process flows."""

import datetime as dt
import typing as t

from endow import Domain

from shared_code.data_model import (
    AuthUser,
    DecisionMaterialSelection,
    DecisionProcess,
    DecisionProcessNote,
    DecisionProcessNoteEd,
    DecisionProsAndCons,
    DecisionTeam,
    DecisionTeamEd,
    DecisionThemeVision,
    LearningMaterial,
    Method,
    Organisation,
    OrganisationType,
    Product,
    Tagged,
)
from shared_code.data_model.constants import (
    AI_QUERY_LIMIT,
    PROCESS_STAGES,
    MaterialType,
    Predicate,
    get_themes,
)
from shared_code.infra.database import advisory_semaphore_context
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth.user_memberships import recursive_member_gids
from shared_code.modules.decision_processes.policy import DecisionProcessPolicy
from shared_code.modules.organisations import OrganisationBackend
from shared_code.modules.products import ProductBackend
from shared_code.services import Applogger, DeferredWork, LLMService
from shared_code.services.deferred import DeferredJob
from shared_code.services.llm import LLMUnavailableError
from shared_code.services.llm.limits import validate_user_input
from shared_code.util.lists import uniq
from shared_code.util.olid import is_valid_olid
from shared_code.util.types import MultiValue

from .ai import build_vision_enhancement_request
from .types import (
    DecisionProcessContext,
    DecisionProcessListContext,
    DecisionTeamContext,
    ProcessGuidanceLevel,
    ProsAndCons,
    ProsAndConsByMaterialSelection,
    ProsAndConsType,
    VisionContext,
)

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext
    from shared_code.modules.auth import AuthContext


class DecisionProcessBackend(Domain, TypeDALPolicyMixin[DecisionProcess]):
    """Create and manage decision processes through organisation permissions."""

    db: DatabaseContext
    auth: AuthContext
    applog: Applogger
    deferred: DeferredWork
    llm: LLMService
    organisations: OrganisationBackend
    products: ProductBackend
    policy: DecisionProcessPolicy

    def _log_process_event(
        self, action: str, process: DecisionProcess, details: dict[str, t.Any] | None = None
    ) -> None:
        """Record an audit event for a significant decision-process change."""
        self.applog.try_fire(
            {
                "kind": "event",
                "action": action,
                "user_gid": self.auth.id,
                "related": process.gid,
                "details": {
                    "process_gid": process.gid,
                    "team_gid": process.team_gid,
                    "process_stage": process.process_stage,
                }
                | (details or {}),
            },
        )

    def list_visible_processes(
        self,
        include_archived: bool = False,
        process_gids: MultiValue[str] | None = None,
    ) -> list[DecisionProcess]:
        """Return policy-authorised processes, optionally filtered by identifiers."""
        query = self.request_read()
        if not include_archived:
            query = query.where(active=True)
        if process_gids:
            query = query.where(DecisionProcess.gid.belongs(process_gids))

        return list(query.orderby(~DecisionProcess.updated_at))

    def count_visible_archived_processes(self) -> int:
        """Count archived processes within the policy-authorised read scope."""
        return self.request_read().where(active=False).count()

    def writable_process_gids(self, process_gids: set[str]) -> set[str]:
        """Return writable process identifiers from the supplied visible processes."""
        if not process_gids:
            return set()

        return set(self.request_update().where(DecisionProcess.gid.belongs(process_gids)).column(DecisionProcess.gid))

    def list_context(self, processes: t.Sequence[DecisionProcess]) -> DecisionProcessListContext:
        """Batch the team, school, and project-leader lookups a process list needs.

        Three queries regardless of row count. Not expressible as `.join()`: `DecisionProcess`
        has no `school` or `project_leader` relationship, the school is reached through a
        `Tagged` edge on the team's vestiging, and the leader is a bare gid.
        """
        teams_by_gid = {
            team.gid: team
            for team in DecisionTeam.where(
                DecisionTeam.gid.belongs({process.team_gid for process in processes}),
            )
        }
        school_gid_by_location_gid = {
            relation.object_gid: relation.subject_gid
            for relation in Tagged.where(
                (Tagged.predicate == Predicate.IS_SCHOOL_OF)
                & Tagged.object_gid.belongs({team.location_gid for team in teams_by_gid.values()}),
            )
        }
        project_leaders_by_gid = {
            leader.gid: leader
            for leader in AuthUser.where(
                AuthUser.gid.belongs(
                    {process.project_leader_gid for process in processes if process.project_leader_gid}
                ),
            )
        }
        return DecisionProcessListContext(
            teams_by_gid=teams_by_gid,
            school_gid_by_location_gid=school_gid_by_location_gid,
            project_leaders_by_gid=project_leaders_by_gid,
        )

    def create_team(
        self,
        location_gid: str,
        name: str,
        courses: list[str] | None = None,
        levels: list[str] | None = None,
        years: list[str] | None = None,
    ) -> DecisionTeam:
        """Create a team below an existing location."""
        location = Organisation.where(
            (Organisation.gid == location_gid) & (Organisation.organisation_type == OrganisationType.LOCATION)
        ).first()
        if not location:
            raise ValueError("Vestiging niet gevonden.")
        if not self.policy.can_manage_location(location_gid):
            raise PermissionError("Je mag geen vakgroep aan deze vestiging toevoegen.")

        team_ed = DecisionTeamEd.insert(
            location_gid=location_gid,
            name=name,
            courses=courses or [],
            levels=levels or [],
            years=years or [],
            last_saved_by=self.auth.get_email() or "internal/create_team",
        )
        team = DecisionTeam.where(DecisionTeam.gid == team_ed.gid).first_or_fail(
            ValueError("Vakgroep niet gevonden na aanmaken."),
        )

        self.register_team(team)
        return team

    def register_team(self, team: DecisionTeam) -> None:
        """Give an already-inserted team its RBAC group and permissions.

        Split out of `create_team` so a caller that inserts the row itself -- an admin grid with
        `create=True`, for instance -- can still wire up the group. Without this a team exists in
        the table but nobody can reach it, because every read and write resolves through the
        `{gid}@team` group.
        """
        rbac = self.auth.raw_rbac
        team_ctx = self.get_team_context(team.gid)

        rbac.add_group(f"{team.gid}@team", team.name, [], gid=team.gid, allow_existing=True)
        rbac.add_permission(team.gid, team.gid, "*")
        rbac.add_permission(team.gid, team_ctx["school"].gid, "read")

    def create_process(self, team_gid: str, schoolyear: str) -> DecisionProcess:
        """Start a process for a team whose workflow the actor may manage."""
        team = DecisionTeam.where(DecisionTeam.gid == team_gid).first()
        if not team:
            raise ValueError("Vakgroep niet gevonden.")
        if not self.policy.can_manage_team(team.gid):
            raise PermissionError("Je mag geen keuzeproces voor deze vakgroep starten.")

        process = DecisionProcess.insert(
            team_gid=team.gid,
            schoolyear=schoolyear,
            start_date=dt.date.today(),
            courses=team.courses or [],
            levels=team.levels or [],
            years=team.years or [],
            # only when the creator is actually in the team: write on the vestiging is enough to
            # get here, and a leader outside the team is one the fase-1 dropdown can neither show
            # nor replace. The old app left this unset too and let fase 1 pick a leader, which is
            # what the keuzecanvas empty-state copy promises.
            project_leader_gid=self.auth.id if self.may_lead_process(team.gid, self.auth.id) else None,
        )
        self.grant_process_permissions(process, team)
        self.db.commit()

        self._log_process_event("decision_process_created", process)
        return process

    def grant_process_permissions(self, process: DecisionProcess, team: DecisionTeam) -> None:
        """Register a process as an RBAC object below its team.

        Every wizard route guards on `auth.requires_permission(...)` against the *process*
        gid, and `edwh_auth_rbac.has_permission` resolves the target through
        `recursive_memberships`: so a gid that is not an identity can never carry a
        permission, no matter which rows exist. The process inherits the team's permission
        through group membership, while board and school access is granted explicitly.
        """
        rbac = self.auth.raw_rbac
        rbac.add_group(
            f"{process.gid}@process",
            f"{team.name} {process.schoolyear}",
            [team.gid],
            gid=process.gid,
            allow_existing=True,
        )
        context = self.get_team_context(team.gid)
        rbac.add_permission(context["board"].gid, process.gid, "read")
        rbac.add_permission(context["school"].gid, process.gid, "read")
        rbac.add_permissions(team.gid, process.gid, "*")

    def get_process(self, process_gid: str, writable: bool = False) -> DecisionProcess:
        """Load one process from the appropriate policy-authorised query."""
        query = self.request_update() if writable else self.request_read()
        return query.where(DecisionProcess.gid == process_gid).first_or_fail(ValueError("Keuzeproces niet gevonden."))

    def get_vision_context(self, process_gid: str) -> VisionContext:
        """Load an authorised process with its team and ordered theme visions."""
        process = (
            self.request_read()
            .where(DecisionProcess.gid == process_gid)
            .join("team", "theme_visions")
            .orderby("sort_order")  # note: DecisionProcess.sort_order breaks due to missing alias
            .first_or_fail(ValueError("Keuzeproces niet gevonden."))
        )
        team = t.cast(DecisionTeam, process.team)
        theme_visions = process.theme_visions
        return VisionContext(process=process, team=team, theme_visions=theme_visions)

    def team_processes(self, team_gid: str) -> list[DecisionProcess]:
        """Return the policy-visible processes for one teaching team."""
        return list(
            self.request_read().where(DecisionProcess.team_gid == team_gid).orderby(~DecisionProcess.updated_at)
        )

    def pros_and_cons(self, process_gid: str, item_type: ProsAndConsType | None = None) -> list[DecisionProsAndCons]:
        """Return the assessments belonging to one authorised decision process."""
        process = self.get_process(process_gid)

        builder = (
            DecisionProsAndCons.join("user", "material_selection")
            .where(DecisionProsAndCons.process_gid == process.gid)
            .orderby(DecisionProsAndCons.sort_order)
        )

        if item_type is not None:
            builder = builder.where(item_type=item_type)

        return list(builder)

    def pros_and_cons_by_type(self, process_gid: str) -> ProsAndCons:
        """Return one authorised process' assessments split by type, each still in sort order."""
        return ProsAndCons(
            pro=self.pros_and_cons(process_gid, item_type="pro"),
            con=self.pros_and_cons(process_gid, item_type="con"),
        )

    def pros_and_cons_by_material_selection(
        self,
        process_gid: str,
        material_selection_gids: MultiValue[str],
        user_gid: str | None = None,
    ) -> ProsAndConsByMaterialSelection:
        """Return one user's ordered assessments grouped by material selection and type."""
        process = self.get_process(process_gid)
        common_query = (
            DecisionProsAndCons.where(
                process_gid=process.gid,
            )
            .where(DecisionProsAndCons.material_selection_gid.belongs(material_selection_gids))
            .orderby(DecisionProsAndCons.sort_order)
        )

        if user_gid is not None:
            common_query = common_query.where(user_gid=user_gid)

        return ProsAndConsByMaterialSelection(
            pro=common_query.where(item_type="pro").collect().group_by_value("material_selection_gid"),
            con=common_query.where(item_type="con").collect().group_by_value("material_selection_gid"),
        )

    def material_selections(self, process_gid: str) -> list[DecisionMaterialSelection]:
        """Return the material selections for one authorised decision process."""
        process = self.get_process(process_gid)
        return list(
            DecisionMaterialSelection.where(DecisionMaterialSelection.process_gid == process.gid).orderby(
                DecisionMaterialSelection.name,
            )
        )

    def learning_materials_by_olid(self, olids: t.Collection[str]) -> dict[str, LearningMaterial]:
        """Return catalog presentation data for selected learning materials."""
        if not olids:
            return {}

        materials = (
            LearningMaterial.where(LearningMaterial.olid.belongs(olids))
            .join("product", "method")
            .select(
                LearningMaterial.name,
                LearningMaterial.olid,
                LearningMaterial.origin,
                Product.image_url,
                Product.description,
                Product.levels,
                Product.subjects,
                Method.image_url,
                Method.description,
                Method.levels,
                Method.subjects,
            )
            .collect()
        )
        return {material.olid: material for material in materials}

    def search_learning_materials(
        self,
        search: str,
        excluded_olids: MultiValue[str],
    ) -> list[LearningMaterial]:
        """Search the product-and-method catalog relation used by material selection."""
        threshold = 0.22 if len(search) < 4 else 0.16 if len(search) < 7 else 0.1
        self.db.executesql(f"SET pg_trgm.similarity_threshold = {threshold};")
        score = self.db.sql_expression(
            """
            similarity(learning_material.name, %(term)s) +
            CASE WHEN learning_material.olid ILIKE %(like_term)s THEN 0.5 ELSE 0 END +
            CASE
                WHEN learning_material.origin = 'method'
                    AND lower(learning_material.name) LIKE %(prefix_term)s THEN 0.95
                WHEN learning_material.origin = 'method'
                    AND lower(learning_material.name) LIKE %(word_term)s THEN 0.55
                WHEN learning_material.origin = 'method'
                    AND similarity(learning_material.name, %(term)s) >= 0.35 THEN 0.2
                ELSE 0
            END
            """,
            term=search,
            like_term=f"%{search}%",
            prefix_term=f"{search.lower()}%",
            word_term=f"% {search.lower()}%",
        )
        origin_order = self.db.sql_expression(
            "CASE WHEN learning_material.origin = 'method' THEN 0 ELSE 1 END",
        )
        query = LearningMaterial.where(
            LearningMaterial.olid.contains(search)
            | self.db.sql_expression("learning_material.name %% %(search)s", search=search),
        ).orderby(~score, origin_order)
        if excluded_olids:
            query = query.where(~LearningMaterial.olid.belongs(excluded_olids))
        return list(
            query.join("product", "method")
            .select(
                LearningMaterial.name,
                LearningMaterial.olid,
                LearningMaterial.origin,
                Product.image_url,
                Method.image_url,
            )
            .paginate(limit=5),
        )

    def change_material_selection(
        self,
        process_gid: str,
        action: t.Literal["add", "remove"],
        material_type: MaterialType,
        name: str,
        olid: str,
    ) -> None:
        """Add or remove one material selection from an authorised process."""
        if not is_valid_olid(olid):
            raise ValueError("Ongeldige OLID.")

        validate_user_input(name)

        process = self.get_process(process_gid, writable=True)
        query = DecisionMaterialSelection.where(
            (DecisionMaterialSelection.process_gid == process.gid) & (DecisionMaterialSelection.olid == olid),
        )
        if action == "add":
            selection = query.first()
            if selection:
                selection.update_record(name=name, material_type=material_type)
            else:
                DecisionMaterialSelection.insert(
                    process_gid=process.gid,
                    name=name,
                    olid=olid,
                    material_type=material_type,
                )
        else:
            query.delete()
        self.db.commit()

        self._log_process_event("decision_process_material_changed", process, details={"olid": olid, "change": action})

    def ensure_theme_visions(self, process_gid: str) -> dict[str, DecisionThemeVision]:
        """Return every theme vision, creating missing rows for an authorised process."""
        process = self.get_process(process_gid)
        theme_visions = {
            vision.theme: vision for vision in DecisionThemeVision.where(DecisionThemeVision.process_gid == process.gid)
        }
        for sort_order, theme in enumerate(get_themes()):
            if theme not in theme_visions:
                theme_visions[theme] = DecisionThemeVision.insert(
                    process_gid=process.gid,
                    theme=theme,
                    summary="",
                    sort_order=sort_order,
                )
        self.db.commit()
        return theme_visions

    def enhance_vision(self, process_gid: str, theme: str, current_summary: str) -> DeferredJob:
        """Queue a provider-neutral enhancement request for one authorised theme."""
        if not self.llm.available:
            raise LLMUnavailableError("AI-ondersteuning is niet beschikbaar.")

        themes = get_themes()
        if theme not in themes:
            raise ValueError("Onbekend visiethema.")

        context = self.get_process_context(process_gid, writable=True)
        request = build_vision_enhancement_request(
            context,
            theme=theme,
            theme_label=themes[theme],
            current_summary=current_summary,
        )

        # count attempts, not successes - matching the previous implementation
        process = context["process"]
        current_ai_usage = process.ai_usage or 0
        if current_ai_usage >= AI_QUERY_LIMIT:
            raise LLMUnavailableError(
                "AI-limiet bereikt voor dit keuzeproces. Neem contact op voor hulp of ga verder zonder AI.",
            )
        else:
            process.update_record(ai_usage=current_ai_usage + 1)
            self.db.commit()

        return self.deferred.enqueue("enhance_vision", dict(request))

    def theme_visions(self, process_gid: str) -> list[DecisionThemeVision]:
        """Return the theme visions for one authorised decision process in display order."""
        process = self.get_process(process_gid)
        return list(
            DecisionThemeVision.where(DecisionThemeVision.process_gid == process.gid).orderby(
                DecisionThemeVision.sort_order,
            )
        )

    def reopen_process(self, process_gid: str) -> DecisionProcess:
        """Return one authorised archived process to the team stage."""
        process = self.get_process(process_gid, writable=True)
        if not self._may_manage_process(process):
            self._log_process_event("decision_process_reopen_denied", process)
            raise ValueError("Alleen de projectleider of een beheerder kan dit keuzeproces heropenen.")
        process.update_record(process_stage="team", active=True)
        self.db.commit()

        self._log_process_event("decision_process_reopened", process)
        return process

    def update_pros_cons_content(self, process_gid: str, item_gid: str, content: str) -> None:
        """Update one authorised pros-or-cons entry's content."""
        validate_user_input(content)

        try:
            with advisory_semaphore_context(
                self.db,
                semaphore=process_gid,
                semaphore_namespace="decision_process.pros_cons",
                transaction_lock=True,
            ):
                process = self._editable_point_process(process_gid)
                item = DecisionProsAndCons.where(
                    (DecisionProsAndCons.gid == item_gid) & (DecisionProsAndCons.process_gid == process.gid),
                ).first_or_fail(ValueError("Plus- of minpunt niet gevonden."))
                if not self.auth.id or self.auth.id not in {item.user_gid, process.project_leader_gid}:
                    raise PermissionError("Je mag alleen eigen punten of punten als projectleider bewerken.")
                item.update_record(content=content)
                self.db.commit()

                self._log_process_event("decision_process_point_updated", process, details={"item_gid": item_gid})
        except Exception:
            self.db.rollback()
            raise

    def save_pros_cons(
        self,
        process_gid: str,
        material_selection_gid: str,
        *,
        pros: dict[str, list[str]],
        cons: dict[str, list[str]],
    ) -> None:
        """Replace the current actor's assessments for one material selection."""
        for contents in (*pros.values(), *cons.values()):
            for content in contents:
                validate_user_input(content)

        process = self.get_process(process_gid, writable=True)
        selection = DecisionMaterialSelection.where(
            (DecisionMaterialSelection.gid == material_selection_gid)
            & (DecisionMaterialSelection.process_gid == process.gid),
        ).first_or_fail(ValueError("Leermiddel niet gevonden."))
        actor_gid = self.auth.id
        if not actor_gid:
            raise PermissionError("Inloggen is vereist.")

        self._save_assessment_type(process, selection, actor_gid, "pro", pros)
        self._save_assessment_type(process, selection, actor_gid, "con", cons)
        self.db.commit()

        self._log_process_event("decision_process_assessments_saved", process, details={"selection_gid": selection.gid})

    def _save_assessment_type(
        self,
        process: DecisionProcess,
        selection: DecisionMaterialSelection,
        actor_gid: str,
        item_type: ProsAndConsType,
        values: dict[str, list[str]],
    ) -> None:
        """Synchronise one assessment type for a process material and actor."""
        current = list(
            DecisionProsAndCons.where(
                (DecisionProsAndCons.process_gid == process.gid)
                & (DecisionProsAndCons.material_selection_gid == selection.gid)
                & (DecisionProsAndCons.user_gid == actor_gid)
                & (DecisionProsAndCons.item_type == item_type),
            ),
        )
        current_by_gid = {item.gid: item for item in current}
        for item in current:
            if item.gid not in values:
                item.delete_record()

        for sort_order, (item_gid, contents) in enumerate(values.items()):
            for content in contents:
                if not content:
                    continue
                if item := current_by_gid.get(item_gid):
                    item.update_record(content=content, sort_order=sort_order)
                else:
                    DecisionProsAndCons.insert(
                        process_gid=process.gid,
                        user_gid=actor_gid,
                        material_selection_gid=selection.gid,
                        item_type=item_type,
                        content=content,
                        sort_order=sort_order,
                    )

    def _editable_point_process(self, process_gid: str) -> DecisionProcess:
        """Require write access and an active, unfinished process for point actions."""
        process = self.get_process(process_gid, writable=True)
        if not process.active or process.process_stage == "done":
            raise PermissionError("Heropen het keuzeproces voordat je kaartjes wijzigt.")
        return process

    def clone_pros_cons(self, process_gid: str, item_gid: str, sort_order: int | None = None) -> DecisionProsAndCons:
        """Clone an assessment within an authorised decision process."""
        process = self._editable_point_process(process_gid)
        original = DecisionProsAndCons.where(
            (DecisionProsAndCons.gid == item_gid) & (DecisionProsAndCons.process_gid == process.gid),
        ).first_or_fail(ValueError("Plus- of minpunt niet gevonden."))
        if not self.auth.id or self.auth.id not in {original.user_gid, process.project_leader_gid}:
            raise PermissionError("Je mag alleen eigen punten of punten als projectleider dupliceren.")
        if sort_order is None:
            points = DecisionProsAndCons.where(process_gid=process.gid, theme=original.theme)
            sort_order = max((point.sort_order for point in points), default=-1) + 1
        try:
            inserted = DecisionProsAndCons.insert(
                process_gid=process.gid,
                user_gid=original.user_gid,
                material_selection_gid=original.material_selection_gid,
                item_type=original.item_type,
                theme=original.theme,
                content=original.content,
                sort_order=sort_order,
            )
            self.db.commit()

            self._log_process_event("decision_process_point_cloned", process, details={"item_gid": inserted.gid})
            return (
                DecisionProsAndCons.join("user", "material_selection")
                .where(DecisionProsAndCons.gid == inserted.gid)
                .first_or_fail(ValueError("De kopie kon niet worden geladen."))
            )
        except Exception:
            self.db.rollback()
            raise

    def delete_pros_cons(self, process_gid: str, item_gid: str) -> None:
        """Delete one duplicate while preserving at least one identical point."""
        try:
            with advisory_semaphore_context(
                self.db,
                semaphore=process_gid,
                semaphore_namespace="decision_process.pros_cons",
                transaction_lock=True,
            ):
                process = self._editable_point_process(process_gid)
                point = DecisionProsAndCons.where(
                    (DecisionProsAndCons.gid == item_gid) & (DecisionProsAndCons.process_gid == process.gid),
                ).first_or_fail(ValueError("Plus- of minpunt niet gevonden."))
                if not self.auth.id or self.auth.id not in {point.user_gid, process.project_leader_gid}:
                    raise PermissionError("Je mag alleen eigen punten of punten als projectleider verwijderen.")
                matching_points = DecisionProsAndCons.where(
                    process_gid=process.gid,
                    material_selection_gid=point.material_selection_gid,
                    user_gid=point.user_gid,
                    item_type=point.item_type,
                    content=point.content,
                )
                if matching_points.count() <= 1:
                    raise ValueError(
                        "Dit is het laatste exemplaar van dit punt. Er moet minimaal één kaartje blijven. "
                        "Zet het eventueel terug bij de plus- of minpunten."
                    )
                point.delete_record()
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.applog.try_fire(
            {
                "kind": "event",
                "action": "decision_process_point_deleted",
                "user_gid": self.auth.id,
                "related": process.gid,
                "details": {"process_gid": process.gid, "item_gid": item_gid},
            },
        )

    def assign_point_themes(
        self,
        process_gid: str,
        item_gid: str,
        themes: list[str],
    ) -> list[DecisionProsAndCons]:
        """Place one assessment at selected themes, copying it for additional destinations."""
        process = self._editable_point_process(process_gid)
        original = DecisionProsAndCons.where(
            (DecisionProsAndCons.gid == item_gid) & (DecisionProsAndCons.process_gid == process.gid),
        ).first_or_fail(ValueError("Plus- of minpunt niet gevonden."))
        if not self.auth.id or self.auth.id not in {original.user_gid, process.project_leader_gid}:
            raise PermissionError("Je mag alleen eigen punten of punten als projectleider verplaatsen.")

        valid_themes = get_themes()
        if not all(isinstance(theme, str) and theme in valid_themes for theme in themes):
            raise ValueError("Onbekend thema.")
        destinations = uniq(themes)
        current_theme = original.theme or None
        primary_theme = current_theme if current_theme in destinations else (destinations[0] if destinations else None)

        next_orders: dict[str | None, int] = {}
        for point in DecisionProsAndCons.where(DecisionProsAndCons.process_gid == process.gid):
            theme = point.theme or None
            next_orders[theme] = max(next_orders.get(theme, 0), point.sort_order + 1)

        try:
            if primary_theme != current_theme:
                original.update_record(theme=primary_theme, sort_order=next_orders.get(primary_theme, 0))

            assigned_gids = [original.gid]
            for theme in destinations:
                if theme == primary_theme:
                    continue
                point = DecisionProsAndCons.insert(
                    process_gid=process.gid,
                    user_gid=original.user_gid,
                    material_selection_gid=original.material_selection_gid,
                    item_type=original.item_type,
                    theme=theme,
                    content=original.content,
                    sort_order=next_orders.get(theme, 0),
                )
                assigned_gids.append(point.gid)

            self.db.commit()

            self._log_process_event("decision_process_point_themes_changed", process, details={"item_gid": item_gid})
            assigned_points = (DecisionProsAndCons.process_gid == process.gid) & DecisionProsAndCons.gid.belongs(
                assigned_gids,
            )
            return list(
                DecisionProsAndCons.join("user", "material_selection")
                .where(assigned_points)
                .orderby(DecisionProsAndCons.sort_order)
            )
        except Exception:
            self.db.rollback()
            raise

    def assign_theme(
        self,
        process_gid: str,
        *,
        item_gids: list[str],
        theme: str | None,
        previous_theme: str | None,
        previous_item_type: ProsAndConsType | None,
    ) -> None:
        """Assign assessments to a theme and restore the previous container order."""
        process = self.get_process(process_gid, writable=True)
        items = DecisionProsAndCons.where(
            (DecisionProsAndCons.process_gid == process.gid) & DecisionProsAndCons.gid.belongs(item_gids),
        )
        for sort_order, item in enumerate(items):
            item.update_record(theme=theme, sort_order=sort_order)

        previous_items = DecisionProsAndCons.where(DecisionProsAndCons.process_gid == process.gid)
        if previous_item_type:
            previous_items = previous_items.where(
                (DecisionProsAndCons.item_type == previous_item_type)
                & ((DecisionProsAndCons.theme == None) | (DecisionProsAndCons.theme == "")),
            )
        elif previous_theme:
            previous_items = previous_items.where(DecisionProsAndCons.theme == previous_theme)
        else:
            raise ValueError("Onbekende bronkolom.")

        for sort_order, item in enumerate(previous_items.orderby(DecisionProsAndCons.sort_order)):
            item.update_record(sort_order=sort_order)
        self.db.commit()

        self._log_process_event("decision_process_themes_assigned", process, details={"item_gids": item_gids})

    def update_theme_summary(
        self,
        process_gid: str,
        vision_gid: str,
        theme: str,
        summary: str,
    ) -> None:
        """Update one theme summary belonging to an authorised process."""
        validate_user_input(summary)

        process = self.get_process(process_gid, writable=True)
        vision = DecisionThemeVision.where(
            (DecisionThemeVision.gid == vision_gid) & (DecisionThemeVision.process_gid == process.gid),
        ).first_or_fail(ValueError("Themasamenvatting niet gevonden."))
        vision.update_record(theme=theme, summary=summary)
        self.db.commit()

        self._log_process_event("decision_process_theme_summary_updated", process, details={"vision_gid": vision_gid})

    def update_priorities(self, process_gid: str, summaries: dict[str, list[str]]) -> None:
        """Store theme summaries and their priority order for an authorised process."""
        for values in summaries.values():
            for value in values:
                validate_user_input(value)

        process = self.get_process(process_gid, writable=True)
        visions = {
            vision.gid: vision
            for vision in DecisionThemeVision.where(
                (DecisionThemeVision.process_gid == process.gid) & DecisionThemeVision.gid.belongs(summaries),
            )
        }
        for sort_order, (vision_gid, values) in enumerate(summaries.items()):
            if not values:
                continue
            vision = visions.get(vision_gid)
            if not vision:
                raise ValueError("Themasamenvatting niet gevonden.")
            vision.update_record(summary=values[0], sort_order=sort_order)
        self.db.commit()

        self._log_process_event("decision_process_priorities_updated", process)

    def save_vision(self, process_gid: str) -> DecisionProcess:
        """Store the completed, priority-ordered vision as a process snapshot."""
        process = self.get_process(process_gid, writable=True)
        themes = get_themes()
        sections = [
            f"{vision.sort_order + 1}. {themes.get(vision.theme, vision.theme)}\n{vision.summary}"
            for vision in self.theme_visions(process_gid)
        ]
        process.update_record(vision="\n\n".join(sections))
        self.db.commit()

        self._log_process_event("decision_process_vision_saved", process)
        return process

    def may_lead_process(self, team_gid: str, user_gid: str | None) -> bool:
        """Return whether a user may be the project leader of a process below one team.

        Checked against the same `recursive_member_gids` set at the same depth that
        `members_and_pending` uses, because that is exactly what the fase-1 dropdown can display
        and offer. Anything outside it yields a process whose leader the UI cannot render or
        change. Note the team's location and school sit *above* the team in the RBAC graph, so
        holding write there does not make someone a team member.
        """
        if not user_gid:
            return False

        return user_gid in set(recursive_member_gids(team_gid, max_level=1))

    def update_project_leader(self, process_gid: str, project_leader_gid: str | None) -> None:
        """Set or clear the project leader for one authorised decision process."""
        process = self.get_process(process_gid, writable=True)
        if project_leader_gid and not self.may_lead_process(process.team_gid, project_leader_gid):
            raise ValueError("De projectleider moet lid zijn van de vakgroep.")

        process.update_record(project_leader_gid=project_leader_gid)
        self.db.commit()

        self._log_process_event(
            "decision_process_leader_updated", process, details={"project_leader_gid": project_leader_gid}
        )

    def update_criteria(
        self,
        process_gid: str,
        *,
        courses: list[str],
        levels: list[str],
        years: list[str],
    ) -> DecisionProcess:
        """Update the selection criteria for one authorised decision process."""
        process = self.get_process(process_gid, writable=True)
        process.update_record(courses=courses, levels=levels, years=years)
        self.db.commit()

        self._log_process_event("decision_process_criteria_updated", process)
        return process

    def get_team_context(self, team_gid: str) -> DecisionTeamContext:
        """Load a teaching team together with its school and board."""
        team = DecisionTeam.where(DecisionTeam.gid == team_gid).first_or_fail(
            ValueError("Vakgroep niet gevonden."),
        )
        school = self.organisations.school_for_location(team.location_gid)
        board = self.organisations.board_for_school(school.gid)
        return DecisionTeamContext(team=team, school=school, board=board)

    def get_process_context(self, process_gid: str, writable: bool = False) -> DecisionProcessContext:
        """Load an authorised process together with its team, school, and board."""
        process = self.get_process(process_gid, writable=writable)
        context = self.get_team_context(process.team_gid)
        return DecisionProcessContext(process=process, **context)

    def get_guidance_note(
        self,
        process_gid: str,
        level: ProcessGuidanceLevel,
        theme: str,
        writable: bool = False,
    ) -> DecisionProcessNote:
        """Load or create an organisation's guidance note, reached through a process.

        The note belongs to the organisation, not to the process: every process below the
        same board or school shares it.
        """
        if writable and not self.may_write_guidance(process_gid, level):
            raise PermissionError("Je mag deze begeleidingstekst niet bewerken.")
        context = self.get_process_context(process_gid)
        organisation = context[level]
        note = DecisionProcessNote.where(
            (DecisionProcessNote.organisation_gid == organisation.gid) & (DecisionProcessNote.theme == theme),
        ).first()
        if note:
            return note
        if not writable:
            raise ValueError("Notitie niet gevonden.")

        note_ed = DecisionProcessNoteEd.insert(
            organisation_gid=organisation.gid,
            theme=theme,
            last_saved_by=self.auth.get_email() or "internal/create_guidance_note",
        )
        return DecisionProcessNote.where(DecisionProcessNote.gid == note_ed.gid).first_or_fail(
            ValueError("Notitie niet gevonden na aanmaken."),
        )

    def visible_teams(self, privilege: str = "read") -> list[DecisionTeam]:
        """Return the teams the actor may reach with one privilege, directly or via their location.

        Only `gid` and `name` are loaded, enough for membership listings and dropdowns. Pass
        `"write"` where the actor is about to change something: a team they may only read must
        not turn up in, say, the "start een keuzeproces" dropdown.
        """
        return list(
            self.policy.team_query(privilege).select(
                DecisionTeam.gid,
                DecisionTeam.name,
                orderby=DecisionTeam.name,
            )
        )

    def _may_manage_process(self, process: DecisionProcess) -> bool:
        """Return whether the actor may archive or reopen a process."""
        actor_gid = self.auth.id
        return self.auth.is_admin() or bool(actor_gid and process.project_leader_gid == actor_gid)

    def may_edit_criteria(self, process_gid: str) -> bool:
        """Return whether the actor may change a process' selection criteria.

        Only the project leader, or an admin, as `process/criteria.html`'s lock icon states.
        Takes a gid rather than a record so the answer never depends on how the caller loaded
        the process, matching `may_write_guidance` and `update_criteria`.
        """
        process = self.get_process(process_gid)
        if self.auth.is_service():
            return True

        return self._may_manage_process(process)

    def may_write_guidance(self, process_gid: str, level: ProcessGuidanceLevel) -> bool:
        """Return whether the actor may edit the guidance texts a process shows at one level.

        Presentation only. Every route that asks this is already guarded by an RBAC permission
        check on the process gid, so the answer decides whether a form renders read-only, never
        whether the page is reachable. Editing additionally requires write access to the target
        organisation. An archived process is read-only for everyone.
        """
        context = self.get_process_context(process_gid)
        if not context["process"].active:
            return False
        if self.auth.is_admin() or self.auth.is_service():
            return True

        return self.auth.has_permission(context[level].gid, "write")

    def update_guidance_note(
        self,
        process_gid: str,
        level: ProcessGuidanceLevel,
        theme: str,
        content: str,
    ) -> DecisionProcessNote:
        """Update one organisation-level guidance note for an authorised actor."""
        validate_user_input(content)
        if not self.may_write_guidance(process_gid, level):
            raise PermissionError("Je mag deze begeleidingstekst niet bewerken.")

        note = self.get_guidance_note(process_gid, level, theme, writable=True)
        note.update_record(content=content)
        self.db.commit()

        self._log_process_event(
            "decision_process_guidance_updated", self.get_process(process_gid), details={"note_gid": note.gid}
        )
        return note

    def guidance_notes(
        self,
        process_gid: str,
        ensure_for_writers: bool = False,
    ) -> dict[str, dict[str, DecisionProcessNote]]:
        """Return the guidance notes of the board and school above one authorised process.

        With `ensure_for_writers`, missing notes are bulk-created for every theme a writer may
        edit, then all notes are reloaded in one query so callers always get row objects.
        """
        context = self.get_process_context(process_gid)
        by_organisation = {context["board"].gid: "board", context["school"].gid: "school"}
        notes = DecisionProcessNote.where(
            DecisionProcessNote.organisation_gid.belongs(list(by_organisation)),
        )
        result: dict[str, dict[str, DecisionProcessNote]] = {"board": {}, "school": {}}
        for note in notes:
            if level := by_organisation.get(note.organisation_gid):
                result[level][note.theme] = note

        if ensure_for_writers:
            missing: list[dict[str, str]] = []
            levels = (("board", context["board"]), ("school", context["school"]))
            for level, organisation in levels:
                if self.may_write_guidance(process_gid, level):
                    missing.extend(
                        {"organisation_gid": organisation.gid, "theme": theme}
                        for theme in get_themes()
                        if theme not in result[level]
                    )
            if missing:
                last_saved_by = self.auth.get_email() or "internal/create_guidance_notes"
                for values in missing:
                    values["last_saved_by"] = last_saved_by
                DecisionProcessNoteEd.bulk_insert(missing)
                self.db.commit()
                return self.guidance_notes(process_gid)
        return result

    def set_stage(self, process_gid: str, stage: str) -> DecisionProcess:
        """Advance or correct a process stage for an authorised actor."""
        if stage not in PROCESS_STAGES:
            raise ValueError("Onbekende procesfase.")
        process = self.get_process(process_gid, writable=True)
        process.update_record(process_stage=stage)
        self.db.commit()

        self._log_process_event("decision_process_stage_changed", process)
        return process

    def complete_process(self, process_gid: str) -> DecisionProcess:
        """Mark an authorised decision process as complete."""
        return self.set_stage(process_gid, "done")

    def archive_process(self, process_gid: str) -> None:
        """Archive a process without deleting its audit trail."""
        process = self.get_process(process_gid, writable=True)
        if not self._may_manage_process(process):
            raise ValueError("Alleen de projectleider of een beheerder kan dit keuzeproces archiveren.")
        process.update_record(active=False)
        self.db.commit()

        self._log_process_event("decision_process_archived", process)
