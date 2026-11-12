"""Isolated database clones from a freshly migrated test-session template."""

import os
import typing as t
import uuid
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from pydal._globals import GLOBAL_LOCKER, THREAD_LOCAL
from pydal.connection import ConnectionPool
from psycopg2 import sql


def database_uri(database: str) -> str:
    """Retarget the configured test connection without changing its credentials."""
    uri = os.environ.get("POSTGRES_URI") or os.environ["MIGRATE_URI"]
    return urlunsplit(urlsplit(uri)._replace(path=f"/{database}"))


# Mirrors postgres/extensions.sql, which only runs when the regular database is initialized.
TEMPLATE_EXTENSIONS = ("pgcrypto", "unaccent", "pg_trgm", "pg_stat_statements")


def execute_database_ddl(statement: sql.Composable, database: str = "postgres") -> None:
    """Run DDL outside transactions, against the maintenance database unless another is named."""
    connection = psycopg2.connect(database_uri(database), connect_timeout=5)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute(statement)
    finally:
        connection.close()


@contextmanager
def database_environment(database: str) -> t.Generator[None]:
    """Give a clone its own connection URLs and migration flag directory."""
    keys = ("POSTGRES_URI", "MIGRATE_URI", "FLAG_LOCATION")
    previous = {key: os.environ.get(key) for key in keys}
    uri = database_uri(database)
    with TemporaryDirectory(prefix="pytest-migration-flags-") as flags:
        os.environ.update(POSTGRES_URI=uri, MIGRATE_URI=uri, FLAG_LOCATION=flags)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def close_clone_contexts(database: str) -> None:
    """Release test-local DAL objects, including graphs created by error loggers."""
    groups = getattr(THREAD_LOCAL, "_pydal_db_instances_", {})
    instances = [instance for group in tuple(groups.values()) for instance in tuple(group)]
    closed = set()
    for instance in instances:
        uri = getattr(instance, "_uri", None)
        if not isinstance(uri, str) or urlsplit(uri).path != f"/{database}" or id(instance) in closed:
            continue

        closed.add(id(instance))
        instance.rollback()
        instance.close()

    if closed:
        print(f"[template-db] closed {len(closed)} remaining test-local DAL contexts before dropping {database}")


def close_idle_clone_connections(database: str) -> None:
    """Disconnect recycled pyDAL connections belonging only to a finished clone."""
    idle_connections = []
    with GLOBAL_LOCKER:
        for uri, pool in ConnectionPool.POOLS.items():
            if urlsplit(uri).path != f"/{database}":
                continue

            idle_connections.extend(pool)
            pool.clear()

    for connection in idle_connections:
        connection.close()


@contextmanager
def cloned_database(template: str = "template0") -> t.Generator[str]:
    """Create a unique database and drop it without terminating leaked sessions."""
    name = f"pytest_clone_{uuid.uuid4().hex}"
    execute_database_ddl(
        sql.SQL("CREATE DATABASE {} TEMPLATE {} STRATEGY FILE_COPY").format(
            sql.Identifier(name), sql.Identifier(template)
        )
    )
    try:
        yield name
    finally:
        close_clone_contexts(name)
        close_idle_clone_connections(name)
        # Fail on leaked connections instead of hiding them with FORCE.
        execute_database_ddl(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@contextmanager
def migrated_template(migrate: t.Callable[[], None]) -> t.Generator[str]:
    """Migrate once per session and prohibit connections to the immutable template."""
    with cloned_database() as name:
        # template0 has no extensions, unlike the regular test database.
        for extension in TEMPLATE_EXTENSIONS:
            execute_database_ddl(
                sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(extension)), database=name
            )

        with database_environment(name):
            migrate()

        execute_database_ddl(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name)))
        yield name
