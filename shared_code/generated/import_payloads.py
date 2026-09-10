"""Generated importer payload types. Do not edit manually."""

import datetime as dt
import typing as t
from shared_code.modules.scrapers.errors import ImportErrorCode

class ImportMethod(t.TypedDict, total=False):
    """Generated importer payload for MethodEd."""
    name: str
    guide_price: float
    sample_copies: str
    preview_digital_environment: str
    gid: str
    olid: str
    supplier_gid: str
    levels: list[str]
    subjects: list[str]
    image_url: str
    description: str
    available: str
    import_error_codes: list[str] | list[ImportErrorCode]
    edition: int
    publication_date: dt.date | None
    authors: list[str]
    language: str
    license_duration: str
    physical_digital_mix: str
    digital_folio_mix: list[str]
    browser: list[str]
    devices: list[str]
    operating_systems: list[str]
    elo_integration: str
    more_information: str
    priority: int
    bouw: list[str]
    tto: bool
    effdt: dt.datetime
    effstatus: bool
    last_saved_by: str
    prio: int
    sync_gid: str
    _errors: list[ImportErrorCode]

class ImportProduct(t.TypedDict, total=False):
    """Generated importer payload for ProductEd."""
    isbn: str
    name: str
    method_gid: str | None
    payment_models: list[str]
    product_usages: list[str]
    related_products: list[str]
    specific_access_urls: list[str]
    specific_access_url_types: list[str]
    level_x_year: list[str]
    sample_copies_link: str
    recommended_price: float
    weight: float
    dimensions: str
    demo_environment_link: str
    composition: str
    copyright_type: str | None
    deprecation_date: dt.date | None
    end_of_life_date: dt.date | None
    follow_up_product: str | None
    for_sale: bool | None
    intended_end_user_role: str | None
    is_consumption_product: bool | None
    sale_unit_size: int | None
    supported_until_date: dt.date | None
    gid: str
    olid: str
    supplier_gid: str
    levels: list[str]
    subjects: list[str]
    image_url: str
    description: str
    available: str
    import_error_codes: list[str] | list[ImportErrorCode]
    edition: int
    publication_date: dt.date | None
    authors: list[str]
    language: str
    license_duration: str
    physical_digital_mix: str
    digital_folio_mix: list[str]
    browser: list[str]
    devices: list[str]
    operating_systems: list[str]
    elo_integration: str
    more_information: str
    priority: int
    bouw: list[str]
    tto: bool
    effdt: dt.datetime
    effstatus: bool
    last_saved_by: str
    prio: int
    sync_gid: str
    _errors: list[ImportErrorCode]
    bundle_product_olids: list[str]
    follow_up_product_olid: str
    method_name: str
    method_olid: str
    related_product_olids: list[str]

class ImportSupplier(t.TypedDict, total=False):
    """Generated importer payload for SupplierEd."""
    name: str
    olid: str
    logo_url: str
    status_visions: str
    email_domains: list[str]
    endpoint_type: str
    endpoint_base_url: str | None
    endpoint_publisher: str | None
    gid: str
    effdt: dt.datetime
    effstatus: bool
    last_saved_by: str
    prio: int
    sync_gid: str

class ImportVision(t.TypedDict, total=False):
    """Generated importer payload for VisionEd."""
    olid: str
    onderwijskwaliteit: str
    visie: str
    property_bag: object
    gid: str
    effdt: dt.datetime
    effstatus: bool
    last_saved_by: str
    prio: int
    sync_gid: str
