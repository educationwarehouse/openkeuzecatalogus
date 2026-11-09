# PDF worker: the base pgq image plus WeasyPrint and its native rendering stack.
#
# Kept separate so the shared pgq image (scrapers, applog, maintenance) stays lean; only this
# service can call PdfService.render. `pgq-base` is supplied by compose as an additional build
# context pointing at the pgq-scrapers service image, so this stays a true extension of that image
# rather than a second copy of its setup.
FROM pgq-base

USER root

# WeasyPrint reaches these through ctypes, so a missing library is an import-time OSError rather
# than a render-time failure. shared-mime-info is needed for embedded image sniffing, and
# fonts-dejavu-core gives the renderer at least one real font family to fall back on.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fonts-dejavu-core && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# The pinned PDF-worker dependencies deliberately stay separate from pgq/requirements.txt, which
# feeds every PGQ worker. WeasyPrint is unusable without the libraries installed above.
COPY pdf-requirements.txt /home/microservices
RUN uv pip install --no-cache -r /home/microservices/pdf-requirements.txt

USER microservices

# CMD see docker compose
