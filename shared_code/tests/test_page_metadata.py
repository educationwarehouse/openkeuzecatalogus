"""Sharing metadata must describe public pages without exposing private context."""

import pytest

from shared_code.util.page_metadata import page_metadata


@pytest.mark.parametrize("path", ["/private/team/secret-team", "/private/keuzecanvas/secret-process", "/auth/login"])
def test_private_social_metadata_does_not_include_context(path: str) -> None:
    metadata = page_metadata(f"{path}?next=/private/secret-process", title="Vertrouwelijk schoolteam")

    assert "Vertrouwelijk schoolteam" in metadata["title"]
    assert "Vertrouwelijk" not in metadata["social_title"]
    assert "secret" not in metadata["canonical"]
    assert "?" not in metadata["canonical"]
    assert metadata["robots"] == "noindex, nofollow"


def test_public_material_title_is_available_when_sharing() -> None:
    metadata = page_metadata("/product/material-gid?source=similar", title="Rekenen & taal")

    assert metadata["social_title"].startswith("Rekenen & taal | ")
    assert metadata["canonical"] == "https://openkeuzecatalogus.nl/product/material-gid"
    assert metadata["robots"].startswith("index, follow")


def test_catalog_filters_do_not_create_separate_canonical_pages() -> None:
    metadata = page_metadata("/producten?search=taal&page=2")

    assert metadata["canonical"] == "https://openkeuzecatalogus.nl/producten"
    assert metadata["social_title"] == page_metadata("/")["social_title"]


@pytest.mark.parametrize("path", ["/producten", "/methodes", "/private/keuzecanvas", "/auth/login"])
def test_platform_pages_share_one_social_preview(path: str) -> None:
    metadata = page_metadata(path, title="Paginatitel")
    homepage = page_metadata("/")

    assert metadata["social_title"] == homepage["social_title"]
    assert metadata["description"] == homepage["description"]
    assert metadata["image"] == homepage["image"]
