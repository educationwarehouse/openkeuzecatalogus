from common.fixtures import CommonHelpers, common, static_hash
from common.models import auth, db, session

flash = auth.flash

auth.enable(route="auth", uses=(CommonHelpers, static_hash))

__all__ = ["CommonHelpers", "auth", "common", "db", "flash", "session"]
