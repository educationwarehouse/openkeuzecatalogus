"""PGQ consumer entrypoints."""

import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*asyncio\.iscoroutinefunction.*deprecated.*inspect\.iscoroutinefunction.*",
    category=DeprecationWarning,
)
