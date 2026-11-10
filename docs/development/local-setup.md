# Local Setup

## Prerequisites

- Docker with Compose support.
- `edwh` installed and available in `PATH`.
- Permission to run `sudo` when `edwh setup` adjusts local ownership/permissions.
  - Tip: you can use `edwh sudo` on your machine once to avoid typing your `sudo` password every time.

### Install and Verify `edwh`

Create and activate a virtual environment, then install this project:

- Server host, for tasks such as `edwh setup` and `edwh up`: `uv pip install .`
- Local development, including all service and test dependencies: `uv pip install .[dev]`

Verify installation:

- `edwh --help` or `edwh -l`

### Reverse Proxy / `broker` Network Requirement

This Compose stack expects the external Docker network `broker` to be managed by the reverse proxy setup.
Do not create this network manually for this project.

Set up the reverse proxy first:

- https://github.com/educationwarehouse/reverse_proxy/

If `broker` is missing, `edwh up` / Compose will fail with a network-not-found error.

## Bootstrap Command

Use `edwh setup` to bootstrap or refresh your local environment configuration.

What it does at a high level:
- Ensures a local `.env` file exists.
- Interactively checks required environment keys and writes missing values.
- Applies sensible defaults based on the selected `STATE_OF_DEVELOPMENT`.
- Updates derived values used by the Docker Compose stack.
- Optionally bootstraps `migrate/data/testing.snapshot` from `TESTING_SNAPSHOT_URL`.
- Optionally configures old-server seed import settings (`MIGRATE_SEED_BASE_URL`, `MIGRATE_SEED_BEARER_TOKEN`).
- Prepares filesystem permissions/directories needed by local services.

`edwh setup` is intended to be re-runnable: run it again whenever environment settings change.

Bootstrap URL behavior:
- `TESTING_SNAPSHOT_URL`:
  - If `migrate/data/testing.snapshot` already exists: no download.
  - If URL is empty and directory is missing: create an empty `migrate/data/testing.snapshot` directory.
  - If URL is set and directory is missing: download via files plugin.
- Seed import env keys:
  - Replaced by `MIGRATE_SEED_BASE_URL` and `MIGRATE_SEED_BEARER_TOKEN`.
  - These are written to `.env` and used by migrate-time JSON seed import.
- Membership-driven access:
  - Supplier access is driven by `supplier_ed.email_domains` and seeded supplier rows.
  - Organisation access is driven by `organisation_ed.email_domains` and organisation RBAC identities.
  - Verified users are matched to suppliers and organisations by email domain during login and email verification.
- You can set these values either by answering prompts in `edwh setup` or by editing `.env` directly.

## Preflight Checklist (First Run)

- Docker daemon is running.
- `edwh` is installed and responds (`edwh --help` or `edwh -l`).
- Reverse proxy environment is set up (providing Docker network `broker`).
- You can run `sudo` for permission updates done by `edwh setup`.

## First-Time Startup Flow

1. Run `edwh setup`.
2. Review/update `.env` values if needed.
3. Start the stack with `edwh up` (which builds images automatically).

## Day-to-Day Flow

- Config or env changed: rerun `edwh setup`.
- Dockerfile/dependency changes: `edwh up` rebuilds images. Use `edwh build` when you also need its explicit pull or requirements compilation workflow.
- Normal start: `edwh up`.
- Normal stop: `edwh down`.

## Verify the Stack

After `edwh up`, verify:

- `edwh ps` shows expected services.
- `edwh health` reports healthy services.
- `edwh inspect-health py4web` and `edwh inspect-health pg-0` confirm service health details.

Useful checks:

- `edwh logs -s migrate`
- `edwh logs -s py4web`
- `edwh logs -s pg-0`

For migration-specific troubleshooting, see [migrations runbook](migrations.md).

## Command Namespaces

This repository’s CLI behavior is defined in `tasks.py` and exposed through the `edwh` task system in two ways:

- Hooked global commands:
  - Some task names are recognized as hook points by `edwh` (for example `setup`, `up`, `fmt`, `lint`).
  - When this project defines one of those task names in `tasks.py`, you can run it directly as `edwh <name>` (for example `edwh setup`).
- Local namespace commands:
  - Tasks that are project-specific (or not mapped to a global hook name) remain available under the local namespace.
  - Run these as `edwh local.<task_name>` (for example `edwh local.pip-bump-all`).

In short: both command forms come from the same `tasks.py`; the difference is whether the task name hooks into a global `edwh` command name or stays project-local under `local.*`.

## See Also

- [Secrets management (`.env` workflow)](US-TOOL-02-secrets.md)
