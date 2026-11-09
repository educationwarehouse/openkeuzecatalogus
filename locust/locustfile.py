"""Public journeys adapted from openkeuzecatalogus-load-tests, branch hugo.

Use the current HTMX routes and discover filter values from the target's HTML.
"""

import secrets

from catalogue import CatalogueHTML

from locust import HttpUser, between, task

CATALOGUES = {"methods": "/methodes", "products": "/producten"}
SEARCH_TERMS = ("rekenen", "biologie", "Nederlands", "wiskunde", "Engels", "geschiedenis", "boek")


class PublicCatalogueUser(HttpUser):
    """Browse, search, filter, paginate, inspect and compare public records."""

    wait_time = between(1, 5)

    def on_start(self) -> None:
        """Give each simulated visitor its own discovered records and asset cache."""
        self.discovered: dict[str, list[str]] = {kind: [] for kind in CATALOGUES}
        self.asset_cache: set[str] = set()

    def get_html(
        self,
        path: str,
        name: str,
        params: dict[str, str | list[str]] | None = None,
        expected: str = "page",
    ) -> CatalogueHTML | None:
        """Reject redirects, errors and malformed successful catalogue responses."""
        headers = {"HX-Request": "true"} if path.startswith("/htmx/") else {}
        with self.client.get(
            path,
            name=name,
            params=params,
            headers=headers,
            allow_redirects=False,
            catch_response=True,
            timeout=30,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Expected HTTP 200, got {response.status_code}")
                return None
            parsed = CatalogueHTML(response.text, response.url)
            if expected == "results" and parsed.result_count is None:
                response.failure("Catalogue result count is missing")
                return None
            elif expected == "filters" and not parsed.controls:
                response.failure("Catalogue filter controls are missing")
                return None
            elif expected == "page" and "</html>" not in response.text.lower():
                response.failure("Expected a complete HTML page")
                return None
        self.load_assets(parsed)
        return parsed

    def load_assets(self, parsed: CatalogueHTML) -> None:
        """Load initial same-origin assets once per visitor, retrying failures."""
        for path, kind in parsed.assets.items():
            if path in self.asset_cache:
                continue
            with self.client.get(path, name=f"asset/{kind}", catch_response=True, timeout=30) as response:
                if response.status_code == 200:
                    self.asset_cache.add(path)
                else:
                    response.failure(f"Expected asset HTTP 200, got {response.status_code}")

    def open_catalogue(self, kind: str) -> CatalogueHTML | None:
        """Request the overview and the filter fragment loaded by HTMX."""
        page = self.get_html(CATALOGUES[kind], f"{kind}/overview", expected="results")
        if page is None:
            return None
        self.remember(kind, page)
        return self.get_html(f"/htmx/{kind}/filters", f"{kind}/filters", expected="filters")

    def remember(self, kind: str, parsed: CatalogueHTML) -> None:
        """Keep a bounded collection of real detail links for follow-up requests."""
        prefix = "/methode/" if kind == "methods" else "/product/"
        paths = [path for path in parsed.details if path.startswith(prefix)]
        self.discovered[kind] = list(dict.fromkeys([*self.discovered[kind], *paths]))[-100:]

    def results(self, kind: str, params: dict[str, str | list[str]], action: str) -> CatalogueHTML | None:
        """Request filtered results using the same GET endpoint as the browser."""
        parsed = self.get_html(f"/htmx/{kind}/results", f"{kind}/{action}", params=params, expected="results")
        if parsed is not None:
            self.remember(kind, parsed)
        return parsed

    @task(5)
    def browse(self) -> None:
        """Browse general pages or a catalogue with its initial filter request."""
        page = secrets.choice(("/", "/index", "/faq", "methods", "products"))
        if page in CATALOGUES:
            self.open_catalogue(page)
        else:
            self.get_html(page, f"browse{page}")

    @task(5)
    def search(self) -> None:
        """Search likely hits and intentional misses, then browse actual pages."""
        kind = secrets.choice(tuple(CATALOGUES))
        if self.open_catalogue(kind) is None:
            return
        query = secrets.choice(SEARCH_TERMS)
        if secrets.randbelow(4) == 0:
            query = f"loadtest-{secrets.token_hex(8)}"
        params: dict[str, str | list[str]] = {"q": query, "page": "1", "view": "list"}
        parsed = self.results(kind, params, "search")
        if parsed is None:
            return
        if parsed.result_count == 0:
            self.results(kind, {"page": "1"}, "clear-search")
        else:
            self.paginate(kind, params, parsed)
            self.detail(kind)

    @task(3)
    def filter_catalogue(self) -> None:
        """Discover valid filters, load large option lists, and apply selections."""
        kind = secrets.choice(tuple(CATALOGUES))
        filters = self.open_catalogue(kind)
        if filters is None:
            return
        params: dict[str, str | list[str]] = {"page": "1", "view": secrets.choice(("list", "grid"))}
        if sorts := filters.controls.get("sort"):
            params["sort"] = secrets.choice(sorts)
        candidates = [slug for slug in filters.controls if slug != "sort"]
        for _ in range(min(len(candidates), 1 + secrets.randbelow(3))):
            slug = candidates.pop(secrets.randbelow(len(candidates)))
            options = filters.controls[slug]
            if slug in filters.windowed:
                discovered = self.filter_options(kind, slug, options)
                if discovered:
                    options = discovered
            count = min(len(options), 1 + secrets.randbelow(2))
            # A radio control must receive one value; repeated values exercise multi-selects.
            params[slug] = secrets.choice(options)
            if count > 1 and slug in filters.multi_selects:
                params[slug] = list(dict.fromkeys(secrets.choice(options) for _ in range(count)))
        parsed = self.results(kind, params, "filtered-results")
        if parsed is not None:
            self.paginate(kind, params, parsed)
        self.results(kind, {"page": "1", "view": "list"}, "clear-filters")

    def filter_options(self, kind: str, slug: str, initial: list[str]) -> list[str]:
        """Exercise option search and one follow-up page for windowed filters."""
        entity = "method" if kind == "methods" else "product"
        path = f"/htmx/filter-options/{entity}/{slug}"
        query = secrets.choice(("", secrets.choice(initial)[:3]))
        params: dict[str, str | list[str]] = {"q": query, "offset": "0", "limit": "100"}
        parsed = self.get_html(path, f"{kind}/filter-options/search", params=params, expected="options")
        if parsed is None:
            return []
        options = parsed.option_values
        if parsed.next_options:
            more = self.get_html(parsed.next_options, f"{kind}/filter-options/page", expected="options")
            if more is not None:
                options.extend(more.option_values)
        return options

    def paginate(self, kind: str, params: dict[str, str | list[str]], parsed: CatalogueHTML) -> None:
        """Follow up to three real next pages, preserving search and filter state."""
        current_page = 1
        for _ in range(3):
            pages = [page for page in parsed.pages if page > current_page]
            if not pages:
                return
            current_page = min(pages)
            params = {**params, "page": str(current_page)}
            self.wait()
            next_page = self.results(kind, params, "pagination")
            if next_page is None:
                return
            parsed = next_page

    def detail(self, kind: str) -> None:
        """Open a record discovered in a successful catalogue response."""
        if paths := self.discovered[kind]:
            self.get_html(secrets.choice(paths), f"{kind}/detail")

    @task(2)
    def revisit_detail(self) -> None:
        """Return to a previously found record, discovering records if needed."""
        kind = secrets.choice(tuple(CATALOGUES))
        if not self.discovered[kind]:
            self.open_catalogue(kind)
        self.detail(kind)

    @task(1)
    def compare(self) -> None:
        """Compare two distinct IDs obtained from the current target's data."""
        kind = secrets.choice(tuple(CATALOGUES))
        if len(self.discovered[kind]) < 2:
            self.open_catalogue(kind)
        paths = self.discovered[kind]
        if len(paths) < 2:
            return
        first = secrets.choice(paths)
        second = secrets.choice([path for path in paths if path != first])
        entity = "method" if kind == "methods" else "product"
        identifiers = "/".join(path.rstrip("/").rsplit("/", 1)[-1] for path in (first, second))
        self.get_html(f"/compare/{entity}/{identifiers}", f"{kind}/compare")
