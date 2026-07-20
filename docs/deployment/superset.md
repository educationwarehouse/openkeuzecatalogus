## Superset database connection

Superset connects to the database using the database connection variables located in the `.env` file.

For security reasons, Superset should **not** connect to the database using the main database user. Instead, it must use a read-only database user.

The following `.env` variables should be used for the Superset database connection:

```env
SUPERSET_DB_USER=superset_readonly
SUPERSET_DB_PASSWORD=...
```

These credentials are used for a **read-only database user**. This limits the impact if Superset is ever compromised: an attacker would not gain write access to the database and would only be able to read the data that this user is allowed to access.

Superset should connect to the database through a private/internal network instead of exposing the database port publicly.

In our setup, Superset is hosted on a separate server. Since both servers are hosted at the same server provider, we connect Superset to the database server through an internal vSwitch. This allows Superset to remotely read from the database without opening the database port to the public internet.

