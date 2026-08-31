# Storage Integration

## Runtime Paths

Shared storage is provided through bind mounts in Compose:

- `./shared_user_storage` -> `/shared_user_storage` (mounted in `py4web`)
- `./shared_cache` -> `/shared_cache` (shared by migrate/py4web/pgq/playwright)
- `./shared_applog` -> `/shared_applog` (shared applog queue directory)

## What Uses These Paths

- `/shared_user_storage` is mounted into `py4web` but no code currently reads or writes through it (provisioned, not yet used).
- The mock image-storage service writes images under `/shared_cache/image_uploads` and returns `file://` URLs pointing at the stored path.
- applog processing writes queued log signals under `/shared_applog`.
- runtime coordination and cache/state files live under `/shared_cache` (for example restart flags, test/coverage artifacts, and the error-ticket cache at `ERROR_CACHE_PATH` / `/shared_cache/errors`, see `shared_code/infra/error_tickets/`).

## Setup Notes

- `edwh setup` applies directory permissions for shared paths.
- Keep these directories present on host for local and containerized workflows.

## Image Storage Configuration

`ImageStorage.from_env()` uses the local mock when `IMAGE_STORAGE_FAKE=1` (the default). Set it to `0` to use an S3-compatible bucket through the MinIO client. Production requires:

- `IMAGE_STORAGE_ENDPOINT_URL`
- `IMAGE_STORAGE_BUCKET`
- `IMAGE_STORAGE_ACCESS_KEY_ID`
- `IMAGE_STORAGE_SECRET_ACCESS_KEY`
- `IMAGE_STORAGE_PUBLIC_BASE_URL`

Image filenames use `IMAGE_STORAGE_HASH_SALT`.
