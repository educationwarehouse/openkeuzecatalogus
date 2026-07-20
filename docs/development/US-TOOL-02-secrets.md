# Secrets Management

## Purpose & Compliance

**Never store hardcoded secrets or credentials in a repository.**
Requirement PvE §7.9 explicitly forbids it, and auditability demands the approach is
*aantoonbaar correct* (demonstrably correct), not just factually correct.

The solution is a two-layer system:

1. **`.env` file**: local, gitignored, holds all environment-specific secrets and configuration.
2. **Runtime-generated secrets**: keys and passwords written to gitignored directories at setup time.

## Where Secrets Live

| Layer | Path | Contents | Created by |
|-------|------|----------|------------|
| Env vars | `.env` (gitignored, never committed) | API keys, passwords, tokens, URIs | `edwh setup` → `edwh.check_env()` |
| File secrets | `shared_keys/jwt.key` (dir gitignored) | 4096-byte hex JWT signing key | `generate_jwt_key()` |
| File secrets | `py4web/password.txt` (gitignored) | py4web dashboard password | `setup_py4web_password()` |

## `.gitignore` Protection

```gitignore
.env
shared_keys/
py4web/password.txt
```

Each of these entries prevents accidental commits. See `.gitignore` at repository root for the full list.

## How `edwh.check_env()` Works

