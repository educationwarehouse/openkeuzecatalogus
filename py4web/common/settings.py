"""Environment-backed settings shared by the py4web app."""

import os
from datetime import timedelta
from pathlib import Path

from py4web.core import required_folder

PACKAGE_FOLDER = os.path.dirname(__file__)

DB_FOLDER = required_folder(PACKAGE_FOLDER, "databases")
DB_URI = os.environ["POSTGRES_URI"]
DB_POOL_SIZE = 1
DB_MIGRATE = False
DB_FAKE_MIGRATE = False

SESSION_SECRET = os.environ["PY4WEB_SESSION_SECRET"]
SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_SECONDS", str(int(timedelta(days=7).total_seconds()))))
SESSION_ABSOLUTE_SECONDS = int(os.getenv("SESSION_ABSOLUTE_SECONDS", str(int(timedelta(days=30).total_seconds()))))
SIGNED_URL_SECONDS = int(os.getenv("SIGNED_URL_SECONDS", str(int(timedelta(days=7).total_seconds()))))

BYTES_PER_MIB = 1024 * 1024
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(50 * BYTES_PER_MIB)))
UPLOAD_MAX_MIB = UPLOAD_MAX_BYTES / BYTES_PER_MIB
REQUEST_MAX_BYTES = UPLOAD_MAX_BYTES + BYTES_PER_MIB

SHARED_CACHE_DIR = Path("/shared_cache")
RESTART_FLAG = SHARED_CACHE_DIR / "restart.flag"


AUTO_APPROVE_AND_LOGIN_AFTER_REGISTRATION = (
    os.getenv("STATE_OF_DEVELOPMENT", "").upper() in {"ONT", "TEST"}
    and os.getenv("AUTO_APPROVE_AND_LOGIN_AFTER_REGISTRATION", "0").strip() == "1"
)
ENTREE_FAKE = os.getenv("ENTREE_FAKE", "0").strip() == "1"
ENTREE_CLIENT_ENDPOINT = os.getenv("ENTREE_CLIENT_ENDPOINT", "").strip()
ENTREE_CLIENT_ID = os.getenv("ENTREE_CLIENT_ID", "").strip()
ENTREE_CLIENT_SECRET = os.getenv("ENTREE_CLIENT_SECRET", "").strip()

__all__ = [
    "AUTO_APPROVE_AND_LOGIN_AFTER_REGISTRATION",
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
    "SESSION_ABSOLUTE_SECONDS",
    "SESSION_IDLE_SECONDS",
    "SESSION_SECRET",
    "SIGNED_URL_SECONDS",
]
