"""Auth user table model and identity synchronization hooks."""

import typing as t

from edwh_auth_rbac.rbac import AuthRbac, UserDict
from pydal.validators import IS_EMAIL, IS_EMPTY_OR, IS_IN_SET, IS_LOWER, IS_NOT_IN_DB
from typedal import relationship
from typedal.fields import TimestampField, TypedField
from typedal.helpers import classproperty
from typedal.types import OpRow, Set, Validator
from typedal.web2py_py4web_shared import AuthUser as _AuthUser

from shared_code.data_model.constants import ROLE_USER, SECTOREN
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import TableWithGid
from shared_code.data_model.validators.is_existing_sso_account import (
    IS_EMPTY_ON_UPDATE,
    IS_NORMALIZED_EMAIL,
    IS_NOT_EXISTING_SSO_ACCOUNT,
    build_normalized_email_match_query,
)
from shared_code.util.email import normalize_email_for_lookup

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

    type identity = t.Any


def _resolve_existing_identity_by_normalized_email(
    rbac: AuthRbac,
    db: DatabaseContext,
    email: str,
) -> UserDict | None:
    """Resolve an existing RBAC identity by exact or normalized email."""
    if existing := rbac.get_user(email):
        return existing

    normalized_email = normalize_email_for_lookup(email)
    identity_query = (db.identity.object_type == "user") & build_normalized_email_match_query(
        db.identity.email,
        normalized_email,
    )
    identity_row = db(identity_query).select(db.identity.object_id, limitby=(0, 1)).first()
    if identity_row and (existing := rbac.get_user(identity_row.object_id)):
        return existing

    return None


class AuthUser(_AuthUser, TableWithGid, SearchMixin, search_fields=("email", "first_name", "last_name")):
    """Application-specific auth user extension with RBAC identity sync."""

    # grid from mixin
    api_key_hash = TypedField(str, readable=False, writable=False)
    past_passwords_hash: TypedField[list[str]]
    reset_password_expires_at = TimestampField(readable=False, writable=False, notnull=False)
    onderwijs_rol = TypedField(
        str,
        requires=IS_EMPTY_OR(
            IS_IN_SET(("docent", "bestuurder", "schoolleider", "anders")),
        ),
    )
    onderwijs_rol_anders = TypedField(str)
    onderwijs_sector = TypedField(str, requires=IS_EMPTY_OR(IS_IN_SET(SECTOREN)))

    roles = relationship(
        list["identity"],
        on=lambda auth_user, identity: [
            # Create a PyDAL alias table for the join manually as alternative to TypedTable.unique_alias():
            membership := AuthUser._db.membership.with_alias("user_identity_membership"),  # type: ignore
            # Define how membership links the user to identities
            membership.on(membership.subject == auth_user.gid),
            # Then link to the identity table
            identity.on(identity.object_id == membership.member_of),
        ],
    )

    @classmethod
    def __on_define__(cls, db: DatabaseContext) -> None:
        """Configure validators and register table hooks after model definition."""
        super().__on_define__(db)
        auth = db.auth
        # access raw rbac because AuthContext doesn't include all these features (update_identity, add_user)
        # (todo)
        rbac = auth.raw_rbac

        cls.past_passwords_hash.readable = False
        cls.past_passwords_hash.writable = False

        cls.first_name.label = "Voornaam"
        cls.last_name.label = "Achternaam"
        cls.password.label = "Wachtwoord"
        cls.password.readable = False
        cls.password.requires = IS_EMPTY_ON_UPDATE(cls.password.requires or [])

        cls.email.requires = t.cast(
            list[Validator],
            [
                IS_NORMALIZED_EMAIL(IS_EMAIL(error_message="Vul een geldig emailadres in")),
                IS_LOWER(),  # converts
                IS_NOT_EXISTING_SSO_ACCOUNT(db),
                IS_NOT_IN_DB(
                    db,
                    "auth_user.email",
                    error_message="Dit emailadres is al in gebruik",
                ),
            ],
        )

        def on_insert(row: OpRow, reference: int) -> None:
            if user := _resolve_existing_identity_by_normalized_email(rbac, db, row.email):
                # identity already exists, user was invited
                rbac.update_identity(
                    user["object_id"],
                    email=row.email,
                    firstname=row.first_name,
                    lastname=row.last_name,
                    fullname=f"{row.first_name} {row.last_name}",
                    password=row.password,
                )
                db.applog.log_auth_action(
                    action="registration",
                    success=True,
                    user_gid=getattr(row, "gid", None),
                    email=row.email,
                    details={"scenario": "invited_identity"},
                )
            else:
                user = rbac.add_user(
                    email=row.email,
                    firstname=row.first_name,
                    fullname=f"{row.first_name} {row.last_name}",
                    password=row.password,
                    member_of=[],
                    gid=getattr(row, "gid", None),
                )
                db.applog.log_auth_action(
                    action="registration",
                    success=True,
                    user_gid=getattr(row, "gid", None),
                    email=row.email,
                    details={"scenario": "new_identity"},
                )

            db.commit()
            user_gid = user["object_id"]

            # normal auth, includes logging:
            auth.add_membership(user_gid, ROLE_USER)

            AuthUser(reference).update_record(
                gid=user_gid,
            )
            db.commit()

        cls.after_insert(on_insert)

        def on_before_update(_selection: Set, changes: OpRow) -> bool:
            """Omit an empty password field so it cannot clear the stored password."""
            update_changes = t.cast(dict, changes)
            if "password" not in update_changes or update_changes["password"] is not None:
                return False

            del update_changes["password"]
            return not tuple(update_changes)

        cls.before_update(on_before_update)

        def on_update(selection: Set, changes: OpRow) -> None:
            users: list[AuthUser] = selection.select(
                AuthUser.id,
                AuthUser.first_name,
                AuthUser.last_name,
                AuthUser.gid,
            )
            for user in users:
                identity = rbac.get_user(user.gid)
                if not identity:
                    continue

                fullname = f"{user.first_name} {user.last_name}"
                password = changes.get("password")

                if password and not isinstance(password, str):
                    password = password.password

                rbac.update_identity(
                    object_id=identity["object_id"],
                    email=changes.get("email"),
                    firstname=changes.get("first_name"),
                    lastname=changes.get("last_name"),
                    fullname=fullname,
                    password=password,
                )

        cls.after_update(on_update)

        # note: no on_delete because identity may not be removed!
        # auth_user can be deleted though, the identity with its permissions will stay.

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for users."""
        return "users"

    @property
    def full_name(self) -> str:
        """Return the user's display name as `first_name last_name`."""
        return f"{self.first_name} {self.last_name}"
