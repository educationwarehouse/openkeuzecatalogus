"""Record terminal failure for abandoned queue jobs without redelivery."""

from shared_code.infra.database import DatabaseContext


def fail_abandoned_jobs(database: DatabaseContext) -> int:
    """Atomically move expired jobs to failure history and store their results."""
    jobs = database.executesql(
        """
        WITH expired AS (
            DELETE FROM pgqueuer
            WHERE status = 'picked' AND heartbeat < NOW() - INTERVAL '5 minutes'
            RETURNING id, entrypoint, priority, dedupe_key
        ), logged AS (
            INSERT INTO pgqueuer_log (job_id, status, entrypoint, priority)
            SELECT id, 'exception', entrypoint, priority FROM expired RETURNING job_id
        ), results AS (
            INSERT INTO pgqueuer_result (job_id, entrypoint, status, ok, result, unique_key)
            SELECT id, entrypoint, 'exception', FALSE,
                '{"exception": "Worker heartbeat expired"}'::json, dedupe_key::uuid
            FROM expired WHERE dedupe_key IS NOT NULL RETURNING job_id
        )
        SELECT expired.id
        FROM expired JOIN logged ON logged.job_id = expired.id;
        """,
    )
    return len(jobs)
