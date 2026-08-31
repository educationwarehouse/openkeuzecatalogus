# Shared Code Architecture

This project is organized around a framework-light core under `shared_code/`.
The goal is to keep business logic reusable, easy to test, and minimally coupled to delivery frameworks (for example `py4web` in an interface layer outside this core).

## Ideology

- Keep framework-specific concerns at the edge.
- Put most behavior in `shared_code` so it can be tested directly.
- Separate business flows, persistence models, and external integrations.
- Prefer explicit contracts for side-effecting services (mail, storage, APIs) so tests can replace real implementations with fakes/mocks.

## High-Level Split

Each top-level area below should be a package directory, not a single flat module file. Concretely, `modules/`, `data_model/`, `services/`, `infra/`, and `util/` should contain subdirectories with `__init__.py` entrypoints where the code is grouped by concern.

```text
shared_code/
  modules/
    auth/
      __init__.py
      password_reset.py
  data_model/
    __init__.py
    tables/
      auth_user.py
      product.py
  services/
    mail/
      contracts.py
      smtp.py
      fake.py
    applog/
    entree/
  migrations/
    migrations.py
  tests/
    test_password_reset.py
    test_service_helpers.py
  infra/
    database/
    error_tickets/
    web/
  util/
    env/
    time/
    class_utils/
```

## Layer Responsibilities

### `modules/`
Feature-oriented business flows (use-cases/orchestration) and feature-local types.
- Use package directories per feature or bounded context.
- `module.py`: orchestration logic for a module/feature.
- `types.py`: module-level typed structures/contracts.

### `data_model/`
ORM-backed data model definitions.
- Use package directories per table family, mixin family, or related model set.
- Contains model classes used by the application core.
- Keeps persistence model code grouped and discoverable.

### `services/`
External or side-effecting capabilities (mail, applog, remote APIs).
- Use package directories per service family or adapter boundary.
- Keep contracts explicit (`contracts.py`) where practical.
- Put real adapters in implementation files (e.g. `smtp.py`).
- Provide test doubles/fakes (e.g. `fake.py`) for deterministic tests.

### `infra/`
Runtime glue, database wiring, framework-adjacent helpers, and file-backed persistence.
- Use package directories per runtime concern.
- Keep application/bootstrap code here when it is not a business flow or external adapter.

### `util/`
Pure helpers with no I/O or side effects.
- Use package directories for grouped utility families when a helper set is more than one file.
- Keep stateless helper functions here.

### `migrations/`
Schema/data migration units grouped by concern.

### `tests/`
Automated tests for modules, data models, and services.
- Includes unit tests for business logic.
- Includes tests for integration boundaries with fakes/mocks.

## Dependency Direction (Guideline)

- `modules/*` may depend on `data_model` and service contracts.
- `data_model` should not depend on feature modules.
- `services/*` provide integrations used by module wiring.
- `infra/*` may depend on `services/*` and `data_model/*` when it is runtime glue.
- `util/*` should remain pure and side-effect free.
- `tests/*` can import any shared core package under test.

## Placeholder Note

Current concrete names like `products`, `payment_api`, and `lms_api` are placeholders to demonstrate structure only.
They do **not** represent final product domains. Replace them with actual bounded-context names when the real domain model is introduced.

## Architecture Docs

- [Compose runtime overview](architecture/overview.md)
- [Dependency rules](architecture/dependency-rules.md)
- [Auth and RBAC](architecture/auth-rbac.md)
- [Catalogue filtering](architecture/catalog-filters.md)
- [Scraper import architecture](architecture/scraper-imports.md)
- [Effective-dated `_ed` and `_model` tables](architecture/effective-dated-models.md)
- [OLID identifiers](architecture/olid.md)
- [Supplier memberships and access control](architecture/supplier-memberships.md)
- [Queue processing (`pgq/`)](architecture/queue-processing.md)
- [Database context ownership](architecture/database-contexts.md)

## Development Docs

- [Local setup (`edwh setup` / `edwh build` / `edwh up`)](development/local-setup.md)
- [Database](development/database.md)
- [Migrations (`edwh migrate`) runbook](development/migrations.md)
- [Tooling and commands](development/tooling.md)
- [Testing](development/testing.md)
- [Secrets management](development/US-TOOL-02-secrets.md)
- [Public release mirroring](development/public-release-mirroring.md)

## Integration Docs

- [py4web](integrations/py4web.md)
- [Mail](integrations/mail.md)
- [Applog](integrations/applog.md)
- [Auth](integrations/auth.md)
- [Storage](integrations/storage.md)
