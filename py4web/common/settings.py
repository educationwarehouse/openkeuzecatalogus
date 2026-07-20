"""Environment-backed settings shared by the py4web app."""

import os
from pathlib import Path

from py4web.core import required_folder

PACKAGE_FOLDER = os.path.dirname(__file__)

DB_FOLDER = required_folder(PACKAGE_FOLDER, "databases")
DB_URI = os.environ["POSTGRES_URI"]
DB_POOL_SIZE = 1
DB_MIGRATE = False
DB_FAKE_MIGRATE = False

SESSION_SECRET = os.environ["PY4WEB_SESSION_SECRET"]

SHARED_CACHE_DIR = Path("/shared_cache")
RESTART_FLAG = SHARED_CACHE_DIR / "restart.flag"


ENTREE_FAKE = os.getenv("ENTREE_FAKE", "0").strip() == "1"
ENTREE_CLIENT_ENDPOINT = os.getenv("ENTREE_CLIENT_ENDPOINT", "").strip()
ENTREE_CLIENT_ID = os.getenv("ENTREE_CLIENT_ID", "").strip()
ENTREE_CLIENT_SECRET = os.getenv("ENTREE_CLIENT_SECRET", "").strip()

__all__ = [
    "DB_FAKE_MIGRATE",
    "DB_FOLDER",
    "DB_MIGRATE",
    "DB_POOL_SIZE",
    "DB_URI",
    "ENTREE_CLIENT_ENDPOINT",
    "ENTREE_CLIENT_ID",
    "ENTREE_CLIENT_SECRET",
    "ENTREE_FAKE",
    "PACKAGE_FOLDER",
    "SESSION_SECRET",
]
