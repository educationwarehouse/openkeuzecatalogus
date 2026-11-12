"""Browser regressions for the shared shell, history, focus and select controls."""

import re
import uuid

from playwright.sync_api import Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL


def _wait_for_view_transition(page: Page) -> None:
    """Wait until Chromium has finished an optional document transition."""
    page.wait_for_function("!document.activeViewTransition")


def _wait_for_catalog_filters(page: Page) -> None:
    """Wait for the lazy filter response and its interaction handlers."""
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    expect(page.locator("#catalog-filters form[data-catalog-filters-enhanced='true']")).to_be_attached()


def test_catalog_type_switch_preserves_shell_and_renders_one_response(page: Page) -> None:
    """Switch catalogue types inside the existing document shell."""
    page.goto(f"{BASE_URL}/producten")
    expect(page.locator("#product-results h2")).to_be_visible()
    _wait_for_catalog_filters(page)
    page.evaluate("window.catalogHeader = document.querySelector('.okl-site-header')")
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    tabs = page.get_by_role("navigation", name="Type leermiddelen")
    for label, result_id in [("Pakketten", "package-results"), ("Producten", "product-results")]:
        tabs.get_by_role("link", name=label, exact=True).click()
        expect(page.locator(f"#{result_id} h2")).to_be_visible()
        expect(page.locator("main h1")).to_be_focused()
        assert page.evaluate("window.catalogHeader === document.querySelector('.okl-site-header')")
        expect(page.locator(".okl-skeleton")).to_have_count(0)
    assert all("/filters" in url for url in requests if "/htmx/" in url)


def test_catalog_to_landing_anchor_keeps_runtime_and_scrolls(page: Page) -> None:
    """Navigate to landing-page anchors without replacing shared runtime state."""
    page.goto(f"{BASE_URL}/producten")
    page.evaluate("() => { window.navigationRuntime = window.okl_track_save; }")
    page.get_by_text("Over het platform", exact=True).click()
    page.get_by_role("link", name="Over de Open Keuzecatalogus", exact=True).click()
    expect(page).to_have_url(re.compile(r"/#waarom$"))
    expect(page.locator("#okl-page-status")).to_contain_text("Van en voor scholen")
    assert page.evaluate("window.navigationRuntime === window.okl_track_save")
    assert 0 <= page.locator("#waarom").bounding_box()["y"] <= 120


def test_catalog_filter_labels_work_after_browser_back(page: Page) -> None:
    """Keep catalogue filter labels interactive after browser history restores."""
    page.goto(f"{BASE_URL}/producten")
    _wait_for_catalog_filters(page)
    expect(page.locator(".okl-catalog-page")).to_have_attribute("data-okl-history-ready", "true")
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Home", exact=True).click()
    expect(page.locator("main h1")).to_contain_text("Van en voor scholen")
    page.go_back()
    expect(page.locator("#product-results h2")).to_be_visible()
    _wait_for_catalog_filters(page)
    page.locator('label[for="catalog-sort"]').click()
    expect(page.get_by_role("option", name="Alfabetisch (A-Z)", exact=True)).to_be_visible()
    page.get_by_role("option", name="Alfabetisch (A-Z)", exact=True).press("Escape")
    filter_field = page.locator('.okl-filter-field:has(label[for="filter-vk"])')
    expect(filter_field.locator('[data-enhanced-capsule-select="true"]')).to_be_attached()
    field_label = filter_field.locator('label[for="filter-vk"]')
    field_label.click()
    menu = filter_field.locator(".capsule-dropdown-menu.show")
    option = menu.locator("label.dropdown-item").first
    option_input = option.locator("input")
    option_input.press("Space")
    expect(option_input).to_be_checked()
    expect(menu).to_be_visible()


def test_boosted_navigation_keeps_filters_and_focus_after_back(page: Page) -> None:
    """Preserve filters, focus and the document across boosted history navigation."""
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{BASE_URL}/index")
    marker = uuid.uuid4().hex
    page.evaluate("marker => { window.documentMarker = marker; }", marker)

    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
    expect(page.locator("main h1")).to_be_focused()
    assert page.evaluate("window.documentMarker") == marker

    _wait_for_catalog_filters(page)
    sort_button = page.get_by_role("button", name="Sorteren op: Alfabetisch (A-Z)", exact=True)
    sort_button.press("ArrowDown")
    page.get_by_role("option", name="Alfabetisch (A-Z)", exact=True).press("Escape")
    expect(sort_button).to_be_focused()
    expect(sort_button).to_have_attribute("aria-expanded", "false")
    sort_button.click()
    page.get_by_role("option", name="Alfabetisch (Z-A)", exact=True).click()
    expect(page).to_have_url(re.compile(r"sort=name_desc"))
    page.get_by_role("searchbox", name="Zoekterm", exact=True).fill("biologie")
    expect(page).to_have_url(re.compile(r"q=biologie"))

    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Home", exact=True).click()
    expect(page.locator("main h1")).to_contain_text("Van en voor scholen")
    assert page.evaluate("window.documentMarker") == marker
    page.go_back()
    expect(page.get_by_role("searchbox", name="Zoekterm", exact=True)).to_have_value("biologie")
    expect(page.get_by_role("button", name="Sorteren op: Alfabetisch (Z-A)", exact=True)).to_be_visible()
    expect(page.locator("main h1")).to_be_focused()
    assert page.evaluate("window.documentMarker") == marker
    page.go_forward()
    expect(page.locator("main h1")).to_contain_text("Van en voor scholen")
    assert not errors


