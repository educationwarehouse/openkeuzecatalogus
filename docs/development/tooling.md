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
- `edwh local.pip-compile-all`
- `edwh local.queue-pgq --entrypoint <entrypoint> --payload '{}'`
- `edwh local.prepare-public --test --files`

`edwh local.pip-bump-all` requires pip-compile plugin 0.7 or newer and explicitly
enables `--generate-hashes` for every upgrade stage. It upgrades shared requirements
first, then service requirements, then development requirements. Other plugin
usages keep hash generation opt-in.

Use `edwh local.pip-compile-all` to update the same requirements files with hashes
without requesting upgrades. It retains existing output pins where compatible with
the input requirements. Changed requirements can still require different versions.
This also requires pip-compile plugin 0.7 or newer.

List project-specific tasks:

- `edwh -l local`

Get help:

- `edwh help <namespace>`
- `edwh help <namespace.command>`
- Example: `edwh help local.queue-pgq`

## Redis memory

Compose configures Redis with `REDIS_MAXMEMORY`, defaulting to `3gb`, below the
5 GiB container limit. The remaining memory provides headroom for replication
buffers, connections and persistence overhead; actual peak usage still needs
monitoring. Set `REDIS_MAXMEMORY` in the deployment environment to tune the limit.

The `noeviction` policy preserves existing keys, including login sessions. At the
limit, Redis rejects writes that need more memory, including session updates.
It does not guarantee uninterrupted logins or prevent every possible OOM kill.
Redis replicas normally ignore `maxmemory` while following their master, so
monitor replica memory too. Recreate the Redis containers to apply these options.

## Linting

`edwh lint` extends the default lint workflow with project-specific checks:

- Ruff import and formatting checks
- `ty` type checks
- `tsc` type checks for TypeScript files
- FIXME marker detection in source comments
- custom EW lint rules from `linting.tasks.py`

`edwh fmt` also formats JavaScript and TypeScript files with Prettier via `bunx`.
When Bun is absent, the formatting and TypeScript checks install it with Bun's official installer.

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
