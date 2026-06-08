FROM postgres:18

# Install required dependencies for building PostgreSQL extensions
USER root

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    postgresql-server-dev-18 \
    postgresql-18-pgaudit \
    && rm -rf /var/lib/apt/lists/*

USER postgres

# CREATE EXTENSION happens via `docker-entrypoint-initdb.d` at startup, see extensions.sql
