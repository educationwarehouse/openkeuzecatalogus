from py4web import action

from ..fixtures import common
from ..models import auth


@action("index")
@common()
def index() -> str:
    return "hello world"


@action("profile")
@common(None, auth.user)
def profile() -> str:
    me = auth.get_user()
    return str(me.as_dict() if me else {})


@action("auth/error")
@common()
def auth_no_roles() -> str:
    return "geen rollen (todo)"
