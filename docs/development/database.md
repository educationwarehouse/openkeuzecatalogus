# Database

This project uses `TypeDAL`/`pyDAL` style database access.

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
