"""Shared auth support domain."""

import typing as t
import uuid

from endow import Domain
from pydal.validators import IS_EMAIL
from typedal.fields import Field, TypedField
from typedal.types import Query

from shared_code.data_model.tables import AuthUser, DecisionTeam, Identity, Organisation, Supplier
from shared_code.data_model.validators.is_existing_sso_account import build_normalized_email_match_query
from shared_code.services.mail.contracts import Mailer
from shared_code.util.email import (
    canonicalize_email_for_similarity,
    email_domain_sql_v1,
    normalize_email_for_lookup,
)

from ...data_model import Membership
from .contract import AuthContext

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class InviteMembershipTarget(t.TypedDict):
    """Resolved organisation, supplier, or teaching-team invite target."""

    gid: str
    label: str


class InviteCandidate(t.TypedDict):
    """Existing user or invited identity candidate.

    The two membership flags are deliberately separate, because they answer different
    questions and can disagree:

    - `already_member`: can this subject reach the group at all, at any nesting depth? A user
      attached to a team below a school reaches the school, and the board above it, this way.
    - `direct_member`: is there a `membership` row linking subject and group directly? Only
      these show up in a depth-1 member listing, and only these can be revoked again.

    An inherited-only subject (`already_member` without `direct_member`) may still be granted
    a direct membership: that is what puts them in the organisation's own member list.
    """

    subject_id: str
    email: str
    full_name: str
    source: str
    already_member: bool
    direct_member: bool


class InviteLookupResult(t.TypedDict):
    """Lookup outcome for one invite email."""

    email: str
    canonical_email: str
    exact_match: InviteCandidate | None
    similar_match: InviteCandidate | None


