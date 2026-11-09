"""Discover catalogue controls and links from the public HTML responses."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

DETAIL_PATH = re.compile(r"^/(?:methode|product)/[0-9a-f-]{36}/?$", re.IGNORECASE)
RESULT_COUNT = re.compile(r"([0-9][0-9.]*)\s+resulta(?:at|ten)", re.IGNORECASE)
PAGE_ACTION = re.compile(r"ew:change_page\(page:\s*(\d+)\)")


def local_path(value: str, base_url: str) -> str | None:
    """Resolve only HTTP resources on the target origin."""
    target = urlsplit(urljoin(base_url, value))
    base = urlsplit(base_url)
    if target.scheme not in {"http", "https"} or (target.scheme, target.netloc) != (base.scheme, base.netloc):
        return None
    return target.path + (f"?{target.query}" if target.query else "")


class CatalogueHTML(HTMLParser):
    """Extract actual filter values, details, pagination and initial assets."""

    def __init__(self, html: str, base_url: str) -> None:
        """Parse one response without relying on configured filter slugs."""
        super().__init__()
        self.base_url = base_url
        self.controls: dict[str, list[str]] = {}
        self.multi_selects: set[str] = set()
        self.windowed: list[str] = []
        self.option_values: list[str] = []
        self.next_options: str | None = None
        self.details: list[str] = []
        self.pages: set[int] = set()
        self.assets: dict[str, str] = {}
        self.select_name = ""
        self.in_filters = False
        self.result_count: int | None = None
        if match := RESULT_COUNT.search(html):
            self.result_count = int(match.group(1).replace(".", ""))
        self.feed(html)

    def _detail_link(self, href: str) -> None:
        """Collect a distinct catalogue detail link on the target origin."""
        path = local_path(href, self.base_url)
        if path and DETAIL_PATH.fullmatch(path) and path not in self.details:
            self.details.append(path)

    def _filter_context(self, tag: str, values: dict[str, str | None]) -> None:
        """Track the active filter form and its current select control."""
        if tag == "form":
            self.in_filters = values.get("id") == "catalog-filter-controls"
        if tag == "select" and self.in_filters:
            self.select_name = values.get("name") or ""
        if slug := values.get("data-option-slug"):
            self.windowed.append(slug)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect controls and resource references from a start tag."""
        values = dict(attrs)
        self._filter_context(tag, values)
        if tag == "input":
            self._input(values)
        elif tag == "option" and self.select_name and (value := values.get("value")):
            self.controls.setdefault(self.select_name, []).append(value)
        elif tag == "a" and (href := values.get("href")):
            self._detail_link(href)
        elif tag == "button" and (match := PAGE_ACTION.search(values.get("_") or "")):
            self.pages.add(int(match.group(1)))
        if "catalog-option-more" in (values.get("class") or "").split():
            self.next_options = local_path(values.get("hx-get") or "", self.base_url)
        self._asset(tag, values)

    def _input(self, values: dict[str, str | None]) -> None:
        """Record selectable values, including unnamed option-page inputs."""
        if values.get("type") not in {"checkbox", "radio"}:
            return
        value = values.get("value") or "on"
        self.option_values.append(value)
        if self.in_filters and (name := values.get("name")):
            self.controls.setdefault(name, []).append(value)
            if values.get("type") == "checkbox":
                self.multi_selects.add(name)

    def _asset(self, tag: str, values: dict[str, str | None]) -> None:
        """Keep scripts, stylesheets and a bounded set of same-origin images."""
        resource = None
        if tag == "script":
            resource = values.get("src")
        elif tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            resource = values.get("href")
        elif tag == "img" and sum(kind == "img" for kind in self.assets.values()) < 8:
            resource = values.get("src")
        if resource and (path := local_path(resource, self.base_url)):
            self.assets[path] = tag

    def handle_endtag(self, tag: str) -> None:
        """End the current form or select context."""
        if tag == "form":
            self.in_filters = False
        elif tag == "select":
            self.select_name = ""
