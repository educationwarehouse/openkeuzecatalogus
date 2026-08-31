"""Tests for auth support flows and user audit-log filtering."""

import datetime as dt
import json
import typing as t
import uuid

from edwh_auth_rbac import AuthRbac
from typedal import TypeDAL

from shared_code.data_model import AuthUser, OrganisationEd, Supplier
from shared_code.data_model.constants import OrganisationType
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.services.applog.handler import all_audit_logs, process_applog_signal, user_audit_logs
from shared_code.services.mail import MockMailer


def _make_auth_support_backend(db: TypeDAL) -> AuthSupportBackend:
    return AuthSupportBackend.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("pytest.auth_support"),
        mailer=MockMailer.from_env(),
    )


def test_lookup_invite_candidate_prefers_exact_user_and_falls_back_to_similar_identity(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    auth_user_factory: t.Callable[..., AuthUser],
    seeded_rbac: AuthRbac,
) -> None:
    """Invite lookup should prefer exact users and detect canonicalized invited identities."""
    assert migrated_db_per_file is None

    suffix = uuid.uuid4().hex
    backend = _make_auth_support_backend(db_per_file)
    membership = seeded_rbac.add_group(
        f"invite-target-{suffix}@internal",
        "Invite Test Target",
        [],
        allow_existing=True,
    )
    membership_gid = str(membership["object_id"])

    exact_user = auth_user_factory(
        prefix=f"invite-exact-{suffix}",
        domain="example.test",
        first_name="Exact",
        last_name="User",
    )

    similar_identity_gid = str(uuid.uuid4())
    similar_identity_email = f"invite.similar.{suffix}@example.test"
    seeded_rbac.add_user(
        email=similar_identity_email,
        firstname="Similar",
        fullname="Similar Identity",
        password="",
        member_of=[],
        gid=similar_identity_gid,
    )
    seeded_rbac.add_membership(similar_identity_gid, membership_gid)
    db_per_file.commit()

    exact_result = backend.lookup_invite_candidate(str(exact_user.email), membership_gid)
    assert exact_result["email"] == exact_user.email
    assert exact_result["similar_match"] is None
    assert exact_result["exact_match"] == {
        "subject_id": str(exact_user.gid),
        "email": exact_user.email,
        "full_name": "Exact User",
        "source": "user",
        "already_member": False,
    }

    similar_result = backend.lookup_invite_candidate(f"invitesimilar{suffix}@example.test", membership_gid)
    assert similar_result["exact_match"] is None
    assert similar_result["canonical_email"] == f"invitesimilar{suffix}@example.test"
    assert similar_result["similar_match"] == {
        "subject_id": similar_identity_gid,
        "email": similar_identity_email,
        "full_name": "Similar Identity",
        "source": "identity",
        "already_member": True,
    }


