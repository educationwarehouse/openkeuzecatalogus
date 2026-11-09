"""Read-only location product-usage reporting view."""

from typedal.fields import TypedField

from shared_code.data_model.fields import OptionalUUIDField, UUIDReferenceField
from shared_code.data_model.representers import comma_separated
from shared_code.data_model.tables.base import TableWithGid


class LocationProductUsageReport(TableWithGid):
    """One product aggregated from the decision processes at one location."""

    location_gid = UUIDReferenceField(label="Vestiging")
    product_name = TypedField(str, length=255, label="Product")
    product_olid = TypedField(str | None, length=255, label="OLID")
    material_types = TypedField(list[str], label="Soorten materiaal", represent=comma_separated)
    team_gids = TypedField(list[str], label="Vakgroep-ID's")
    team_names = TypedField(list[str], label="Vakgroepen", represent=comma_separated)
    process_gids = TypedField(list[str], label="Proces-ID's")
    schoolyears = TypedField(list[str], label="Schooljaren", represent=comma_separated)
    process_stages = TypedField(list[str], label="Procesfasen", represent=comma_separated)
    active_process_count = TypedField(int, label="Actieve processen")
    archived_process_count = TypedField(int, label="Gearchiveerde processen")
    process_count = TypedField(int, label="Aantal processen")
    catalog_gid = OptionalUUIDField(label="Catalogus-ID")
    catalog_origin = TypedField(str | None, length=10, label="Catalogusherkomst")
