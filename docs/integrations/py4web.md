# py4web Integration

## Overview

`py4web` is the HTTP delivery layer around shared domain logic in `shared_code`.

Runtime wiring:

- `py4web/common/models/backend/backend_base.py` defines `Py4webBackend`.
- `py4web/common/models/backend/__init__.py` injects auth context and initializes `backend`, `db`, and `auth`.
- `shared_code.data_model.define_tables(db)` registers shared tables in the web runtime.

## App Surfaces

The project currently has four routable py4web apps under `py4web/apps/`:

- `apps/_default`: public pages, HTMX endpoints, auth routes.
- `apps/admin`: admin grids and management actions.
- `apps/private`: private app entrypoint.
- `apps/restart`: secret-guarded endpoint that touches the restart flag and exits the process; picked up by `/healthcheck` to trigger a container restart.

`py4web/common` is not an app surface — it lives outside `py4web/apps/` and provides shared fixtures, models, and error rendering used by all four apps above.

## HTML Parser for Editable Pages

We selected the `soup5ever-experimental` tree builder from
[`soup5ever`](https://pypi.org/project/soup5ever/) for the full-page parse in
`ContentEditableV2`. The fixture parses rendered HTML, changes editable
sections, then serializes the entire page.
It therefore needs a parser that repairs malformed markup as a browser would;
otherwise, the round trip can change what visitors see. One relevant case is
formatting left open across elements, which must continue in the next element.

The earlier `html5lib` parser preserved the tested HTML5 structure but was slow.
[`html5_parser`](https://html5-parser.readthedocs.io/en/latest/) was an
intermediate experiment on this branch: it passed the same checks and was much
faster, but required compatible `lxml` and libxml2 builds. Both `soup5ever`
builders, built on [Servo's `html5ever`](https://github.com/servo/html5ever),
passed those checks without that libxml2 compatibility requirement. The
experimental builder was fastest in this run at 18.1 ms, compared with 23.2 ms
for the regular builder. The standard library's `html.parser` and `lxml` missed
some of the checked HTML5 behavior.

In one py4web-container run on a generated page with 1,000 articles, the median of
three parse-only runs was:

| Parser                    | Median parse time | HTML5 checks |
|---------------------------|-------------------|--------------|
| `soup5ever-experimental`  | 18.1 ms           | 5/5          |
| `soup5ever`               | 23.2 ms           | 5/5          |
| `html5_parser`            | 27.5 ms           | 5/5          |
| `html5lib`                | 170.5 ms          | 5/5          |
| `lxml`                    | 57.3 ms           | 2/5          |
| `html.parser`             | 80.6 ms           | 0/5          |

The five checks cover foster parenting, implied `tbody`, paragraph closing,
formatting reconstruction, and option closing. They are a focused sample, not a
full HTML5 conformance suite; timings depend on the input and environment. Repeat
the comparison with `edwh local.bench-html-parsers` and use `--verbose` for details.
Import `soup5ever` before calling
`BeautifulSoup(html, "soup5ever-experimental")` so its tree builder is registered.

## Request Normalization

Public catalogue requests are normalized via `py4web/common/models/request_data.py`:

- `CatalogRequest.from_request(...)` normalizes `page`, `view`, `sort`, and filter payload.
- `parse_form_data_with_bracket_notation(...)` expands form keys like `items[0][name]`.
- Resolved filters are delegated to shared backends (`backend.methods` / `backend.products`).

## Runtime Health

`/healthcheck` in `apps/_default/controllers/internals.py` verifies:

- DB reachability (`SELECT 1`).
- restart-flag freshness (`/shared_cache/restart.flag`).

If restart flag is stale, process exits non-zero so container healthchecks can restart it.

## Flash Alerts

`flash` is the py4web flash fixture exposed by `py4web/apps/_default/fixtures/__init__.py` as `flash = auth.flash`.

Python code can use it in two ways:
- Generic controllers import `flash` from `..fixtures` and call `flash.set("message")` or `flash.set("message", "alert-success")`.
- Auth-specific code uses `AppAuth.flash_error(...)`, `flash_success(...)`, `flash_warning(...)`, or `flash_info(...)`, which delegate to `self.flash.set(...)`.

Rendering flow:
- `py4web/apps/_default/templates/layout.html` reads the flash object from the template globals and emits a `py4web-flash` template element.
- `py4web/apps/_default/assets/js/bootstrap-flash.js` turns that template into a dismissible Bootstrap alert in the top-right corner of the page.
