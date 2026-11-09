import os
import sys
import uuid
from urllib.parse import urlencode

from common.fixtures import FlagBasedCache
from common.fixtures.common import admin
from common.fixtures.content_editable import ContentEditableV2
from common.models import session
from common.settings import RESTART_FLAG

from py4web import HTTP, URL, action, redirect, request
from shared_code.data_model import (
    Identity,
    MethodEd,
    OrganisationEd,
    OrganisationType,
    Predicate,
    ProductEd,
    SupplierEd,
    TaggedEd,
)
from shared_code.infra.database.tables import rebuild_model
from shared_code.modules.decision_processes.helpers import calculate_next_schoolyear_label
from shared_code.util.olid import generate as generate_olid

from .. import settings
from ..models import backend, db


@action("api/content-editable/save", method="POST")
@admin()
def api_save() -> str:
    """Sla een contenteditable-sectie uit de UI op in de database.

    Toegang tot dit endpoint wordt beperkt door de admin-fixture.
    """
    form = {**request.forms}

    for identifier, content in form.items():
        ContentEditableV2.write_value(identifier, content)

    return session["path"]


if os.getenv("COVERAGE_PROCESS_START"):  # pragma: no cover

    @action("_flush-runtime-coverage")
    def flush_runtime_coverage() -> str:
        """Persist runtime coverage from the long-running web process."""
        import coverage

        cov = coverage.Coverage.current()

        assert cov, "no-coverage"

        cov.save()
        return "flushed"


if os.getenv("STATE_OF_DEVELOPMENT", "").upper() == "ONT":

    @action("5xx")
    def development_5xx() -> None:
        """Raise a 5xx response for development error-ticket checks."""
        raise RuntimeError("Development 5xx endpoint")


if settings.ENTREE_FAKE:

    @action("auth/entree_mock_authorize")
    def entree_mock_authorize() -> None:
        """Fake Entree authorize endpoint used in test mode."""
        callback_url = URL("auth/plugin/oauth2kennisnet/callback", scheme=True)
        params = {"code": "mock-entree-code"}
        if state := request.query.get("state"):
            params["state"] = state
        redirect(f"{callback_url}?{urlencode(params)}")


if MOCK_EMAIL_DOMAIN := os.environ.get("PYTEST_MOCK_EMAIL_DOMAIN", ""):

    @action("auth/cleanup_mock_users", method=["POST"])
    @action.uses(db)
    def cleanup_mock_users() -> str:
        """Delete mock auth users created by browser tests."""
        domain = (request.query.get("domain", "") or MOCK_EMAIL_DOMAIN).lstrip("@")
        email_like = f"%@{domain}"

        auth_users = db(db.auth_user.email.like(email_like)).select(db.auth_user.gid)
        gids = [row.gid for row in auth_users if row.gid]

        deleted_memberships = db(db.membership.subject.belongs(gids)).delete() if gids else 0
        deleted_auth_users = db(db.auth_user.email.like(email_like)).delete()
        deleted_identities = len(Identity.where(Identity.object_id.belongs(gids)).delete()) if gids else 0
        db.commit()

        return (
            "cleaned "
            f"{deleted_auth_users} auth users, "
            f"{deleted_identities} identities, "
            f"{deleted_memberships} memberships for {email_like}"
            f" ({gids = })"
        )


