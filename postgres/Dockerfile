FROM postgres:18

# Install required dependencies for building PostgreSQL extensions
USER root

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    postgresql-server-dev-18 \
    postgresql-18-pgaudit \
    && rm -rf /var/lib/apt/lists/*

# The base image only reads $PGDATA/postgresql.conf, which initdb generates from
# this sample, so postgres/addendum.conf (bind-mounted at
# /etc/postgresql/postgresql.conf) needs an explicit include to have any effect.
RUN printf "\ninclude = '/etc/postgresql/postgresql.conf'\n" \
    >> /usr/share/postgresql/"$PG_MAJOR"/postgresql.conf.sample

# Clusters that were initialized before that include existed are healed on start.
COPY --chmod=755 entrypoint-addendum.sh /usr/local/bin/entrypoint-addendum.sh

USER postgres

ENTRYPOINT ["entrypoint-addendum.sh"]
# resetting ENTRYPOINT above drops the inherited CMD, so state it again
CMD ["postgres"]

# CREATE EXTENSION happens via `docker-entrypoint-initdb.d` at startup, see extensions.sql
