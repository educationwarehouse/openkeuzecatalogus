"""Typed mirrors of the tables and views managed by ``edwh-auth-rbac``."""

from datetime import datetime

from typedal import TypedTable
from typedal.fields import TypedField


class Identity(TypedTable):
    """RBAC identity record for a user, group, or item."""

    object_id = TypedField(str, required=True, unique=True, length=36)
    object_type = TypedField(str)
    created = TypedField(datetime)
    email = TypedField(str)
    firstname = TypedField(str)
    lastname = TypedField(str)
    fullname = TypedField(str)
    encoded_password = TypedField(str)


class Membership(TypedTable):
    """Direct RBAC membership relation between two identities."""

    subject = TypedField(str, required=True, length=36)
    member_of = TypedField(str, required=True, length=36)


class RecursiveMembers(TypedTable):
    """Read-only RBAC view of identities reachable from a group."""

    root = TypedField(str)
    object_id = TypedField(str)
    object_type = TypedField(str)
    level = TypedField(int)
    email = TypedField(str)
    firstname = TypedField(str)
    fullname = TypedField(str)