`edwh.check_env()` is the core primitive that populates `.env`. It is provided by the
[edwh](https://pypi.org/project/edwh/) library (MIT license, external).

### Signature

```python
value = edwh.check_env(
    key: str,                # env var name, e.g. "POSTGRES_PASSWORD"
    default: str = "",       # fallback value if not present and user skips prompt
    comment: str = "",       # prompt text shown to the user
    allowed_values: tuple | list | None = None,  # if set, validates input
    force_default: bool = False,  # if True, skip prompt and accept default silently
    prefix: str = "",        # prepended to stored value (used for URL prefixes)
) -> str                     # the resolved value (already written to .env)
```

### Behavior

1. If `key` already exists in `.env`, return its value immediately (no prompt).
2. If `force_default=True` (used when `ACCEPT_DEFAULTS=1` in development), write `default` to `.env` and return it silently.
3. Otherwise, prompt the user with `comment` and the `default`. Input is validated against `allowed_values` if set.
4. If `prefix` is non-empty, it is prepended before writing (e.g. `prefix="https://ntfy.sh/"` + default `"EDWH-DEV-ERROR-hostname"` → stored as `"https://ntfy.sh/EDWH-DEV-ERROR-hostname"`).
5. Return value is the resolved string, and **this return value is what enables variable dependencies**.

### Dependency Chaining via Return Values

Because `check_env` returns the resolved value as a Python string, later calls can reference
earlier values directly. This creates a natural ordering in `tasks.py:setup()` where configured
values from earlier calls are composed into later defaults:

```python
# 1. Capture a value into a Python variable:
postgres_password = edwh.check_env(
    key="POSTGRES_PASSWORD",
    default="password",
    comment="Password for pgpool/postgres to access the backend database",
    force_default=use_default,
)

# 2. Use that variable to construct dependent env var values:
edwh.check_env(
    key="INSIDE_DOCKER_POSTGRES_URI",
    default=f"postgres://{postgres_username}:{postgres_password}@pgpool:5432/{postgres_database}",
    comment="...",
    force_default=use_default,
)
edwh.check_env(
    key="OUTSIDE_DOCKER_POSTGRES_URI",
    default=f"postgres://{postgres_username}:{postgres_password}@127.0.0.1:{pgpool_port}/{postgres_database}",
    comment="...",
    force_default=use_default,
)
edwh.check_env(
    key="INSIDE_DOCKER_PG_DUMP_URI",
    default=f"postgres://{postgres_username}:{postgres_password}@pg-0:5432/{postgres_database}",
    comment="...",
    force_default=use_default,
)
```

This pattern means:

- `POSTGRES_PASSWORD` must be resolved **before** any `*_POSTGRES_URI` variable.
- `POSTGRES_USERNAME` and `POSTGRES_DATABASE` must also be resolved first.
- Similarly, `STATE_OF_DEVELOPMENT` is captured first and used to determine
  `INTERNET_ACCESSIBLE`, `PY4WEB_DEBUG_MODE`, `PY4WEB_REPLICAS`, and whether
  `ACCEPT_DEFAULTS` is offered.
- `hosting_domain` feeds into `DEFAULT_FROM_ADDRESS` and applog ID defaults.
- `smtp_server` (from `setup_smtp`) may be split into `SMTP_SERVER` + `SMTP_PORT`.

## Setup Flow: `tasks.py:setup()` Execution Order

Variables are evaluated in this exact sequence. The order matters because later calls
reference values from earlier ones.

1. **Host identity**: `HOSTINGDOMAIN`, `APPLICATION_NAME`, `PROJECT`
2. **Environment tier**: `STATE_OF_DEVELOPMENT` (ONT \| TEST \| DEMO \| PRD)
   - Controls all subsequent defaults via `StateOfDevelopment`
3. **Network exposure**: `INTERNET_ACCESSIBLE`, `CERTRESOLVER`
   - Production-like tiers default to internet-accessible + Let's Encrypt
4. **Defaults gate** (ONT/TEST only): `ACCEPT_DEFAULTS`
   - When `1`, all subsequent prompts use `force_default=True`
5. **Debug & scaling**: `PY4WEB_DEBUG_MODE`, `PY4WEB_REPLICAS`
   - Dev: debug=1, replicas=1; Production: debug=0, replicas=3
6. **Schema version**: `SCHEMA_VERSION` (auto-computed hash, no prompt)
7. **Subdomain**: `PY4WEB_SUBDOMAIN`
8. **Applog credentials**: `PY4WEB_APPLOG_ID/KEY`, `TOOLS_APPLOG_ID/KEY`
   - IDs use `hosting_domain`; keys are random
9. **Crypto seeds**: `EMAIL_VERIFICATION_SEED`, `DEFAULT_FROM_ADDRESS`
10. **Notifications**: `NTFY_ERROR_URL`, `NTFY_WARNING_URL`, `NTFY_SORT_URL`
    - Defaults use `prefix="https://ntfy.sh/"` + hostname-based channel names
11. **Data services**: `REDIS_PORT`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`,
    `PGPOOL_PORT`, `POSTGRES_DATABASE`, `INSIDE_DOCKER_POSTGRES_URI`,
    `OUTSIDE_DOCKER_POSTGRES_URI`, `INSIDE_DOCKER_PG_DUMP_URI`, `PGSTATS_PORT`
    - Ports use `edwh.tasks.next_value()` to avoid collisions
    - URIs compose earlier values via f-strings
12. **Object storage (Backblaze B2)**: `B2_ATTACHMENTS_BUCKETNAME/KEYID/KEY`,
    `B2_HASH_SALT`
13. **Mailgun**: `MAILGUN_DOMAIN/API_KEY/NEXT_RETRY_DELAY_EXPRESSION/MAX_RETRIES`
14. **Upload retry**: `UPLOAD_MAX_RETRIES`, `UPLOAD_NEXT_RETRY_DELAY_EXPRESSION`
15. **Docker tag**: `DOCKER_TAG`
16. **Misc**: `EDDIE_EMAIL`, `PGQ_WORKERS`
17. **Sub-tasks** (called inline):
    - `setup_migrate_seed(use_default)` - `MIGRATE_SEED_BASE_URL`, `MIGRATE_SEED_BEARER_TOKEN`
    - `setup_testing_snapshot(use_default)` - `TESTING_SNAPSHOT_URL`
    - `setup_py4web_password(use_default)` - generates password, writes to `password.txt` + `.env`
    - `setup_smtp(dotenv_path, sod)` - `SMTP_FAKE`, `SMTP_SERVER/PORT/SENDER/USER/PASSWORD/TLS/SSL`
    - `uptimerobot_autoadd()` - auto-adds monitors via plugin
18. **Permissions & file secrets**: `chown`, `set_permissions`, `generate_jwt_key()`,
    `bundler_build()`

New environment variables may be added as features evolve. The `setup` task is designed to be re-runnable so new keys are prompted on next invocation.

## Default Values by Environment

Set via `tasks.py:StateOfDevelopment` (see [local-setup.md](local-setup.md) for the environment tier concept). Different defaults:

| Variable | ONT/TEST | DEMO/PRD |
|----------|----------|---------------|
| `ACCEPT_DEFAULTS` | offered (default: 1) | not offered |
| `SMTP_FAKE` | 1 | 0 |
| `PY4WEB_DEBUG_MODE` | 1 | 0 |
| `PY4WEB_REPLICAS` | 1 | 3 |
| `INTERNET_ACCESSIBLE` | 0 | 1 |
| `CERTRESOLVER` | default | letsencrypt |

Production-like environments require explicit input for every sensitive variable;
unsafe defaults are never silently accepted.

## How Secrets Reach Containers

The pipeline from `.env` → container:

```
edwh setup
    │
    ▼
.env  (written by check_env / set_env_value)
    │
    ▼
docker-compose.yml  (reads .env automatically via Compose default)
    │  ┌─────────────────────────────────────────┐
    │  │  environment:                            │
    │  │    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}│
    │  │    SMTP_FAKE: ${SMTP_FAKE:-1}            │
    │  │    ...                                    │
    │  └─────────────────────────────────────────┘
    │
    ▼
