# Database Context Ownership

`TypeDAL` model classes are bound to one database context at a time. A second context that defines the same models can replace that binding; closing it can then leave code still using the first context without defined models.

## Ownership

Create and close a database context only at a composition root:

- a py4web request lifecycle;
- a PGQ job entrypoint;
- a CLI or migration command; or
- a test fixture.

The owner defines the shared tables before handing the context to application code and closes it only after all dependent work has finished.

Modules, services, and helpers receive the existing database context as an explicit dependency. They must not call `database_context()` or create a second `TypeDAL` instance. This keeps one coherent model binding and transaction active throughout an execution.

## Tests

Tests that exercise code which persists data must pass their fixture-owned database context into that code. A test must not open an additional context while a `db_per_file` fixture is active; doing so rebinds the shared TypeDAL models and can break later test cleanup.
