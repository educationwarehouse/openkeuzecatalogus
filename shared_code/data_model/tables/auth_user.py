"""Auth user table model and identity synchronization hooks."""

import typing as t
import uuid

from edwh_auth_rbac import AuthRbac
from pydal.validators import IS_EMAIL, IS_EMPTY_OR, IS_IN_SET, IS_LOWER, IS_NOT_IN_DB
from typedal import TypeDAL, relationship
from typedal.fields import TimestampField, TypedField, UUIDField
from typedal.types import OpRow, Set, Validator
from typedal.web2py_py4web_shared import AuthUser as _AuthUser

from shared_code.data_model.constants import ROLE_USER, SECTOREN
from shared_code.data_model.mixins import SearchMixin
from shared_code.data_model.validators.is_uuid import IS_UUID
from shared_code.services import Applogger

if t.TYPE_CHECKING:  # pragma: no cover
    type identity = t.Any


class AuthUser(_AuthUser, SearchMixin, search_fields=("email", "first_name", "last_name")):
    """Application-specific auth user extension with RBAC identity sync."""

    gid = UUIDField(default=uuid.uuid4, writable=False, requires=IS_UUID(), filter_out=str, label="gid")
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
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure validators and register table hooks after model definition."""
        super().__on_define__(db)

        cls.past_passwords_hash.readable = False
        cls.past_passwords_hash.writable = False

        cls.first_name.label = "Voornaam"
        cls.last_name.label = "Achternaam"
        cls.password.label = "Wachtwoord"
        cls.password.readable = False

        cls.email.requires = t.cast(
            list[Validator],
            [
                IS_EMAIL(error_message="Vul een geldig emailadres in"),
                IS_LOWER(),  # converts
                IS_NOT_IN_DB(
                    db,
                    "auth_user.email",
                    error_message="Dit emailadres is al in gebruik",
                ),
            ],
        )

        rbac = AuthRbac(db)
        rbac.define_model(
            allowed_types=["user", "group", "item"],
            redefine=True,
            migrate=False,
        )

        applog = Applogger.from_env()

        def on_insert(row: OpRow, reference: int, logger: Applogger = applog) -> None:
            if user := rbac.get_user(row.email):
                # identity already exists, user was invited
                rbac.update_identity(
                    user["object_id"],
                    email=row.email,
                    firstname=row.first_name,
                    lastname=row.last_name,
                    fullname=f"{row.first_name} {row.last_name}",
                    password=row.password,
                )
                logger.log_auth_action(
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
                logger.log_auth_action(
                    action="registration",
                    success=True,
                    user_gid=getattr(row, "gid", None),
                    email=row.email,
                    details={"scenario": "new_identity"},
                )

            rbac.add_membership(user, ROLE_USER)

            AuthUser(reference).update_record(
                gid=user["object_id"],
            )

        cls.after_insert(on_insert)

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

    @property
    def full_name(self) -> str:
        """Return the user's display name as `first_name last_name`."""
        return f"{self.first_name} {self.last_name}"
