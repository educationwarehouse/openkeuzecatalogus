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

Suppress a specific custom lint violation with a same-line `# noqa: EW001` when you have a justified exception.

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
