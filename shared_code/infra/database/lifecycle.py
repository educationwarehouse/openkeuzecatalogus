"""Database context lifecycle and applog-aware error handling."""

import contextlib
import os
import typing as t

from shared_code.data_model.setup import define_tables
from shared_code.modules.auth import AuthAdapter
from shared_code.services.applog import Applogger
from shared_code.services.applog.contracts import ApplogEvent

from .advisory_locks import advisory_semaphore_context
from .context import DatabaseContext


@contextlib.contextmanager
def catch_errors(
    appname: str,
    ignore: bool = False,
    reraise: bool = True,
    ExceptionLevel: type[BaseException] = Exception,
    applog: Applogger | None = None,
) -> t.Generator[None]:
    """Capture exceptions as applog events, with optional ignore/reraise behavior."""
    applog = applog or Applogger.with_injected(
        auth_adapter=AuthAdapter.for_service(appname),
    )

    try:
        yield
    except ExceptionLevel as error:
        if ignore:
            return

        error_event = ApplogEvent(
            kind="error",
            action=None,
            details={"application": appname},
        )

        applog.try_fire(error_event)

        if reraise:
            raise error


@contextlib.contextmanager
def database_context(
    appname: str,
    ignore_errors: bool = False,
    semaphore: str | None = None,
    semaphore_namespace: str = "edwh.core",
    env_key: str = "POSTGRES_URI",
) -> t.Generator[DatabaseContext]:
    """Set up a database connection and close it after use."""
    with catch_errors(appname, ignore=ignore_errors, reraise=not ignore_errors):
        postgres_uri = os.environ.get(env_key)
        if not postgres_uri:
            raise RuntimeError(f"{env_key = } is required.")

        db = DatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service(appname))

        try:
            with advisory_semaphore_context(
                db,
                semaphore=semaphore,
                semaphore_namespace=semaphore_namespace,
                transaction_lock=True,
            ):
                yield define_tables(db)
                db.commit()
        except BaseException as error:
            db.rollback()
            print("! something failed -> rolling back database changes !")
            print(error)
            raise error
        finally:
            if semaphore:
                db.executesql(
                    "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                    placeholders=(semaphore_namespace, semaphore),
                )
            db.close()
