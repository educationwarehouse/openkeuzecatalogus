# standalone file so it's a fresh database context
import uuid

from typedal import TypeDAL

from shared_code.data_model import Method, Product, SupplierEd
from shared_code.modules.scrapers.flow import ImportFlow
from shared_code.modules.scrapers.types import ImportPriority
from shared_code.util.olid import generate, generate_supplier_olid


def test_import_methods_and_products_marks_missing_rows_as_removed(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Importer flow should mark previously active rows as removed when omitted."""
    flow = ImportFlow.with_injected(db=db_per_file)
    supplier_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="Flow Removal Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    db_per_file.commit()

    kept_method_gid = str(uuid.uuid4())
    removed_method_gid = str(uuid.uuid4())
    kept_product_gid = str(uuid.uuid4())
    removed_product_gid = str(uuid.uuid4())
    kept_method_olid = generate("method", kept_method_gid)
    removed_method_olid = generate("method", removed_method_gid)
    kept_product_olid = generate("product", kept_product_gid)
    removed_product_olid = generate("product", removed_product_gid)

    initial_stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": kept_method_gid,
                "supplier_gid": supplier.gid,
                "olid": kept_method_olid,
                "name": "Te Houden Methode",
                "available": "leverbaar",
            },
            {
                "gid": removed_method_gid,
                "supplier_gid": supplier.gid,
                "olid": removed_method_olid,
                "name": "Te Verwijderen Methode",
                "available": "leverbaar",
            },
        ],
        products=[
            {
                "gid": kept_product_gid,
                "supplier_gid": supplier.gid,
                "olid": kept_product_olid,
                "name": "Te Houden Product",
                "available": "leverbaar",
                "method_gid": kept_method_gid,
                "method_olid": kept_method_olid,
            },
            {
                "gid": removed_product_gid,
                "supplier_gid": supplier.gid,
                "olid": removed_product_olid,
                "name": "Te Verwijderen Product",
                "available": "leverbaar",
                "method_gid": removed_method_gid,
                "method_olid": removed_method_olid,
            },
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.removed",
        mark_removed=True,
    )

    assert initial_stats.methods.new == 2
    assert initial_stats.products.new == 2
    assert initial_stats.methods.removed == 0
    assert initial_stats.products.removed == 0

    removal_stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": kept_method_gid,
                "supplier_gid": supplier.gid,
                "olid": kept_method_olid,
                "name": "Te Houden Methode",
                "available": "leverbaar",
            }
        ],
        products=[
            {
                "gid": kept_product_gid,
                "supplier_gid": supplier.gid,
                "olid": kept_product_olid,
                "name": "Te Houden Product",
                "available": "leverbaar",
                "method_gid": kept_method_gid,
                "method_olid": kept_method_olid,
            }
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.removed",
        mark_removed=True,
    )

    assert removal_stats.methods.removed == 1
    assert removal_stats.products.removed == 1

    removed_method = Method.where(Method.olid == removed_method_olid).first_or_fail()
    removed_product = Product.where(Product.olid == removed_product_olid).first_or_fail()
    assert removed_method.available == "verwijderd"
    assert removed_product.available == "verwijderd"