def test_normalize_invite_email_returns_normalized_or_error(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Invite email normalization should return canonical values and validation errors."""
    assert migrated_db_per_file is None

    backend = _make_auth_support_backend(db_per_file)

    normalized, error = backend.normalize_invite_email("  USER+Invite@Example.Test ")
    assert normalized == "user+invite@example.test"
    assert error is None

    invalid_value, invalid_error = backend.normalize_invite_email("not-an-email")
    assert invalid_value is None
    assert invalid_error == "Vul een geldig e-mailadres in"


def test_auth_support_invite_lifecycle_and_membership_target_resolution(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Auth support should resolve targets and run invite identity lifecycle end-to-end."""
    assert migrated_db_per_file is None

    suffix = uuid.uuid4().hex
    backend = _make_auth_support_backend(db_per_file)

    organisation = OrganisationEd.insert(
        name=f"Invite Organisation {suffix}",
        organisation_type=OrganisationType.SCHOOL.value,
        email_domains=[],
    )
    assert organisation is not None

    supplier = supplier_factory(
        name=f"Invite Supplier {suffix}",
        email_domains=[f"invite-supplier-{suffix}.example.test"],
    )

    organisation_target = backend.resolve_membership_target(str(organisation.gid))
    assert organisation_target == {
        "gid": str(organisation.gid),
        "label": f"Invite Organisation {suffix}",
    }

    supplier_target = backend.resolve_membership_target(str(supplier.gid))
    assert supplier_target == {
        "gid": str(supplier.gid),
        "label": f"Invite Supplier {suffix}",
    }

    assert backend.resolve_membership_target(str(uuid.uuid4())) is None
    assert backend.resolve_membership_target(None) is None

    membership = seeded_rbac.add_group(
        f"invite-lifecycle-{suffix}@internal",
        f"Invite Lifecycle {suffix}",
        [],
        allow_existing=True,
    )
    membership_gid = str(membership["object_id"])

    invited_email = f"invite.lifecycle.{suffix}@example.test"
    invited = backend.create_invited_identity(
        email=invited_email,
        first_name="Invite",
        last_name="Lifecycle",
    )

    assert invited["email"] == invited_email
    assert invited["full_name"] == "Invite Lifecycle"
    assert invited["source"] == "identity"
    assert invited["already_member"] is False
    assert invited["subject_id"]

    identity_row = (
        db_per_file(
            (db_per_file.identity.object_type == "user") & (db_per_file.identity.object_id == invited["subject_id"]),
        )
        .select(
            db_per_file.identity.object_id,
            db_per_file.identity.email,
            limitby=(0, 1),
        )
        .first()
    )
    assert identity_row is not None
    assert str(identity_row.email or "") == invited_email

    assert seeded_rbac.has_membership(invited["subject_id"], membership_gid) is False
    backend.grant_invited_membership(invited["subject_id"], membership_gid)
    assert seeded_rbac.has_membership(invited["subject_id"], membership_gid) is True
    backend.revoke_invited_membership(invited["subject_id"], membership_gid)
    assert seeded_rbac.has_membership(invited["subject_id"], membership_gid) is False

    backend.send_membership_invite_email(
        email=invited_email,
        membership_label=f"Invite Lifecycle {suffix}",
        invite_url="https://example.test/invite",
        first_name="Invite",
    )

    inbox_rows = [
        json.loads(line)
        for line in backend.mailer.inbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching_mails = [
        row
        for row in inbox_rows
        if row.get("subject") == f"Uitnodiging voor Invite Lifecycle {suffix}"
    ]
    assert len(matching_mails) == 1
    invite_mail = matching_mails[0]
    assert invite_mail["subject"] == f"Uitnodiging voor Invite Lifecycle {suffix}"
    assert "Hallo Invite" in (invite_mail["text_body"] or "")
    assert "https://example.test/invite" in (invite_mail["text_body"] or "")

    exact_user = auth_user_factory(
        prefix=f"invite-exact-normalized-{suffix}",
        domain="example.test",
        first_name="Exact",
        last_name="Normalized",
    )
    exact_normalized_probe = f"  {exact_user.email.upper()}  "
    assert backend._find_similar_match(exact_normalized_probe, membership_gid) is None

    assert backend._find_similar_match("invalid-email-without-at", membership_gid) is None


def test_user_audit_logs_matches_nested_details_and_normalized_email(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """User audit logs should include nested user references and normalized email matches."""
    assert migrated_db_per_file is None

    target_gid = str(uuid.uuid4())
    unrelated_gid = str(uuid.uuid4())

    process_applog_signal(
        db_per_file,
        name="admin-action",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "gid-match",
            "details": {"target_user_gid": target_gid},
            "admin_email": "admin@example.test",
        },
        ts=dt.datetime(2026, 7, 6, 10, 0, 0),
    )
    process_applog_signal(
        db_per_file,
        name="membership-invite",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "email-match",
            "details": {"candidate_email": " TARGET@Example.Test "},
            "email": "target@example.test",
        },
        ts=dt.datetime(2026, 7, 6, 10, 1, 0),
    )
    process_applog_signal(
        db_per_file,
        name="admin-action",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "unrelated",
            "details": {"target_user_gid": unrelated_gid, "candidate_email": "other@example.test"},
        },
        ts=dt.datetime(2026, 7, 6, 10, 2, 0),
    )
    db_per_file.commit()

    logs = user_audit_logs(
        db_per_file,
        user_gid=target_gid,
        user_email="target@example.test",
        limit=10,
    )

    assert [log["name"] for log in logs] == ["membership-invite", "admin-action"]
    assert [t.cast(dict[str, t.Any], log["evidence"])["action"] for log in logs] == ["email-match", "gid-match"]
    assert logs[0]["user"] == "target@example.test"
    assert logs[1]["user"] == "admin@example.test"


