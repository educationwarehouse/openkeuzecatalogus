"""Tagged relationship table definitions."""

import typing as t

from pydal.validators import IS_IN_SET
from typedal import QueryBuilder
from typedal.fields import TypedField
from typedal.types import Expression, OnQuery

from shared_code.data_model.constants import Predicate
from shared_code.data_model.fields import UUIDReferenceField
from shared_code.data_model.tables.base import EffdtTable

if t.TYPE_CHECKING:
    from shared_code.data_model.tables.base import TableWithGid


class TaggedEd(EffdtTable):
    """Effective-dated tagged relationship source table."""

    subject_gid = UUIDReferenceField(label="Subject GID")

    predicate = TypedField(str, label="Predicate", requires=IS_IN_SET([item.value for item in Predicate]))

    object_gid = UUIDReferenceField(label="Object GID")

    comment = TypedField(str | None, label="Opmerking")


class Tagged(TaggedEd):
    """Current tagged relationship model view."""

    @classmethod
    def lookup(
        cls,
        subject_gid: str | None,
        predicate: Predicate | None,
        object_gid: str | None,
    ) -> list[str]:
        """Return the missing tagged column, or full matches when all filters are known."""
        missing = [value is None for value in (subject_gid, predicate, object_gid)]
        if missing.count(True) > 1:
            raise ValueError("Tagged.lookup expects at most one unspecified argument.")

        query = QueryBuilder(cls)
        if subject_gid is not None:
            query = query.where(subject_gid=subject_gid)
        if predicate is not None:
            query = query.where(predicate=predicate)
        if object_gid is not None:
            query = query.where(object_gid=object_gid)

        if subject_gid is None:
            return query.column(cls.subject_gid)
        elif predicate is None:
            return query.column(cls.predicate)
        elif object_gid is None:
            return query.column(cls.object_gid)
        else:
            # all 3 passed, return the Tagged.gid
            return query.column(cls.gid)

    @classmethod
    def insert_relation_if_missing(
        cls,
        subject_gid: str,
        predicate: Predicate,
        object_gid: str,
        *,
        last_saved_by: str,
        comment: str = "",
        prio: int = 0,
    ) -> bool:
        """Insert a tagged relation once, returning whether a new row was created."""
        if cls.where(subject_gid=subject_gid, predicate=predicate, object_gid=object_gid).count():
            return False

        TaggedEd.insert(
            subject_gid=subject_gid,
            predicate=predicate.value,
            object_gid=object_gid,
            comment=comment,
            last_saved_by=last_saved_by,
            prio=prio,
        )
        return True


def tagged_relationship_query(predicate: Predicate, inverse: bool = False) -> OnQuery:
    """Build a relationship query through a tagged predicate."""

    def on(subject: TableWithGid, related_object: TableWithGid) -> list[Expression]:
        tagged = Tagged.unique_alias()

        if inverse:
            tagged_condition = tagged.object_gid == subject.gid
            related_condition = tagged.subject_gid == related_object.gid
        else:
            tagged_condition = tagged.subject_gid == subject.gid
            related_condition = tagged.object_gid == related_object.gid

        return [
            t.cast(Expression, tagged),
            tagged.on((tagged.predicate == predicate) & tagged_condition),
            related_object.on(related_condition),
        ]

    return t.cast(OnQuery, on)
