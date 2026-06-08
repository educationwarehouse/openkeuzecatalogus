"""Database table setup entrypoint for shared data models."""

from typedal import TypeDAL

from shared_code.data_model.tables import (
    AuthUser,
    CountsPerMinute,
    Evidence,
    Method,
    MethodEd,
    Product,
    ProductEd,
    Signal,
    Supplier,
    SupplierEd,
    Vision,
    VisionEd,
)


def define_tables(db: TypeDAL) -> TypeDAL:
    """Define shared data-model tables in the provided database."""
    db.define(
        AuthUser,
        rname="auth_user",
        format="%(email)s",
        singular="User",
        plural="Users",
        redefine=True,
        migrate=False,
    )

    # influences UI:
    AuthUser.reorder_fields(
        AuthUser.id,
        AuthUser.first_name,
        AuthUser.last_name,
        AuthUser.email,
        AuthUser.password,
        AuthUser.onderwijs_rol,
        AuthUser.onderwijs_rol_anders,
        AuthUser.onderwijs_sector,
        # ... other internal fields, not shown to user ...
    )

    db.define(
        Evidence,
        rname="evidence",
        format="%(gid)s",
        singular="Evidence",
        plural="Evidence",
        redefine=True,
        migrate=False,
    )
    db.define(
        Signal,
        rname="signal",
        format="%(name)s",
        singular="Signal",
        plural="Signals",
        redefine=True,
        migrate=False,
    )
    db.define(
        CountsPerMinute,
        rname="counts_per_minute",
        format="%(name)s",
        singular="CountsPerMinute",
        plural="CountsPerMinute",
        redefine=True,
        migrate=False,
    )

    db.define(
        Supplier,
        rname="supplier_model",
        format="%(name)s",
        singular="Supplier",
        plural="Suppliers",
        redefine=True,
        migrate=False,
    )
    db.define(
        SupplierEd,
        rname="supplier_ed",
        format="%(name)s",
        singular="SupplierEd",
        plural="SupplierEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Method,
        rname="method_model",
        format="%(name)s",
        singular="Method",
        plural="Methods",
        redefine=True,
        migrate=False,
    )
    db.define(
        MethodEd,
        rname="method_ed",
        format="%(name)s",
        singular="MethodEd",
        plural="MethodEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Product,
        rname="product_model",
        format="%(name)s",
        singular="Product",
        plural="Products",
        redefine=True,
        migrate=False,
    )
    db.define(
        ProductEd,
        rname="product_ed",
        format="%(name)s",
        singular="ProductEd",
        plural="ProductEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Vision,
        rname="vision_model",
        format="%(olid)s",
        singular="Vision",
        plural="Visions",
        redefine=True,
        migrate=False,
    )
    db.define(
        VisionEd,
        rname="vision_ed",
        format="%(olid)s",
        singular="VisionEd",
        plural="VisionEds",
        redefine=True,
        migrate=False,
    )

    # prevent locks:
    db.commit()
    return db
