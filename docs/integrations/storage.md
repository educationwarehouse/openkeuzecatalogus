# Storage Integration

## Runtime Paths

Shared storage is provided through bind mounts in Compose:

- `./shared_user_storage` -> `/shared_user_storage` (shared read-write by `py4web` and `pgq-pdf`)
- `./shared_cache` -> `/shared_cache` (shared by migrate/py4web/pgq/playwright)
- `./shared_applog` -> `/shared_applog` (shared applog queue directory)

## What Uses These Paths

- `/shared_user_storage/keuzecanvas` holds staged HTML, rendered PDFs, and a content-hash marker for each keuzecanvas vision PDF. `py4web` writes the HTML and streams a fresh PDF to the user; `pgq-pdf` reads the HTML and writes the PDF and hash marker.
- The mock image-storage service writes images under `/shared_cache/image_uploads` and returns `file://` URLs pointing at the stored path.
- applog processing writes queued log signals under `/shared_applog`.
- runtime coordination and cache/state files live under `/shared_cache` (for example restart flags, test/coverage artifacts, and the error-ticket cache at `ERROR_CACHE_PATH` / `/shared_cache/errors`, see `shared_code/infra/error_tickets/`).

## Setup Notes

- `edwh setup` applies directory permissions for shared paths.
- Keep these directories present on host for local and containerized workflows.

## PDF Worker

Vision-PDF conversion runs only in the `pgq-pdf` Compose service. It uses the dedicated
`pgq/pdf.Dockerfile`, which supplies WeasyPrint and its native libraries; the web service must
not render PDFs itself. Both services need the same writable `./shared_user_storage` bind mount,
because the queue payload contains only the vision gid, not the staged HTML.

Scale this consumer independently with `PDF_WORKERS` (default `2`). It uses batch size `1`, so
each worker processes one render at a time.

The web request serves a cached PDF only when its hash marker matches the newly generated HTML.
Otherwise it stages the HTML, enqueues `render_vision_pdf`, and returns a waiting page that polls
the read-only `/visie.pdf/status` URL every two seconds. Status checks do not rebuild the HTML or
enqueue work. Each worker renders at most one PDF at a time, and a per-document file lock plus
a freshness check prevents duplicate jobs from rendering the same export simultaneously.
HTML, PDF and freshness markers are published atomically. A failed render writes a separate
failure marker for that document version. Polling reports this failure and the retry action
explicitly starts another export. An interrupted render never writes the freshness marker;
a later download request can start it again. A changed vision produces different HTML and
therefore also causes a new render.

## Image Storage Configuration

`ImageStorage.from_env()` uses the local mock when `IMAGE_STORAGE_FAKE=1` (the default). Set it to `0` to use an S3-compatible bucket through the MinIO client. Production requires:

- `IMAGE_STORAGE_ENDPOINT_URL`
- `IMAGE_STORAGE_BUCKET`
- `IMAGE_STORAGE_ACCESS_KEY_ID`
- `IMAGE_STORAGE_SECRET_ACCESS_KEY`
- `IMAGE_STORAGE_PUBLIC_BASE_URL`

Image filenames use `IMAGE_STORAGE_HASH_SALT`.

PDF exports use this same `ImageStorage` service to read owned covers. The worker embeds each
cover once, deduplicates repeated URLs and uses at most four concurrent downloads. An unavailable
cover does not block the document. Branded QR codes are embedded as sharp PNGs, avoiding the
render cost of thousands of individual vector circles.
