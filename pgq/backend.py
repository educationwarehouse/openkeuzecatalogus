"""Dependency wiring for PGQ workers."""

import contextlib
import typing as t

from endow import BackendBase

from shared_code.data_model.setup import define_tables
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.services import Applogger, ErrorTicketService, LLMService, Mailer, PdfService


class PgqBackend(BackendBase):
    """Shared service graph for one PGQ database job."""

    applog: Applogger
    db: DatabaseContext
    error_tickets: ErrorTicketService
    llm: LLMService
    mailer: Mailer
    # only usable in the `pgq-pdf` image, which adds WeasyPrint's native libraries; elsewhere
    # `PdfService.available` is False rather than an import error
    pdf: PdfService


@contextlib.contextmanager
def pgq_backend(appname: str) -> t.Generator[PgqBackend]:
    """Yield a PGQ backend whose services share one database context."""
    backend = PgqBackend.with_injected(auth_adapter=AuthAdapter.for_service(appname))
    try:
        define_tables(backend.db)
        yield backend
        backend.db.commit()
    except Exception as e:
        backend.db.rollback()
        raise e
    finally:
        backend.db.close()
        backend.close()