Container runtime  (os.environ has all declared vars)
```

- Docker Compose reads `.env` from the project directory automatically.
- `environment:` blocks in `docker-compose.yml` reference `${VAR}` or `${VAR:-default}`.
- The `*shared_environment` YAML anchor is reused across `migrate`, `py4web`, `pgq-*`, and `playwright` services, so every service gets all configured env vars.
- `SERVICE_NAME` is set per Compose service so applog events can attribute work to `migrate`, `py4web`, `pgq-scrapers`, `pgq-applog`, or `playwright` instead of relying on the container hostname.

### Troubleshooting Variable Interpolation

Run `docker compose config` to see the resolved Compose file with all `${VAR}` substitutions applied. This is useful when you suspect a value isn't reaching a container.

To inspect the environment inside a running container:

```bash
docker compose exec <service> env
# or for a specific var:
docker compose exec <service> printenv <VAR_NAME>
```

## Onboarding Checklist

Before starting, complete the generic prerequisites in [local-setup.md](local-setup.md#prerequisites) (Docker, edwh install, reverse proxy / broker network).

Secrets-specific steps:

- [ ] Run `edwh setup` to interactively fill `.env` with values for this environment.
- [ ] Verify `.env` is listed in `.gitignore` and no uncommitted `.env` shows in `git status`.
- [ ] Store a backup of `.env` in a secure location (e.g. team password manager) for disaster recovery.

## Acceptance Criteria (Auditability)

For auditors and reviewers, these criteria must all be met:

- [ ] `.env` appears in `.gitignore` and is absent from all commits (`git log --all --full-history -- .env` returns nothing).
- [ ] No hardcoded credentials, API keys, or passwords exist in any committed source file, Compose file, or documentation.
- [ ] `shared_keys/`, `shared_cache/`, `shared_applog/`, `shared_user_storage/`, and `py4web/password.txt` are all gitignored.
- [ ] A new team member can reproduce a working environment by following the [onboarding checklist](#onboarding-checklist) above without access to any prior `.env` snapshot.
- [ ] `edwh setup` is re-runnable: running it again does not overwrite existing values unless the user explicitly provides new input.
- [ ] Production-like environments (`STATE_OF_DEVELOPMENT` = DEMO, PRD) require explicit value entry; unsafe defaults are not silently accepted.
