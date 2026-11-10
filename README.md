# Open Keuze Catalogus

## Quick start

Requires Python 3.14, `uv`, Docker Compose, and the reverse proxy's `broker` network. See [local setup](docs/development/local-setup.md) for prerequisites.

```sh
git clone git@github.com:educationwarehouse/onzeleermiddelen-private.git
cd onzeleermiddelen-private
uv venv --python 3.14 venv
. ./venv/bin/activate
uv pip install '.[dev]'  # use '.' on PRD
edwh setup
edwh up
edwh health
```

For development, answer `ONT` for `STATE_OF_DEVELOPMENT` and `1` for `ACCEPT_DEFAULTS`. For production, answer `PRD` and supply the real domain, credentials, and service settings. Key choices:

- `MIGRATE_SEED_BASE_URL`: clear it in `.env` for a standalone development environment; keep it only with access to the old-server seed endpoint.
- `IMAGE_STORAGE_FAKE=1` stores image uploads locally; use `0` and configure the `IMAGE_STORAGE_*` bucket keys for real storage.
- `SMTP_FAKE=1` keeps mail local; use `0` and provide `SMTP_*` connection details for real mail.
- `ENTREE_CLIENT_ID` and `ENTREE_CLIENT_SECRET` can stay empty locally; supply real credentials to enable Entree login. Set `ENTREE_FAKE=1` in `.env` to exercise the fake login locally.

`edwh setup` creates the gitignored `.env` and prompts for missing values. Edit existing values there, then rerun `edwh setup` after changes.

See [docs](docs/README.md) for further details.
