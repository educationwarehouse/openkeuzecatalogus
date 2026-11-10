"""Core helpers used by migration support classes."""

import contextlib
import sys
import typing as t

import pydal
import typedal

type DAL = pydal.DAL | typedal.TypeDAL


def upsert_index_v1(
    db: DAL,
    full_table_name: str,
    columns: list[str],
    unique: bool = False,
    include: list[str] | None = None,
) -> None:
    """Drop and recreate an index with optional uniqueness and INCLUDE columns."""
    idx_name = f"idx_{full_table_name}_" + "_".join(columns)
    idx_name = idx_name.replace(" ", "_")  # support asc en desc in columname
    sql = f"""
        DROP INDEX IF EXISTS {idx_name};
        CREATE {"UNIQUE" if unique else ""} INDEX {idx_name}
            ON public.{full_table_name} ({", ".join(columns)})
            {"INCLUDE (" + ", ".join(include) + ")" if include else ""}
            ;
        """
    db.executesql(sql)


def create_trigram_index_v1(db: DAL, full_table_name: str, column: str) -> None:
    """Create the trigram index used by case-insensitive and fuzzy text search."""
    index_name = f"{full_table_name}_{column}_trgm_idx"
    db.executesql(f"""
    CREATE INDEX {index_name}
        ON public.{full_table_name} USING gin (({column}::text) gin_trgm_ops);
    """)


def convert_to_effdt_v1(db: DAL, table: str) -> None:
    """Convert a gid table into an effective-dated source table.

    Existing rows become effective at the conversion timestamp. Callers must move
    any foreign keys that target `gid` to the current model table separately.
    """
    table_ed = f"{table}_ed"
    db.executesql(f"""
        ALTER TABLE {table} RENAME TO {table_ed};
        ALTER TABLE {table_ed} DROP CONSTRAINT IF EXISTS {table}_gid_key;
        ALTER TABLE {table_ed}
            ADD COLUMN effdt timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN effstatus boolean NOT NULL DEFAULT TRUE,
            ADD COLUMN prio integer NOT NULL DEFAULT 0,
            ADD COLUMN last_saved_by varchar NOT NULL DEFAULT 'migration/convert_to_effdt',
            ADD COLUMN sync_gid uuid NOT NULL DEFAULT uuidv7()
                CONSTRAINT {table_ed}_unique_sync_gid UNIQUE;
        CREATE INDEX {table_ed}_id_effdt
            ON {table_ed} (gid ASC, effdt DESC, id ASC);
        ALTER TABLE {table_ed}
            ALTER COLUMN effdt SET DEFAULT utcnow();
    """)


def is_materialized_view(db: DAL, name: str, scheme: str = "public") -> bool:
    """Return whether the named database object is a materialized view."""
    if scheme:
        name = f"{scheme}.{name}"

    # return bool(db.executesql(f"-- SELECT 1 FROM materialized_views where mview = '{name}'"))
    return bool(db.executesql(t"SELECT 1 FROM materialized_views where mview = {name}"))


def drop_table_or_mv(db: DAL, name: str, scheme: str = "public") -> None:
    """Drop the named object as a materialized view or table if it exists."""
    if scheme:
        name = f"{scheme}.{name}"

    if is_materialized_view(db, name, scheme=""):
        # is mv
        db.executesql(f"""DROP MATERIALIZED VIEW IF EXISTS {name};""")
    else:
        # is table (hopefully)
        db.executesql(f"""DROP TABLE IF EXISTS {name};""")


