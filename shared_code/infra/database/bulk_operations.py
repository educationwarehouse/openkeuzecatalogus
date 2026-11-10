"""Serialize bulk database operations across workers and web processes."""

import contextlib
import typing as t

from typedal import TypeDAL

from shared_code.infra.database import advisory_semaphore_context

BULK_OPERATIONS_SEMAPHORE = "bulk_operations"


@contextlib.contextmanager
def bulk_operation_context(db: TypeDAL) -> t.Generator[None]:
    """Own transaction boundaries and hold one shared lock for a bulk operation."""
    # Web callers may already hold read locks from a preview or supplier lookup.
    # Finish that transaction before waiting, or it can block the active import.
    db.commit()
    with advisory_semaphore_context(db, semaphore=BULK_OPERATIONS_SEMAPHORE):
        try:
            # Use a session lock: import stages commit independently, so a
            # transaction-level lock would stop protecting the run too early.
            yield
            db.commit()
        except BaseException:
            # An aborted SQL transaction cannot execute pg_advisory_unlock.
            # Roll back before the semaphore context releases the session lock.
            db.rollback()
            raise
