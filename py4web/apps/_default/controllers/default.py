from py4web import action

from ..fixtures import common, flash
from ..models import auth, db


@action("index")
@action.uses(db)
def index() -> str:
    return "hello world"


@action("flash")
@common("auth.html")
def flash_demo() -> dict:
    # fixme: remove
    flash.set("joejoe")
    return {
        "form": "get joejoe'd",
    }


@action("profile")
@action.uses(auth.user)
def profile() -> str:
    return str(auth.get_user())