def test_user_audit_logs_matches_direct_signal_and_evidence_user_references(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """User audit logs should match direct signal/evidence references and honor the result limit."""
    assert migrated_db_per_file is None

    target_gid = str(uuid.uuid4())
    unrelated_gid = str(uuid.uuid4())

    process_applog_signal(
        db_per_file,
        name="oldest-signal-user",
        signal_source="pytest",
        user_gid=target_gid,
        ts=dt.datetime(2099, 1, 2, 10, 0, 0),
    )
    process_applog_signal(
        db_per_file,
        name="middle-related-user",
        signal_source="pytest",
        related=target_gid,
        ts=dt.datetime(2099, 1, 2, 10, 1, 0),
    )
    process_applog_signal(
        db_per_file,
        name="newest-evidence-user",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "evidence-user",
            "user_gid": target_gid,
            "by_eddie_email": "eddie@example.test",
        },
        ts=dt.datetime(2099, 1, 2, 10, 2, 0),
    )
    process_applog_signal(
        db_per_file,
        name="unrelated-signal-user",
        signal_source="pytest",
        user_gid=unrelated_gid,
        ts=dt.datetime(2099, 1, 2, 10, 3, 0),
    )
    db_per_file.commit()

    limited_logs = user_audit_logs(
        db_per_file,
        user_gid=target_gid,
        user_email=None,
        limit=2,
    )

    assert [log["name"] for log in limited_logs] == ["newest-evidence-user", "middle-related-user"]
    assert limited_logs[0]["user"] == "eddie@example.test"
    assert t.cast(dict[str, t.Any], limited_logs[0]["evidence"])["action"] == "evidence-user"
    assert str(limited_logs[1]["related"]) == target_gid

    all_matching_logs = user_audit_logs(
        db_per_file,
        user_gid=target_gid,
        user_email=None,
        limit=10,
    )
    assert [log["name"] for log in all_matching_logs] == [
        "newest-evidence-user",
        "middle-related-user",
        "oldest-signal-user",
    ]
    assert str(all_matching_logs[2]["user_gid"]) == target_gid


def test_all_audit_logs_returns_recent_rows_with_evidence_user_fallbacks(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """All audit logs should expose evidence payloads, user labels, and newest-first limiting."""
    assert migrated_db_per_file is None

    older_user_gid = str(uuid.uuid4())
    newest_related_gid = str(uuid.uuid4())

    process_applog_signal(
        db_per_file,
        name="older-direct-user",
        signal_source="pytest",
        user_gid=older_user_gid,
        ts=dt.datetime(2100, 1, 1, 10, 0, 0),
    )
    process_applog_signal(
        db_per_file,
        name="middle-email-evidence",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "middle",
            "email": "middle@example.test",
        },
        ts=dt.datetime(2100, 1, 1, 10, 1, 0),
    )
    process_applog_signal(
        db_per_file,
        name="newest-admin-evidence",
        signal_source="pytest",
        evidence={
            "kind": "event",
            "action": "newest",
            "admin_email": "admin@example.test",
        },
        related=newest_related_gid,
        ts=dt.datetime(2100, 1, 1, 10, 2, 0),
    )
    db_per_file.commit()

    logs = all_audit_logs(db_per_file, limit=2)

    assert [log["name"] for log in logs] == ["newest-admin-evidence", "middle-email-evidence"]
    assert logs[0]["user"] == "admin@example.test"
    assert str(logs[0]["related"]) == newest_related_gid
    assert t.cast(dict[str, t.Any], logs[0]["evidence"])["action"] == "newest"
    assert logs[1]["user"] == "middle@example.test"
    assert t.cast(dict[str, t.Any], logs[1]["evidence"])["action"] == "middle"

    logs_with_older_row = all_audit_logs(db_per_file, limit=3)
    assert [log["name"] for log in logs_with_older_row] == [
        "newest-admin-evidence",
        "middle-email-evidence",
        "older-direct-user",
    ]
    assert str(logs_with_older_row[2]["user"]) == older_user_gid
    assert logs_with_older_row[2]["evidence"] is None
