from common.fixtures import CommonHelpers, common
from common.models import auth, db, session

flash = auth.flash

auth.enable(route="auth", uses=(CommonHelpers,))

__all__ = ["CommonHelpers", "auth", "common", "db", "flash", "session"]