def create_effdted_model_view_with_prio_v4(
    db: DAL,
    table: str,
    query_step_1: str | None = None,
    extra_columns: dict[str, str] | None = None,
) -> None:
    """Create trigger-based effective-dated model structures for a table."""
    # now with a table and triggers instead of a materialized view
    effdt = f"{table}_ed"
    model = f"{table}_model"

    # step -1
    db.executesql(f"""
    DROP TRIGGER IF EXISTS refresh_{model}_trigger ON {effdt};
    DROP TRIGGER IF EXISTS {model}_update_trigger ON {effdt};
    """)

    # stap 0
    db.executesql(f"""
    -- create table structure without any data:
    CREATE TABLE {model} (LIKE {effdt} INCLUDING ALL);
    """)

    if extra_columns:
        for column, datatype in extra_columns.items():
            db.executesql(f"""
            ALTER TABLE {model}
                ADD {column} {datatype};
            """)

    # stap 1
    query = (
        query_step_1
        or f"""
            WITH ranked AS (
            SELECT
                table_ed.id,
                ROW_NUMBER() OVER (PARTITION BY table_ed.gid ORDER BY table_ed.prio DESC, table_ed.effdt DESC) AS rn
            FROM
                {effdt} table_ed
            WHERE
                table_ed.effdt <= CLOCK_TIMESTAMP()
                AND (target_gid IS NULL OR table_ed.gid = target_gid)
        )
        SELECT
            table_ed.*
        FROM
            ranked inner join {effdt} table_ed on table_ed.id = ranked.id and rn = 1 and table_ed.effstatus = 'T';
    """  # noqa S608: all parameters are in our control so no SQL injection possible
    )

    db.executesql(f"""
    DROP FUNCTION IF EXISTS get_active_{table}(uuid);
    CREATE OR REPLACE FUNCTION get_active_{table}(target_gid uuid DEFAULT NULL)
    RETURNS TABLE (
        like {model} -- was {effdt} but _model can have more columns (e.g. `tag.parents`)
    ) AS $$
    BEGIN
        RETURN QUERY
        {query}
    END;
    $$ LANGUAGE plpgsql;
    """)

    # stap 2
    db.executesql(
        f"""
    CREATE OR REPLACE FUNCTION apply_change_{model}()
    RETURNS TRIGGER AS $$
    DECLARE
        best_record {model}%ROWTYPE; -- was {effdt} but _model can have more columns (e.g. `tag.parents`)
    BEGIN
        -- Find the best effective dated row for the affected GID in a single SELECT
        SELECT *
            INTO best_record
            FROM get_active_{table}(NEW.gid)
            LIMIT 1;
        -- If there's no valid record, remove from the model if it exists
        -- verwerk eff_status == 'F' om te verwijderen
        IF NOT FOUND THEN
            DELETE FROM {model} WHERE gid = NEW.gid;
            RETURN NULL;
        END IF;

        -- Check if the `id` matches; if not, update the model: remove any old row and insert new
        IF NOT EXISTS (
            SELECT 1
            FROM {model}
            WHERE id = best_record.id
        ) THEN
            -- Remove the old record if it exists
            DELETE FROM {model} WHERE gid = best_record.gid;

            -- Insert the new record dynamically
            INSERT INTO {model} SELECT best_record.*;
        END IF;

        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """  # noqa S608: all parameters are in our control so no SQL injection possible
    )

    # stap 3
    db.executesql(
        f"""
    CREATE OR REPLACE TRIGGER {model}_update_trigger
        AFTER INSERT
        ON {effdt}
        FOR EACH ROW
            EXECUTE PROCEDURE apply_change_{model}();
    """
    )

    # stap 4
    db.executesql(
        f"""
    CREATE OR REPLACE FUNCTION rebuild_{model}()
    RETURNS void AS $$
    BEGIN
        -- remove all rows from {model}
        TRUNCATE {model};

        -- insert new rows from get_active_{table}()
        INSERT INTO {model}
        SELECT * FROM get_active_{table}();
    END;
    $$ LANGUAGE plpgsql;
    """  # noqa S608: all parameters are in our control so no SQL injection possible
    )

    # stap 5 - indices
    db.executesql(f"""
    -- Create TOAST table settings (internal dependency will be handled automatically by PostgreSQL)
    ALTER TABLE {model}
        SET (AUTOVACUUM_ENABLED = TRUE);

    DROP INDEX IF EXISTS idx_{effdt}_effdt_lookup;
    CREATE INDEX idx_{effdt}_effdt_lookup ON {effdt} (effdt, gid, prio DESC, effdt DESC) include (id);

    """)

    # laatste stap - vul de tabel:
    db.executesql(f"""
    select rebuild_{model}();
    """)


@contextlib.contextmanager
def no_triggers(db: DAL) -> t.Generator[None]:
    """Temporarily disable database triggers.

    Examples:
        >>> with no_triggers(db):
        >>>      db.executesql('''
        >>>      UPDATE tagged_ed SET id = id where id = (select max(id) from tagged_ed);
        >>>      ''')
        >>>      db.commit() # -> this won't notify postgres notify listener via trigger

    """
    db.executesql(
        """
    -- disable triggers
    SET session_replication_role = replica;
    """
    )
    try:
        yield
    except:
        db.rollback()
        raise
    finally:
        db.executesql(
            """
        -- re-enable triggers
        SET session_replication_role = default;
        """
        )


def rebuild_all_materialized_tables_v1(
    db: DAL, exceptions: t.Iterable[str] = (), extra: t.Iterable[str] = (), dependency_order: list[str] | None = None
) -> list[str]:
    """Rebuild all public materialized tables, optionally ordered by dependency."""
    # Get all materialized table models
    result = db.executesql("""
                           SELECT table_name
                               FROM information_schema.tables
                               WHERE table_schema = 'public'
                                 AND RIGHT(table_name, 6) = '_model'
                               ORDER BY table_name;
                           """)

    # Sort tables based on dependency order, with fallback to alphabetical
    table_names = [tablename for row in result if (tablename := row[0]) and tablename not in exceptions]

    if dependency_order:
        table_names.sort(
            key=lambda table: (
                dependency_order.index(table) if table in dependency_order else 999,  # Unknown tables get low priority
                table,  # Secondary sort by name for consistency
            ),
        )
    table_names.extend(extra)

    # Execute rebuild functions in dependency order
    for table_name in table_names:
        func_name = f"rebuild_{table_name}()"
        try:
            db.executesql(f"SELECT rebuild_{table_name}();")
            print(f"{func_name} Ok")
            db.commit()
        except Exception as e:
            print(f"{table_name} Err: {e}")
            db.rollback()

    return table_names


def simple_progress[T](items: t.Collection[T], every: int = 1000, final: bool = True) -> t.Iterator[T]:
    """Yield items while printing coarse progress for large migration batches."""
    idx = 0

    for idx, item in enumerate(items, 1):
        if idx % every == 0:
            print(f"{idx} / {len(items)}", file=sys.stderr)
        yield item

    if items and final:
        print(f"{idx} / {len(items)}", file=sys.stderr)
