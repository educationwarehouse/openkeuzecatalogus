"""Queue infrastructure that maintains ownership heartbeats for every entrypoint."""

import asyncio
import datetime as dt
import functools
import logging
import typing as t

import asyncpg
from pgqueuer.models import Job
from pgqueuer.types import QueueExecutionMode
from pgskewer import ImprovedQueuer

from pgq.consumers.health import mark_heartbeat

type JobHandler = t.Callable[[Job], t.Awaitable[t.Any]]


class WorkerQueuer(ImprovedQueuer):
    """Register job handlers with heartbeat tracking enabled centrally."""

    async def _health_heartbeat(self) -> None:
        """Keep this process healthy while its event loop remains responsive."""
        while not self.shutdown.is_set():
            mark_heartbeat()
            await asyncio.sleep(30)

    async def run(
        self,
        dequeue_timeout: dt.timedelta = dt.timedelta(seconds=30),
        batch_size: int = 10,
        mode: QueueExecutionMode = QueueExecutionMode.continuous,
        max_concurrent_tasks: int | None = None,
        shutdown_on_listener_failure: bool = False,
    ) -> None:
        """Run a local health heartbeat for exactly this manager's lifetime."""
        async with asyncio.TaskGroup() as tasks:
            heartbeat = tasks.create_task(self._health_heartbeat())
            try:
                await super().run(
                    dequeue_timeout=dequeue_timeout,
                    batch_size=batch_size,
                    mode=mode,
                    max_concurrent_tasks=max_concurrent_tasks,
                    shutdown_on_listener_failure=shutdown_on_listener_failure,
                )
            finally:
                heartbeat.cancel()

    def entrypoint(self, name: str, **options: t.Any) -> t.Callable[[JobHandler], JobHandler]:
        """Keep every registered job alive without enabling queue redelivery."""
        register = super().entrypoint(name, **options)

        def decorate(handler: JobHandler) -> JobHandler:
            @functools.wraps(handler)
            async def tracked(job: Job) -> t.Any:
                stopped = asyncio.Event()

                async def heartbeat() -> None:
                    while not stopped.is_set():
                        try:
                            running = await self.qm.queries.driver.fetch(
                                """
                                UPDATE pgqueuer SET heartbeat = NOW()
                                WHERE id = $1 AND status = 'picked' AND queue_manager_id = $2
                                RETURNING id;
                                """,
                                job.id,
                                job.queue_manager_id,
                            )
                        except asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError:
                            logging.exception("Heartbeat failed for job %s; retrying next tick", job.id)
                        else:
                            if not running:
                                raise RuntimeError(f"Job {job.id} is no longer owned by this worker")

                        try:
                            await asyncio.wait_for(stopped.wait(), timeout=30)
                        except TimeoutError:
                            continue

                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(heartbeat())
                    try:
                        return await handler(job)
                    finally:
                        stopped.set()

            return register(tracked)

        return decorate
