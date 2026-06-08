"""Database context helpers with applog-aware error handling and advisory locks."""

import contextlib
import os
import typing as t

from typedal import TypeDAL

from shared_code.data_model.setup import define_tables
from shared_code.services.applog import Applogger
from shared_code.services.applog.contracts import ApplogEvent
from shared_code.services.time.clock import utcnow


@contextlib.contextmanager
def catch_errors(
    appname: str, ignore: bool = False, reraise: bool = True, ExceptionLevel: type[BaseException] = Exception
) -> t.Iterator[None]:
    """Capture exceptions as applog events, with optional ignore/reraise behavior."""
    applog = Applogger.from_env()

    try:
        yield
    except ExceptionLevel as e:
        if ignore:
            return

        # store ticket:
        context = {
            "application": appname,
        }

        error_event = ApplogEvent(
            timestamp=utcnow(),
            kind="error",
            action=None,
            details=context,
        )

        applog.fire(error_event)

        # try:
        #     ticket_id = store_ticket(context)
        # except Exception as e_ticket:
        #     # something failed :(
        #     print("Error storing ticket", e, e_ticket, file=sys.stderr)
        #     ticket_id = None
        #
        # ntfy_sh.notify(
        #     ntfy_sh.NTFY_ERROR_URL,
        #     ticket_id,
        #     "{HOSTINGDOMAIN} {APPLICATION_NAME} {appname} | {error_code}".format(
        #         appname=appname, error_code=type(e), **os.environ
        #     ),
        #     click_url=PY4WEB_URL("admin/errors", ticket_id or ""),
        # )

        if reraise:
            raise e


@contextlib.contextmanager
def advisory_semaphore_context(
    db: TypeDAL,
    semaphore: str | None = None,
    semaphore_namespace: str = "edwh.core",
    transaction_lock: bool = False,
    release_on_exit: bool = True,
) -> t.Iterator[None]:
    """Acquire and release a PostgreSQL advisory lock around a code block."""
    if not semaphore:
        yield
        return

    lock_fn = "pg_advisory_xact_lock" if transaction_lock else "pg_advisory_lock"
    db.executesql(
        f"SELECT {lock_fn}(hashtext(%s), hashtext(%s))",
        placeholders=(semaphore_namespace, semaphore),
    )
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        should_unlock = (not transaction_lock) and (release_on_exit or failed)
        if should_unlock:
            db.executesql(
                "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                placeholders=(semaphore_namespace, semaphore),
            )


@contextlib.contextmanager
def database_context(
    appname: str = "",
    ignore_errors: bool = False,
    semaphore: str | None = None,
    semaphore_namespace: str = "edwh.core",
    env_key: str = "POSTGRES_URI",
) -> t.Iterator[TypeDAL]:
    """Set up a database connection and close it after use."""
    with catch_errors(appname, ignore=ignore_errors, reraise=not ignore_errors):
        postgres_uri = os.environ.get(env_key)
        if not postgres_uri:
            raise RuntimeError(f"{env_key = } is required.")

        db = TypeDAL(postgres_uri)

        try:
            with advisory_semaphore_context(
                db,
                semaphore=semaphore,
                semaphore_namespace=semaphore_namespace,
                transaction_lock=True,
            ):
                yield define_tables(db)
                db.commit()
        except BaseException as e:
            db.rollback()
            print("! something failed -> rolling back database changes !")
            print(e)
            raise e
        finally:
            if semaphore:
                db.executesql(
                    "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                    placeholders=(semaphore_namespace, semaphore),
                )
            db.close()