def test_reduced_motion_skips_view_transitions(page: Page) -> None:
    """Avoid view transitions when the user requests reduced motion."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{BASE_URL}/index")
    page.evaluate("""() => {
        window.transitionCalls = 0;
        const original = document.startViewTransition.bind(document);
        document.startViewTransition = (...args) => {
            window.transitionCalls += 1;
            return original(...args);
        };
    }""")
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
    expect(page.locator("main h1")).to_be_focused()
    assert page.evaluate("window.transitionCalls") == 0


def test_navigation_without_view_transition_support(page: Page) -> None:
    """Keep boosted navigation functional without the View Transition API."""
    page.goto(f"{BASE_URL}/index")
    page.evaluate("document.startViewTransition = undefined")
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
    expect(page.locator("main h1")).to_be_focused()
    expect(page.locator("#okl-page-status")).to_have_text("Pakketten & Producten")


def test_catalog_detail_uses_named_transition_and_preserves_document(page: Page) -> None:
    """Use the cover transition name while keeping the current document."""
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{BASE_URL}/producten")
    expect(page.locator("#product-results h2")).to_be_visible()
    card = page.locator(".catalog-result-item").filter(has=page.locator("img")).first
    expect(card).to_be_visible()
    heading = card.locator("h3 a").inner_text()
    page.evaluate("""() => {
        window.detailDocumentMarker = true;
        window.coverTransitionNames = [];
        const original = document.startViewTransition.bind(document);
        document.startViewTransition = (...args) => {
            window.coverTransitionNames.push(
                document.querySelector('.catalog-result-item img[style*="okl-product-cover"]')?.style.viewTransitionName
            );
            return original(...args);
        };
    }""")
    card.get_by_role("link", name="Bekijk product", exact=True).click()
    expect(page.locator("main h1")).to_have_text(heading)
    expect(page.locator("main h1")).to_be_focused()
    expect(page.locator(".okl-detail-media img")).to_have_css("view-transition-name", "okl-product-cover")
    assert page.evaluate("window.detailDocumentMarker") is True
    assert "okl-product-cover" in page.evaluate("window.coverTransitionNames")
    page.go_back()
    expect(page.locator(".catalog-result-item").first).to_be_visible()
    assert page.evaluate("window.detailDocumentMarker") is True


def test_mobile_menu_and_select_survive_boosted_navigation(page: Page) -> None:
    """Keep mobile menu and select controls usable after boosted navigation."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE_URL}/index")
    page.get_by_role("button", name=re.compile("Menu openen")).click()
    drawer = page.locator("#okl-navigation-drawer")
    expect(drawer).to_be_visible()
    drawer.get_by_role("link", name=re.compile("Catalogus Vind")).click()
    expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
    expect(page.locator("main h1")).to_be_focused()
    assert page.locator("main").evaluate("element => !element.inert")
    _wait_for_catalog_filters(page)
    page.get_by_role("button", name=re.compile("Filters tonen")).click()
    page.get_by_role("button", name="Sorteren op: Alfabetisch (A-Z)", exact=True).click()
    page.get_by_role("option", name="Alfabetisch (Z-A)", exact=True).press("Enter")
    expect(page).to_have_url(re.compile(r"sort=name_desc"))
    page.reload()
    _wait_for_catalog_filters(page)
    page.get_by_role("button", name=re.compile("Filters tonen")).click()
    expect(page.get_by_role("button", name="Sorteren op: Alfabetisch (Z-A)", exact=True)).to_be_visible()
    for width in (320, 390, 768):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.evaluate("""() => ({
            viewport_width: innerWidth,
            scroll_width: document.documentElement.scrollWidth,
            overflowing_elements: Array.from(document.querySelectorAll("body *"))
                .filter($element => $element.getBoundingClientRect().right > innerWidth)
                .slice(0, 15)
                .map($element => ({
                    tag: $element.tagName,
                    class_name: $element.className,
                    right: $element.getBoundingClientRect().right,
                    text: $element.textContent.trim().slice(0, 120),
                })),
        })""")


