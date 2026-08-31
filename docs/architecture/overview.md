# Overview

This repository uses Docker Compose to run the web app, background workers, and core data services around the shared Python code in `shared_code/`.

## Service Groups

- Application/runtime:
  - `migrate`: one-shot migration/bootstrap job.
  - `py4web`: web runtime.
- Async workers:
  - `pgq-scrapers`: queue consumer for scraper jobs.
  - `pgq-applog`: queue consumer for applog jobs.
- Data services:
  - `pg-0`: PostgreSQL database.
  - `redis-master`: primary Redis.
  - `redis-slave`: Redis replica of `redis-master`.

## Runtime Entrypoint Map

- `migrate` service
  - Entrypoint: `command: migrate`
  - Responsibility: run registered migrations from `shared_code/migrations/migrations.py`.
- `py4web` service
  - Entrypoint: `python3 py4web_bjoern.py`
  - Responsibility: serve web routes (`apps/_default`, `apps/admin`, `apps/private`) and wire shared backends via `common/models/backend`.
- `pgq-scrapers` service
  - Entrypoint: `pgq run pgq.consumers.scrapers:main --batch-size 1`
  - Responsibility: process scraper import jobs (`start_importer_edu-v`).
- `pgq-applog` service
  - Entrypoint: `pgq run pgq.consumers.applog:main --batch-size 5`
  - Responsibility: process queued email and applog deque schedules.
- `playwright` service
  - Responsibility: run browser tests against the running `py4web` service.

## Network Topology

- `backend` (`${PROJECT}_backend`): internal service-to-service network.
- `broker`: external pre-existing network attached to `py4web` for proxy/edge integration; provided by the reverse proxy environment (see local setup prerequisites).

## Startup and Dependency Flow

1. `pg-0` and `redis-master` come up first.
2. `migrate` runs after those dependencies are available.
3. `py4web` starts only after:
   - `pg-0` healthcheck succeeds, and
   - `migrate` has completed successfully.
4. `pgq-scrapers` and `pgq-applog` follow the same dependency pattern as `py4web`.
5. `redis-slave` starts after `redis-master` and replicates from it.

## State and Persistence Boundaries

- Persistent database state:
  - `postgres_data` named volume for PostgreSQL.
- Shared bind-mounted state:
  - `./shared_code` mounted read-only in runtime containers.
  - `./shared_cache`, `./shared_applog`, `./shared_keys`.
  - `./shared_user_storage` (mounted by `py4web`).
  - `./migrate/flags` (migration/runtime coordination).

## Scaling Model

- `py4web` replicas via `PY4WEB_REPLICAS` (default `3`).
- `pgq-scrapers` replicas via `PGQ_WORKERS` (default `3`).
- `pgq-applog` runs with one replica.
