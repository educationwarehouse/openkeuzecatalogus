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
