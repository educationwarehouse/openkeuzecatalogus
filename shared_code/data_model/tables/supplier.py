"""Supplier table definitions."""

import typing as t
import uuid

from pydal.validators import IS_EMPTY_OR, IS_IN_SET, IS_URL
from typedal import TypeDAL
from typedal.fields import TypedField
from typedal.helpers import classproperty
from typedal.types import OpRow

from shared_code.data_model.constants import ROLE_SUPPLIER
from shared_code.data_model.mixins.effdt.mixin import EffdtFields
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.representers.lists import comma_separated
from shared_code.data_model.tables.base import BaseTable
from shared_code.util.olid import generate_supplier_olid

if t.TYPE_CHECKING:
    pass


def keep_supplier_group_in_sync(cls: type[SupplierEd]) -> t.Callable[[OpRow, int], None]:
    """Keep the supplier RBAC group aligned with the latest active supplier row."""
    db = cls._db  # type: DatabaseContext
    assert db, "Can't use keep_supplier_group_in_sync on a class used without db.define()"
    auth = db.auth
    # access raw rbac because AuthContext doesn't include all these features (update_identity, add_group)
    # (todo)
    rbac = auth.raw_rbac

    def wrapper(_changes: OpRow, row_id: int) -> None:
        row = cls(row_id)
        if not row or row.effstatus is False:
            return

        group_email = f"{row.gid}@supplier"

        if existing := rbac.get_group(row.gid):
            # propagate name changes
            rbac.update_identity(existing["object_id"], email=group_email, name=row.name, fullname=row.name)
        else:
            rbac.add_group(
                group_email,
                row.name,
                [ROLE_SUPPLIER],
                gid=str(row.gid),
                allow_existing=True,
            )
            db.applog.try_fire(
                {
                    "kind": "event",
                    "action": "supplier-group-created",
                    "user_gid": db.auth.id,
                    "related": str(row.gid),
                    "details": {
                        "supplier_gid": str(row.gid),
                        "supplier_name": row.name,
                        "group_email": group_email,
                    },
                },
            )

        rbac.add_permission(row.gid, row.gid, "*")

    return wrapper


class SupplierEd(BaseTable, EffdtFields):
    """Effective-dated supplier source table."""

    name = TypedField(str, label="Naam", required=True)
    olid = TypedField(str, label="OLID", unique=True)
    logo_url = TypedField(str, label="Logo URL")
    status_visions = TypedField(
        str,
        label="Status Visies",
        requires=IS_IN_SET(
            {
                "nog niet gedeeld",
                "wil niet delen",
                "in gesprek",
                "compleet",
            },
        ),
    )

    email_domains = TypedField(
        list[str],
        label="Email Domeinen",
        comment="Gebruikt voor automatische rol-toekenning",
        represent=comma_separated,
    )

    endpoint_type = TypedField(
        str,
        requires=IS_IN_SET(("edu-v", "none")),
        label="Type API endpoint",
    )

    endpoint_base_url = TypedField(
        str | None,
        requires=IS_EMPTY_OR(IS_URL()),
        label="Basis-URL endpoint voor data-import",
        comment="Zonder resource-pad, bijvoorbeeld: https://catalogus.edu-v.kennisnet.nl/v2/",
    )

    endpoint_publisher = TypedField(
        str | None,
        label="Edu-V publisher filter",
        comment="Alleen invullen voor gedeelde Kennisnet-catalogus URL's; leeg laten voor leverancier-eigen endpoint.",
    )

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Generate supplier OLIDs before inserts when none was supplied."""
        super().__on_define__(db)

        def on_insert(fields: SupplierEd) -> None:
            if fields.get("olid"):
                return

            gid = fields.get("gid") or uuid.uuid4()
            fields["gid"] = gid
            fields["olid"] = generate_supplier_olid(gid)

        cls.before_insert(on_insert)
        cls.after_insert(keep_supplier_group_in_sync(cls))

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for suppliers."""
        return "suppliers"


class Supplier(SupplierEd, SearchMixin, search_fields=("name", "gid", "olid")):
    """Current supplier model view."""
