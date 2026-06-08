# Dependency Rules

These rules keep `shared_code/` easy to test and prevent framework or integration coupling from leaking into business logic.

## Allowed Imports

- `shared_code/modules/*`:
  - may import `shared_code/data_model/*`
  - may import service contracts/clients from `shared_code/services/*`
  - may import module-local `types.py` and helpers
- `shared_code/services/*`:
  - may import third-party integration libraries
  - may import shared typing/utilities
- `shared_code/tests/*`:
  - may import any code under test from `shared_code/*`

## Disallowed Imports

- `shared_code/data_model/*` must not import from `shared_code/modules/*`.
- `shared_code/modules/*` should not import framework delivery code (for example `py4web/apps/*`).
- `shared_code/services/*` should not import feature orchestration from `shared_code/modules/*`.

## Practical Rule of Thumb

- If it describes business flow: place it in `modules`.
- If it defines persistence structure: place it in `data_model`.
- If it talks to external systems (SMTP, storage, remote APIs): place it in `services`.
- If a module needs a side effect, depend on a service contract or adapter boundary rather than embedding integration logic in the module.
