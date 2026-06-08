# Shared Code Architecture

This project is organized around a framework-light core under `shared_code/`.
The goal is to keep business logic reusable, easy to test, and minimally coupled to delivery frameworks (for example `py4web` in an interface layer outside this core).

## Ideology

- Keep framework-specific concerns at the edge.
- Put most behavior in `shared_code` so it can be tested directly.
- Separate business flows, persistence models, and external integrations.
- Prefer explicit contracts for side-effecting services (mail, storage, APIs) so tests can replace real implementations with fakes/mocks.

## High-Level Split

```text
shared_code/
  modules/
    products/
      __init__.py
      module.py
      types.py
  data_model/
    __init__.py
    product.py
  services/
    mail/
      contracts.py
      smtp.py
      fake.py
    storage/
    payment_api/
    lms_api/
  migrations/
    products.py
    users.py
  tests/
    test_products.py
    test_product_model.py
    test_mail.py
```

## Layer Responsibilities

### `modules/`
Feature-oriented business flows (use-cases/orchestration) and feature-local types.
- `module.py`: orchestration logic for a module/feature.
- `types.py`: module-level typed structures/contracts.

### `data_model/`
ORM-backed data model definitions.
- Contains model classes used by the application core.
- Keeps persistence model code grouped and discoverable.

### `services/`
External or side-effecting capabilities (mail, storage, remote APIs).
- Keep contracts explicit (`contracts.py`) where practical.
- Put real adapters in implementation files (e.g. `smtp.py`).
- Provide test doubles/fakes (e.g. `fake.py`) for deterministic tests.

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
- `tests/*` can import any shared core package under test.

## Placeholder Note

Current concrete names like `products`, `payment_api`, and `lms_api` are placeholders to demonstrate structure only.
They do **not** represent final product domains. Replace them with actual bounded-context names when the real domain model is introduced.

## Architecture Docs

- [Compose runtime overview](architecture/overview.md)
- [Dependency rules](architecture/dependency-rules.md)
- [Effective-dated `_ed` and `_model` tables](architecture/effective-dated-models.md)

## Development Docs

- [Local setup (`edwh setup` / `edwh build` / `edwh up`)](development/local-setup.md)
- [Migrations (`edwh migrate`) runbook](development/migrations.md)
- [Tooling and commands](development/tooling.md)
- [Testing](development/testing.md)
- [Public release mirroring](development/public-release-mirroring.md)

## Integration Docs

- [py4web](integrations/py4web.md)
- [Mail](integrations/mail.md)
- [Applog](integrations/applog.md)
- [Auth](integrations/auth.md)
- [Storage](integrations/storage.md)
