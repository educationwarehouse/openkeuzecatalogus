import os

from common.settings import (
    DB_FAKE_MIGRATE,
    DB_FOLDER,
    DB_MIGRATE,
    DB_POOL_SIZE,
    DB_URI,
    ENTREE_CLIENT_ENDPOINT,
    ENTREE_CLIENT_ID,
    ENTREE_CLIENT_SECRET,
    ENTREE_FAKE,
    SESSION_SECRET,
)

APP_FOLDER = os.path.dirname(__file__)
APP_NAME = os.path.split(APP_FOLDER)[-1]

__all__ = [
    "APP_FOLDER",
    "APP_NAME",
    "DB_FAKE_MIGRATE",
    "DB_FOLDER",
    "DB_MIGRATE",
    "DB_POOL_SIZE",
    "DB_URI",
    "ENTREE_CLIENT_ENDPOINT",
    "ENTREE_CLIENT_ID",
    "ENTREE_CLIENT_SECRET",
    "ENTREE_FAKE",
    "SESSION_SECRET",
]
