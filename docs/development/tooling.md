# Tooling

## Core CLI

The project uses `edwh` for local workflow commands.

Common commands:

- `edwh setup`
- `edwh build`
- `edwh up`
- `edwh down`
- `edwh ps`
- `edwh health`
- `edwh inspect-health <service>`
- `edwh logs -s <service>` (repeat `-s` for multiple services)

## Project-Specific Tasks

Project-specific commands from `tasks.py` are available under `local.*`, for example:

- `edwh local.pip-bump-all`
- `edwh local.queue-pgq --entrypoint <entrypoint> --payload '{}'`
- `edwh local.prepare-public --test --files`

List project-specific tasks:

- `edwh -l local`

Get help:

- `edwh help <namespace>`
- `edwh help <namespace.command>`
- Example: `edwh help local.queue-pgq`

## Linting

`edwh lint` extends the default lint workflow with project-specific checks:

- Ruff import and formatting checks
- `ty` type checks
- FIXME marker detection in source comments
- custom EW lint rules from `linting.tasks.py`

Current custom EW rules:

- `EW001`: avoid `monkeypatch.setattr(...)`; prefer a focused fixture or an explicit test seam instead
- `EW002`: call `.with_injected(...)` rather than `.from_env(...)` directly on an Endow injectable, except inside its own `from_env` factory
- `EW003`: provide every runtime input required by an Endow injectable when calling `.with_injected(...)`

Suppress a specific custom lint violation with a same-line `# noqa: EW001` (or the relevant EW code) only when there is a justified exception.

## Payload Type Generation

Static payload types are generated from runtime model metadata in the `migrate`
container:

- `edwh types.generate-importtypes`: regenerate importer payload types.
- `edwh types.generate-publictypes`: regenerate public catalogue payload types.
- `edwh types.generate`: run both generators.

The commands write generated modules to `shared_code/generated/`. Run the relevant
generator after changing field metadata that affects importer or public payloads, and
commit the regenerated output with the metadata change.

## User & Role Administration

`admin.tasks.py` provides `edwh admin.*` commands for managing users, roles, and feature flags:

- `edwh admin.list-users [--role <role>]`
- `edwh admin.add-user <email> ...`
- `edwh admin.remove-user <email>`
- `edwh admin.set-password <email> [--password <password>]`
- `edwh admin.grant-role <email> <role>`
- `edwh admin.revoke-role <email> <role>`
- `edwh admin.make-admin <email>`
- `edwh admin.featureflag <flag_name> [--disabled]`

List all admin tasks: `edwh -l admin`.
