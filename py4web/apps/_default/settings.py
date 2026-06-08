import os

from py4web.core import required_folder

APP_FOLDER = os.path.dirname(__file__)
APP_NAME = os.path.split(APP_FOLDER)[-1]

DB_FOLDER = required_folder(APP_FOLDER, "databases")
DB_URI = os.environ["POSTGRES_URI"]
DB_POOL_SIZE = 1
DB_MIGRATE = False
DB_FAKE_MIGRATE = False

SESSION_SECRET = os.environ["PY4WEB_SESSION_SECRET"]

ENTREE_FAKE = os.getenv("ENTREE_FAKE", "0").strip() == "1"
ENTREE_CLIENT_ENDPOINT = os.getenv("ENTREE_CLIENT_ENDPOINT", "").strip()
ENTREE_CLIENT_ID = os.getenv("ENTREE_CLIENT_ID", "").strip()
ENTREE_CLIENT_SECRET = os.getenv("ENTREE_CLIENT_SECRET", "").strip()
