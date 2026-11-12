# Dependency Rules

These rules keep `shared_code/` easy to test and prevent framework or integration coupling from leaking into business logic.

## Allowed Imports

- `shared_code/modules/*`:
    - may import `shared_code/data_model/*`
    - may import service contracts/clients from `shared_code/services/*`
    - may import runtime glue and policy helpers from `shared_code/infra/*`
    - may import pure helpers from `shared_code/util/*`
    - may import module-local `types.py` and helpers
- `shared_code/data_model/*`:
    - may import shared contracts needed for table hooks and record operators
    - should avoid importing feature workflows or delivery code
- `shared_code/services/*`:
    - may import third-party integration libraries
    - may import shared typing/utilities
- `shared_code/infra/*`:
    - may import `shared_code/data_model/*`, `shared_code/services/*`, and `shared_code/util/*`
- `shared_code/tests/*`:
    - may import any code under test from `shared_code/*`

## Disallowed Imports

- `shared_code/data_model/*` must not import feature workflows from `shared_code/modules/*`.
- `shared_code/modules/*` should not import framework delivery code (for example `py4web/apps/*`).
- `shared_code/services/*` should not import feature orchestration from `shared_code/modules/*`.
- `shared_code/util/*` should remain pure and side-effect free.

## Practical Rule of Thumb

- If it describes business flow: place it in `modules`.
- If it defines persistence structure: place it in `data_model`.
- If it talks to external systems (SMTP, storage, remote APIs): place it in `services`.
- If it is runtime wiring, app bootstrap, or persistence-adjacent glue: place it in `infra`.
- If it is a pure helper without I/O: place it in `util`.
- If a module needs a side effect, depend on a service contract or adapter boundary rather than embedding integration logic in the module.
