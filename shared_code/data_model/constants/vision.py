"""Database-backed lookup helpers for fixed vision-theme definitions."""

import typing as t


class VisionThemeMetadata(t.TypedDict):
    """Display metadata for one current vision-theme definition."""

    title: str
    info_link: str
    info_note: str


def themes_metadata() -> dict[str, VisionThemeMetadata]:
    """Return current admin-managed metadata keyed by stable vision-theme GID."""
    from shared_code.data_model import VisionThemeDefinition

    rows = VisionThemeDefinition.select(
        VisionThemeDefinition.gid,
        VisionThemeDefinition.title,
        VisionThemeDefinition.info_url,
        VisionThemeDefinition.description,
        orderby=(VisionThemeDefinition.sort_order, VisionThemeDefinition.id),
    )
    return {
        row.gid: VisionThemeMetadata(
            title=row.title,
            info_link=row.info_url,
            info_note=row.description,
        )
        for row in rows
    }


def get_themes() -> dict[str, str]:
    """Return current vision-theme titles keyed by stable GID."""
    from shared_code.data_model import VisionThemeDefinition

    rows = VisionThemeDefinition.select(
        VisionThemeDefinition.gid,
        VisionThemeDefinition.title,
        orderby=(VisionThemeDefinition.sort_order, VisionThemeDefinition.id),
    )
    return {row.gid: row.title for row in rows}
