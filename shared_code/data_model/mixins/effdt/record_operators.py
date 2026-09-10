"""Record operator overrides for effective-dated tables."""

import typing as t

from pydal.helpers.classes import RecordOperator

from shared_code.modules.auth import AuthContext

from .helpers import model_to_ed, update_effectivedated
from .table import EffdtTable

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class AuthRecordOperator(RecordOperator):
    auth: AuthContext


def get_effective_dated_table(table: t.Any) -> type[EffdtTable] | None:
    table_rname = str(table._rname)

    if table_rname.endswith("_ed"):
        return table

    if table_rname.endswith("_model"):
        return model_to_ed(table)

    return None


def effdt_record_updater(self: AuthRecordOperator, **fields: t.Any) -> t.Any:
    db = self.db
    table = db[self.tablename]

    colset = self.colset
    newfields = fields or dict(colset)

    for fieldname in list(newfields.keys()):
        if fieldname not in table.fields or table[fieldname].type == "id":
            del newfields[fieldname]

    table_ed = get_effective_dated_table(table)

    if table_ed:
        last_saved_by = self.auth.get_email() or newfields.get("last_saved_by") or "internal/effdt_record_updater"

        for field in ("id", "sync_gid", "effdt", "last_saved_by", "updated_at"):
            newfields.pop(field, None)

        update_effectivedated(
            db,
            table_ed,
            where=table_ed.id == self.id,
            new_values=newfields,
            last_saved_by=last_saved_by,
        )
    else:
        self.db(table._id == self.id, ignore_common_filters=True).update(**newfields)

    colset.update(newfields)
    return colset


def effdt_record_deleter(self: AuthRecordOperator) -> t.Any:
    db = self.db
    table = db[self.tablename]

    table_ed = get_effective_dated_table(table)

    if table_ed:
        last_saved_by = self.auth.get_email()

        return update_effectivedated(
            db,
            table_ed,
            where=table_ed.id == self.id,
            delete=True,
            last_saved_by=last_saved_by or "internal/effdt_record_deleter",
        )

    return self.db(table._id == self.id).delete()


def setup_record_operators(db: DatabaseContext) -> None:
    """Install effective-dated record operator overrides on `db`."""
    db.record_operators = {
        "update_record": type(
            "EffdtRecordUpdater",
            (AuthRecordOperator,),
            {
                "auth": db.auth,
                "__call__": effdt_record_updater,
            },
        ),
        "delete_record": type(
            "EffdtRecordDeleter",
            (AuthRecordOperator,),
            {
                "auth": db.auth,
                "__call__": effdt_record_deleter,
            },
        ),
    }


__all__ = ["setup_record_operators"]