class AuthSupportBackend(Domain):
    """Shared auth-side orchestration for invites and membership support."""

    db: DatabaseContext
    auth: AuthContext
    mailer: Mailer

    def resolve_membership_target(self, membership_gid: str | None) -> InviteMembershipTarget | None:
        """Resolve an inviteable supplier, organisation, or teaching-team target."""
        if not membership_gid:
            return None

        if organisation := Organisation.where(gid=membership_gid).select(Organisation.name).first():
            return InviteMembershipTarget(
                gid=membership_gid,
                label=organisation.name or membership_gid,
            )

        if supplier := Supplier.where(gid=membership_gid).select(Supplier.name).first():
            return InviteMembershipTarget(
                gid=membership_gid,
                label=supplier.name or membership_gid,
            )

        if team := DecisionTeam.where(gid=membership_gid).select(DecisionTeam.name).first():
            return InviteMembershipTarget(
                gid=membership_gid,
                label=team.name or membership_gid,
            )

        return None

    def normalize_invite_email(self, email: str | None) -> tuple[str | None, str | None]:
        """Normalize and validate an invite email."""
        normalized_email = normalize_email_for_lookup(email)
        value, error = IS_EMAIL(error_message="Vul een geldig e-mailadres in")(normalized_email)
        if error:
            return None, str(error)

        return str(value), None

    def lookup_invite_candidate(self, email: str, membership_gid: str | None) -> InviteLookupResult:
        """Lookup exact and similar existing identities for an invite email."""
        # todo: Once organisations can manage this themselves, suggest related existing users while typing.
        exact_match = self._find_exact_match(email, membership_gid)
        similar_match = None if exact_match else self._find_similar_match(email, membership_gid)

        return InviteLookupResult(
            email=email,
            canonical_email=canonicalize_email_for_similarity(email),
            exact_match=exact_match,
            similar_match=similar_match,
        )

    def grant_invited_membership(self, subject_id: str, membership_gid: str) -> None:
        """Grant direct membership to an existing user or invited identity."""
        self.auth.add_membership(subject_id, membership_gid)

    def revoke_invited_membership(self, subject_id: str, membership_gid: str) -> None:
        """Revoke direct membership from an invited identity or user subject."""
        self.auth.remove_membership(subject_id, membership_gid)
        self.db.commit()

    def create_invited_identity(
        self,
        email: str,
        first_name: str,
        last_name: str,
    ) -> InviteCandidate:
        """Create an invited RBAC identity claimable by later registration or SSO."""
        gid = str(uuid.uuid4())

        self.auth.raw_rbac.add_user(
            email=email,
            firstname=first_name,
            fullname=f"{first_name} {last_name}".strip(),
            password="",
            member_of=[],
            gid=gid,
        )
        return InviteCandidate(
            subject_id=gid,
            email=email,
            full_name=f"{first_name} {last_name}".strip(),
            source="identity",
            already_member=False,
            direct_member=False,
        )

    def send_membership_invite_email(
        self,
        *,
        email: str,
        membership_label: str,
        invite_url: str,
        first_name: str,
    ) -> None:
        """Send the shared invite email for a newly created invited identity."""
        greeting = first_name or "daar"
        self.mailer.send(
            to=email,
            subject=f"Uitnodiging voor {membership_label}",
            body=(
                f"Hallo {greeting},\n\n"
                f"Je bent uitgenodigd voor {membership_label} in de Open Keuzecatalogus.\n"
                f"Gebruik dit e-mailadres om in te loggen of een account aan te maken via:\n{invite_url}\n\n"
                "Na registratie of SSO-login wordt je toegang automatisch gekoppeld."
            ),
        )

    def invite_membership(
        self,
        *,
        email: str | None,
        first_name: str,
        last_name: str,
        membership_gid: str,
        membership_label: str,
        invite_url: str,
    ) -> None:
        """Grant an existing identity or create and invite a new membership identity."""
        normalized_email, error = self.normalize_invite_email(email)
        if error or not normalized_email:
            raise ValueError(error or "Vul een geldig e-mailadres in.")

        lookup = self.lookup_invite_candidate(normalized_email, membership_gid)
        candidate = lookup["exact_match"] or lookup["similar_match"]
        if candidate:
            # `direct_member`, not `already_member`: someone who only inherits access through a
            # nested group still needs their own row to appear in this organisation's member list
            if not candidate["direct_member"]:
                self.grant_invited_membership(candidate["subject_id"], membership_gid)
            return

        invited = self.create_invited_identity(normalized_email, first_name, last_name)
        self.grant_invited_membership(invited["subject_id"], membership_gid)
        self.send_membership_invite_email(
            email=normalized_email,
            membership_label=membership_label,
            invite_url=invite_url,
            first_name=first_name,
        )

    def has_direct_membership(self, subject_id: str, membership_gid: str) -> bool:
        """Return whether a direct `membership` row links one subject to one group.

        `AuthContext.has_subject_membership` answers the transitive question instead, so the
        two differ for a subject that only reaches the group through a nested group.
        """
        return Membership.where(subject=subject_id).where(member_of=membership_gid).exists()

    def _candidate_from_user(self, user: AuthUser, membership_gid: str | None) -> InviteCandidate:
        subject_id = user.gid
        return InviteCandidate(
            subject_id=subject_id,
            email=user.email,
            full_name=user.full_name.strip(),
            source="user",
            already_member=bool(membership_gid) and self.auth.has_subject_membership(subject_id, membership_gid),
            direct_member=bool(membership_gid) and self.has_direct_membership(subject_id, membership_gid),
        )

    def _candidate_from_identity(self, identity: t.Any, membership_gid: str | None) -> InviteCandidate:
        subject_id = str(identity.object_id)
        return InviteCandidate(
            subject_id=subject_id,
            email=str(identity.email or ""),
            full_name=str(identity.fullname or identity.firstname or identity.email or ""),
            source="identity",
            already_member=bool(membership_gid) and self.auth.has_subject_membership(subject_id, membership_gid),
            direct_member=bool(membership_gid) and self.has_direct_membership(subject_id, membership_gid),
        )

    def _find_exact_match(self, email: str, membership_gid: str | None) -> InviteCandidate | None:
        normalized_email = normalize_email_for_lookup(email)

        user = (
            AuthUser.where(build_normalized_email_match_query(AuthUser.email, normalized_email))
            .select(AuthUser.gid, AuthUser.email, AuthUser.first_name, AuthUser.last_name)
            .first()
        )
        if user:
            return self._candidate_from_user(user, membership_gid)

        identity_query = (Identity.object_type == "user") & build_normalized_email_match_query(
            Identity.email,
            normalized_email,
        )
        identity = (
            Identity.where(identity_query)
            .select(
                Identity.object_id,
                Identity.email,
                Identity.firstname,
                Identity.fullname,
                limitby=(0, 1),
            )
            .first()
        )
        if identity:
            return self._candidate_from_identity(identity, membership_gid)

        return None

    def _same_email_domain(self, email_field: Field | TypedField[t.Any], domain: str) -> Query:
        """Match rows whose email domain equals `domain`, using the email-domain index.

        This only narrows the candidate set (see `email_domain_sql`); the canonicalization in
        `_find_similar_match` still decides whether a candidate actually matches. The expression
        carries no table of its own, so callers must combine it with a real field condition.
        """
        literal = self.db._adapter.represent(domain, "string")
        return Query(self.db, f"{email_domain_sql_v1(email_field)} = {literal}")

    def _find_similar_match(self, email: str, membership_gid: str | None) -> InviteCandidate | None:
        normalized_email = normalize_email_for_lookup(email)
        target = canonicalize_email_for_similarity(email)
        if "@" not in target:
            return None

        _, target_domain = target.rsplit("@", 1)

        user_rows = AuthUser.where(
            (AuthUser.email != None) & self._same_email_domain(AuthUser.email, target_domain),
        ).select(
            AuthUser.gid,
            AuthUser.email,
            AuthUser.first_name,
            AuthUser.last_name,
            orderby=AuthUser.id,
        )
        for user in user_rows:
            user_email = normalize_email_for_lookup(user.email)
            if user_email == normalized_email:
                continue
            if canonicalize_email_for_similarity(user_email) == target:
                return self._candidate_from_user(user, membership_gid)

        identity_rows = Identity.where(
            (Identity.email != None)
            & (Identity.object_type == "user")
            & self._same_email_domain(Identity.email, target_domain),
        ).select(
            Identity.object_id,
            Identity.email,
            Identity.firstname,
            Identity.fullname,
            orderby=Identity.id,
        )
        for identity in identity_rows:
            identity_email = normalize_email_for_lookup(identity.email)
            if identity_email == normalized_email:
                continue
            if canonicalize_email_for_similarity(identity_email) == target:
                return self._candidate_from_identity(identity, membership_gid)

        return None


__all__ = [
    "AuthSupportBackend",
    "InviteCandidate",
    "InviteLookupResult",
    "InviteMembershipTarget",
]
