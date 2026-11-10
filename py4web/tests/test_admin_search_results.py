"""Regression coverage for search results whose navigation parent is missing."""

from pathlib import Path

import bs4
import pytest
from apps.admin.models.search_orgs import SearchTableConfig, global_search_configs
from common.models.rendering import render_template
from pydal.objects import Row

TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "apps" / "admin" / "templates"


@pytest.fixture(
    params=[("School", "parent_board"), ("Vestiging", "parent_school"), ("Vakgroep", "location")],
    ids=["school", "location", "team"],
)
def parent_search_config(
    request: pytest.FixtureRequest, admin_app_request_context: None
) -> tuple[SearchTableConfig, str]:
    """Use each real search configuration whose URL needs a parent relationship."""
    label, parent_key = request.param
    config = next(config for config in global_search_configs() if config.label == label)
    return config, parent_key


@pytest.mark.parametrize("parent_state", ["missing", "null", "present"])
def test_search_templates_preserve_results_with_missing_parents(
    parent_search_config: tuple[SearchTableConfig, str], parent_state: str
) -> None:
    """Both search views retain orphaned results and link healthy results correctly."""
    config, parent_key = parent_search_config
    row = Row(gid="result-gid", name="Regression search result")
    if parent_state == "null":
        row[parent_key] = None
    elif parent_state == "present":
        row[parent_key] = {"gid": "parent-gid"}

    config.rows = [row.as_dict()]
    expected_urls = {
        "School": "/admin/board/parent-gid/schools/select?q=result-gid",
        "Vestiging": "/admin/school/parent-gid/locations/select?q=result-gid",
        "Vakgroep": "/admin/location/parent-gid/teams/select?q=result-gid",
    }

    results_html = render_template(
        "search_results.html",
        templates_path=TEMPLATES_PATH,
        page_results=[],
        results={config.label: config},
        total_results=1,
    )
    preview_html = render_template(
        "search_preview.html",
        templates_path=TEMPLATES_PATH,
        page_results=[],
        results=[(config, row)],
        search_term="Regression",
    )

    results = bs4.BeautifulSoup(results_html, "html5lib")
    preview = bs4.BeautifulSoup(preview_html, "html5lib")
    card = results.select_one(".card")
    preview_item = preview.select_one(".list-group-item")
    assert card is not None
    assert preview_item is not None
    assert "Regression search result" in card.get_text()
    assert "Regression search result" in preview_item.get_text()

    if parent_state == "present":
        result_link = card.select_one("a[href]")
        assert result_link is not None
        assert result_link["href"] == expected_urls[config.label]
        assert preview_item.name == "a"
        assert preview_item["href"] == expected_urls[config.label]
    else:
        assert card.select_one("a[href]") is None
        assert preview_item.name == "div"
        assert not preview_item.has_attr("href")

    assert preview.select_one(".admin-search-preview-more a[href]") is not None
