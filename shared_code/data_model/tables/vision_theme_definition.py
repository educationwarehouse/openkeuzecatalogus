"""Effective-dated definitions for the fixed vision-theme set."""

from typedal.fields import TextField, TypedField
from typedal.helpers import classproperty

from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import EffdtTable


class VisionThemeDefinitionEd(EffdtTable):
    """Editable source record for one stable vision-theme GID."""

    title = TypedField(str, length=255, label="Titel")
    description = TextField(label="Toelichting")
    info_url = TypedField(str, length=2048, label="Informatie URL")
    sort_order = TypedField(int, label="Sortering", default=0)


class VisionThemeDefinition(
    VisionThemeDefinitionEd,
    SearchMixin,
    search_fields=("title", "description", "info_url"),
):
    """Current editable vision-theme definitions."""

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for vision-theme definitions."""
        return "vision-theme-definitions"
