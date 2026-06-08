"""Basic smoke tests for dummy database wiring."""

from typedal import TypeDAL

from shared_code.data_model import ProductEd

# note: db from conftest


def test_db_has_tables(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Verify core models exist and table iteration does not crash."""
    assert migrated_db_per_file is None
    assert db_per_file
    assert db_per_file.find_model("Product")
    assert not db_per_file.find_model("FakeModel")

    for table in db_per_file:
        # doesn't need to have values but at least shouldn't crash:
        db_per_file(table).count()


def test_product_ed_effstatus_roundtrip(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Write effstatus via ORM and verify it via SQL and ORM."""
    assert migrated_db_per_file is None

    row_true = ProductEd.insert(olid="product-ed-effstatus-true", available="leverbaar", effstatus=True)
    row_false = ProductEd.insert(olid="product-ed-effstatus-false", available="leverbaar", effstatus=False)
    db_per_file.commit()

    rows_sql = db_per_file.executesql(
        "SELECT id, effstatus FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    effstatus_sql_by_id = {row["id"]: row["effstatus"] for row in rows_sql}
    assert effstatus_sql_by_id[row_true.id] is True
    assert effstatus_sql_by_id[row_false.id] is False
    true_rows_sql = db_per_file.executesql(
        "SELECT id FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) AND effstatus = true ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    false_rows_sql = db_per_file.executesql(
        "SELECT id FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) AND effstatus = false ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    assert [row["id"] for row in true_rows_sql] == [row_true.id]
    assert [row["id"] for row in false_rows_sql] == [row_false.id]

    rows_orm = ProductEd.where(ProductEd.id.belongs((row_true.id, row_false.id))).collect()
    effstatus_orm_by_id = {row.id: row.effstatus for row in rows_orm}
    assert effstatus_orm_by_id[row_true.id] is True
    assert effstatus_orm_by_id[row_false.id] is False