if os.environ.get("STATE_OF_DEVELOPMENT", "").upper() == "TEST":

    def _browser_test_location(name: str) -> str:
        """Create an independent organisation hierarchy for one browser fixture."""
        board = OrganisationEd.insert(name=f"{name} bestuur", organisation_type=OrganisationType.BOARD)
        school = OrganisationEd.insert(name=f"{name} school", organisation_type=OrganisationType.SCHOOL)
        location = OrganisationEd.insert(name=f"{name} vestiging", organisation_type=OrganisationType.LOCATION)
        TaggedEd.insert(subject_gid=board.gid, predicate=Predicate.IS_BOARD_OF, object_gid=school.gid)
        TaggedEd.insert(subject_gid=school.gid, predicate=Predicate.IS_SCHOOL_OF, object_gid=location.gid)
        rebuild_model(db, "organisation")
        rebuild_model(db, "tagged")

        return str(location.gid)

    def _browser_test_catalog(search_term: str, count: int) -> list[str]:
        """Insert catalog records for production search and detail rendering."""
        suffix = uuid.uuid4().hex
        supplier = SupplierEd.insert(name=search_term, olid=generate_olid("supplier", suffix))
        rebuild_model(db, "supplier")
        material_names = []
        for index in range(count):
            name = f"{search_term} {index:02}"
            image_url = "/private/static/images/logo-okl-on-dark.svg" if index == 0 else ""
            method = MethodEd.insert(
                name=name,
                olid=generate_olid("method", f"{suffix}-{index}"),
                supplier_gid=supplier.gid,
                description=f"Beschrijving {name}",
                image_url=image_url,
                available="leverbaar",
            )
            ProductEd.insert(
                name=name,
                olid=generate_olid("product", f"{suffix}-{index}"),
                supplier_gid=supplier.gid,
                method_gid=method.gid,
                description=f"Beschrijving {name}",
                image_url=image_url,
                available="leverbaar",
            )
            material_names.append(name)

        rebuild_model(db, "method")
        rebuild_model(db, "product")
        db.executesql("REFRESH MATERIALIZED VIEW learning_material;")

        return material_names

    @action("test_seed_browser_data", method="POST")
    @admin()
    def test_seed_browser_data() -> dict:
        """Prepare records consumed through real browser pages and widgets."""
        scenario = request.forms.get("scenario")
        if scenario not in {"process", "overview", "catalog", "material"}:
            raise HTTP(400, "Unknown browser scenario.")

        suffix = uuid.uuid4().hex
        search_term = f"Browser{suffix}"
        process_gids = []
        team_name = ""
        material_names = []

        if scenario != "catalog":
            location_gid = _browser_test_location(search_term)
            team = backend.decision_processes.create_team(location_gid, search_term)
            actor_gid = backend.auth_context.id
            assert actor_gid, "The admin fixture requires an authenticated user."
            backend.auth_context.add_membership(actor_gid, team.gid)
            count = 12 if scenario == "overview" else 2
            processes = [
                backend.decision_processes.create_process(team.gid, f"{2020 + i}-{2021 + i}") for i in range(count)
            ]
            backend.decision_processes.change_material_selection(
                processes[0].gid, "add", "created", "Eigen browsermateriaal", generate_olid("browser", suffix)
            )
            process_gids = [str(process.gid) for process in processes]
            team_name = team.name

        if scenario in {"catalog", "material"}:
            count = 20 if scenario == "catalog" else 2
            material_names = _browser_test_catalog(search_term, count)

        return {
            "process_gids": process_gids,
            "team_name": team_name,
            "search_term": search_term,
            "material_names": material_names,
        }

    @action("test_seed_pdf_wait", method="POST")
    @admin()
    def test_seed_pdf_wait() -> str:
        """Create a readable process for the PDF browser test."""
        location_gid = _browser_test_location(f"PDF {uuid.uuid4().hex}")
        team = backend.decision_processes.create_team(location_gid, "PDF browser test")
        process = backend.decision_processes.create_process(team.gid, calculate_next_schoolyear_label())
        return process.gid


restart_cache = FlagBasedCache(RESTART_FLAG)


@action("healthcheck")
@action.uses(db)
def healthcheck() -> str:
    """Health check endpoint for this container.

    How it works:
    1. Verifies the database connection with a lightweight `SELECT 1;`.
       Raises HTTP 500 if the DB is unreachable.
    2. Checks a shared flag file at `/shared_cache/restart.flag`.
       - If the file was touched since container boot, the container is considered unhealthy.
       - Docker will restart the container if it is unhealthy.

    Returns:
        "ok" if the container is healthy.

    Raises:
        HTTP(500) if the database connection fails.
        Exits with code 1 if the container should be restarted.

    """
    # should be relatively fast, doesn't use full backend/session
    # but does test db connection.
    if not db.executesql("SELECT 1;"):
        raise HTTP(500, "bad database connection")

    if restart_cache.is_stale():
        print("Flag file newer than container boot -> restart needed")
        sys.exit(1)  # exit immediately with non-zero code for Docker healthcheck

    return "ok"
