"""PostgreSQL advisory-lock helpers."""

import contextlib
import typing as t

from typedal import TypeDAL


@contextlib.contextmanager
def advisory_semaphore_context(
    db: TypeDAL,
    semaphore: str | None = None,
    semaphore_namespace: str = "edwh.core",
    transaction_lock: bool = False,
    release_on_exit: bool = True,
) -> t.Generator[None]:
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
    except BaseException as error:
        failed = True
        raise error
    finally:
        should_unlock = (not transaction_lock) and (release_on_exit or failed)
        if should_unlock:
            db.executesql(
                "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                placeholders=(semaphore_namespace, semaphore),
            )
