"""Generated public catalogue payload types. Do not edit manually."""

import datetime as dt
import typing as t

class PublicMethod(t.TypedDict, total=False):
    """Generated public payload for Method."""
    name: str
    guide_price: float
    sample_copies: str
    preview_digital_environment: str
    olid: str
    supplier_gid: str
    levels: list[str]
    subjects: list[str]
    image_url: str
    description: str
    available: str
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
    gid: str

class PublicProduct(t.TypedDict, total=False):
    """Generated public payload for Product."""
    isbn: str
    name: str
    method_gid: str
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
    olid: str
    supplier_gid: str
    levels: list[str]
    subjects: list[str]
    image_url: str
    description: str
    available: str
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
    gid: str

class PublicSupplier(t.TypedDict, total=False):
    """Generated public payload for Supplier."""
    name: str
    olid: str
    logo_url: str
    status_visions: str
    gid: str