def test_impersonation_reloads_identity_and_restores_admin(page: Page) -> None:
    """Reload impersonated identity and restore the administrator session."""
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    user_email, _ = _create_verified_user(page, prefix="navigation-user", admin=False)
    admin_email, admin_password = _create_verified_user(page, prefix="navigation-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/admin/users")
    search = page.get_by_role("textbox").first
    search.fill(user_email)
    search.press("Enter")
    row = page.locator(".grid-table tr").filter(has_text=user_email)
    expect(row).to_be_visible()
    page.evaluate("window.identityMarker = true")
    row.get_by_role("button", name="Impersonate", exact=True).click()
    page.wait_for_url("**/index")
    assert page.evaluate("window.identityMarker") is None
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
    _wait_for_view_transition(page)
    account_menu = page.locator("details.okl-navigation__dropdown").filter(
        has=page.locator("summary", has_text="Mijn account (impersonatie)")
    )
    account_menu.locator("summary").click()
    stop_impersonating = account_menu.get_by_role("link", name="Impersonatie stoppen", exact=True)
    expect(stop_impersonating).to_be_visible()
    stop_url = stop_impersonating.get_attribute("href")
    assert stop_url
    page.goto(f"{BASE_URL}{stop_url}")
    expect(page.get_by_role("heading", name="Admin Dashboard", exact=True)).to_be_visible()
    page.get_by_role("link", name="Besturen bekijken", exact=True).click()
    expect(page.locator(".grid-wrapper .grid-table")).to_be_visible()
    expect(page.locator(".grid-footer")).to_have_count(1)
    _wait_for_view_transition(page)
    organisation_link = page.get_by_role("navigation", name="Beheernavigatie").get_by_role("link", name="Organisaties")
    expect(organisation_link).to_have_attribute("aria-current", "page")
    for width in (320, 390, 768):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator(".grid-table-wrapper")).to_have_attribute("tabindex", "0")
    page.set_viewport_size({"width": 1280, "height": 800})
    board_url = page.url
    page.get_by_role("button", name="Zoeken", exact=True).click()
    search_dialog = page.get_by_role("dialog", name="Zoeken", exact=True)
    with page.expect_response(lambda response: response.url.endswith("/admin/search-preview")):
        search_dialog.get_by_role("textbox", name="Zoeken", exact=True).fill("biologie")
    expect(page).to_have_url(board_url)
    search_dialog.press("Escape")
    expect(search_dialog).not_to_be_visible()
    page.goto(f"{BASE_URL}/admin/users")
    expect(page.locator(".grid-wrapper .grid-table")).to_be_visible()
    page.goto(f"{BASE_URL}/admin/errors")
    polling_table = page.locator(".table-responsive[hx-get]")
    expect(polling_table).to_have_count(1)
    for _ in range(2):
        with page.expect_response(
            lambda response: (
                response.url.endswith("/admin/errors") and response.request.headers.get("hx-request") == "true"
            )
        ):
            pass
        expect(polling_table).to_have_count(1)
        expect(page.locator(".admin-table-hint")).to_have_count(1)
    assert not errors


def test_landing_interactions_reinitialize_after_boosted_return(page: Page) -> None:
    """Reinitialize landing interactions after returning through the shared shell."""
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{BASE_URL}/index")
    for _ in range(2):
        page.locator(".okl-rail-btn--next").click()
        expect(page.locator('.okl-slider-dot[aria-current="true"]')).to_have_attribute(
            "aria-label",
            re.compile("carrouselpositie 2 "),
        )
        page.locator(".okl-discussion__marker").first.click()
        dialog = page.locator(".js-okl-source-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator('[data-field="title"]')).not_to_be_empty()
        dialog.get_by_role("button", name="Sluiten", exact=True).click()
        expect(dialog).not_to_be_visible()
        page.locator(".okl-view-switch").click()
        expect(page.locator("#okl-discussion")).to_have_class(re.compile("is-full"))
        page.evaluate('window.scrollTo({top: 0, behavior: "instant"})')
        page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
        expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
        page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Home", exact=True).click()
        expect(page.locator("main h1")).to_contain_text("Van en voor scholen")


def test_compact_catalog_rows_and_comparison_actions(page: Page) -> None:
    """Keep compact rows responsive and comparison actions accessible."""
    page.goto(f"{BASE_URL}/producten?view=list")
    expect(page.locator("#product-results h2")).to_be_visible()
    cards = page.locator(".catalog-result-item")
    for width in (320, 390, 768, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(cards.first).to_have_css("border-radius", "0px")
        assert cards.first.evaluate("""card => {
            const view = card.querySelector('.okl-catalog-card__view').getBoundingClientRect();
            const compare = card.querySelector('.okl-compare-choice').getBoundingClientRect();
            return view.right <= compare.left || view.bottom <= compare.top;
        }""")
    covers = cards.filter(has=page.locator("img"))
    selection = covers if covers.count() >= 2 else cards
    selection.nth(0).get_by_role("checkbox").check()
    selection.nth(1).get_by_role("checkbox").check()
    page.get_by_role("button", name="Vergelijk leermiddelen 2", exact=True).click()
    page.get_by_role("link", name="Vergelijk geselecteerde producten", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Vergelijken")
    external_links = page.locator(".comparison-value .okl-text-action")
    for link in external_links.all():
        expect(link).to_have_css("font-size", "12px")
        expect(link).to_have_attribute("rel", "noopener noreferrer")
    remove = page.locator(".comparison-heading-remove").first
    assert remove.evaluate("""link => {
        const rect = link.getBoundingClientRect();
        return link.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    }""")
    remove.click()
    expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
    expect(page.locator(".catalog-result-item input:checked")).to_have_count(1)
