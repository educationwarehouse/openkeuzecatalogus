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
