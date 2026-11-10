# Database

This project uses `TypeDAL`/`pyDAL` style database access.

## Postgres Image (`postgres/`)

The `postgres` Compose service is built from `postgres/Dockerfile` (base: `postgres:18`, adds `pgaudit` and extension build deps).
`postgres/extensions.sql` is mounted into `docker-entrypoint-initdb.d` and runs once on database init, enabling `pgcrypto`, `unaccent`,
`pg_trgm`, and `pg_stat_statements`.
`pg_trgm` backs the similarity scoring in [search ranking](../architecture/search-ranking.md) and is also
enabled by migration for databases that predate this init script; `pg_stat_statements` gets the same treatment.

### Layered config

`postgres/addendum.conf` supplies extra `postgresql.conf` settings layered onto the base image config: `pgaudit`,
`pg_stat_statements` with `pg_stat_statements.track = all`, `password_encryption`, and `client_min_messages`.

The base image only ever reads `$PGDATA/postgresql.conf`, so the bind mount by itself does nothing. Two pieces make the
layering real:

- clusters initialized from scratch pick up `include = '/etc/postgresql/postgresql.conf'` because the Dockerfile appends
  it to `postgresql.conf.sample`, which `initdb` copies into `$PGDATA/postgresql.conf`;
- clusters that already existed get that same line appended once by `postgres/entrypoint-addendum.sh` when the container
  starts.

Verify with `SHOW shared_preload_libraries;` (in the `pg-0` container): it must list `pgaudit, pg_stat_statements`. If it
is empty the config layer is not being read.

### Slow queries

`pg_stat_statements` collects statistics cluster-wide, so one database with the extension installed can show them all:

```bash
docker compose exec -T pg-0 psql -U postgres -d backend \
  -c "SELECT calls, round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 1) AS mean_ms, \
             round(100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct, \
             left(query, 120) AS query \
        FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 20;"
```

With PostgreSQL's default `pg_stat_statements.save = on`, counters survive clean
server shutdowns and restarts. Clear them with `pg_stat_statements_reset()` when
starting a new measurement; a crash can lose statistics that were not saved.

## References

- `pyDAL`: https://www.web2py.com/books/default/chapter/29/06/the-database-abstraction-layer
- `TypeDAL`: https://typedal.readthedocs.io/en/stable/

## Safety

- Prefer ORM calls for normal CRUD and query work.
- Use `db.executesql(...)` only when you need SQL-specific behavior that the ORM does not cover.
- When you do use `executesql`, pass dynamic values through `placeholders=` or t-strings, not string interpolation.

ORM calls are safe for values because they bind parameters instead of concatenating SQL text.
That includes normal model operations such as inserts, updates, deletes, and filtered queries.

T-strings are a newer Python feature that let you embed expressions in SQL while keeping values parameterized.
They are useful when you want readable SQL without manually building a string.
There are two common forms:

- `t"SELECT ... WHERE olid = {olid}"`: embed the value expression directly.
- `t"SELECT ... WHERE {olid = }"`: use the named-expression shorthand, for when the column and variable have the same name.

## What Still Needs Care

- SQL identifiers such as table names, column names, trigger names, and function names cannot be parameterized the same way as values.
- Only build identifiers from trusted code paths or strict allowlists.
- If you must interpolate identifiers, keep the source controlled and predictable.

## Practical Rule

- Safe: `Product.insert(name=name, ...)`
- Safe: `db.executesql("SELECT ... WHERE olid = %(olid)s", placeholders={"olid": olid})`
- Safe: `db.executesql(t"SELECT ... WHERE olid = {olid}")`
- Safe: `db.executesql(t"SELECT ... WHERE {olid = }")`
- Unsafe: `db.executesql(f"SELECT ... WHERE olid = '{olid}'")`
