"""Reusable access-control fixture with redirect-or-else semantics."""

import functools
import inspect
import typing as t

import yayarl as yarl
from py4web.core import Fixture, Session, redirect, request
from typedal.for_py4web import DAL

from py4web import URL
from shared_code.data_model import AnyDict

type ConditionFn = t.Callable[[AnyDict], bool]
type Condition = ConditionFn | bool | t.Callable[[], bool]
type OrElseReturn = str | yarl.URL | BaseException | None
type OrElseFn = t.Callable[[AnyDict], OrElseReturn]
type OrElse = (
    str
    | yarl.URL
    | OrElseFn  # lambda ctx: 'url' | URL('url') | HTTP(403, '') | None
    | t.Callable[[], OrElseReturn]  # lambda: ...
    | BaseException
    | None
)


def get_required_arg_count(func: t.Callable[..., t.Any]) -> int:
    """Count the amount of required arguments (-> without a default and exlucing *args and **kwargs).

    Examples:
        >>> get_required_arg_count(lambda x: x) # 1
        >>> get_required_arg_count(lambda x, y, z=3: x) # 2
        >>> get_required_arg_count(lambda x, *a: x) # 1

    """
    sig = inspect.signature(func)
    required_args = [
        param.name
        for param in sig.parameters.values()
        if (param.kind == inspect.Parameter.POSITIONAL_ONLY or param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and param.default == inspect.Parameter.empty
    ]
    return len(required_args)


class RequiresFixture(Fixture):
    """A fixture class that validates a condition and performs an action if the condition is not met.

    See AppAuth.requires for usage examples.
    """

    condition: ConditionFn
    or_else: OrElseFn

    def __init__(
        self,
        db: DAL,
        session: Session,
        condition: Condition,
        or_else: OrElse,
    ) -> None:
        """Initialize the fixture with its database, session, condition, and fallback."""
        super().__init__()
        self.__prerequisites__ = [db, session]

        self.db = db
        self.session = session

        self._condition = self.condition = t.cast(ConditionFn, condition)
        self._or_else = self.or_else = t.cast(OrElseFn, or_else)

    def transform_callback_on_request[T](self, maybe_callback: T | None) -> T:
        """Transform a callback into a callable with the request context bound in.

        Args:
            maybe_callback: The value to transform into a function with 1 argument.

        Returns:
            Callable: The transformed callback function.

        """
        if not callable(maybe_callback):
            return lambda _: maybe_callback  # type: ignore

        callback: t.Callable[..., t.Any] = maybe_callback

        signature = inspect.signature(callback)

        matched = set()
        for key, value in request.url_args.items():
            if key in signature.parameters:
                callback = functools.partial(callback, **{key: value})
                matched.add(key)

        # if callable has optional extra's, we can ignore those.
        argc = get_required_arg_count(callback)

        match argc:
            case 0:
                return lambda _: callback()  # type: ignore
            case 1:
                return callback  # type: ignore
            case _:
                missing = signature.parameters.keys() - matched
                raise TypeError(
                    f"Invalid callable: not all arguments could be matched: {missing}!",
                )

    def _validate(self, ctx: AnyDict) -> bool:
        if callable(self.condition):
            return self.try_condition(ctx)
        else:
            return bool(self.condition)

    def validate(self, ctx: AnyDict | None = None) -> bool:
        """Validate the condition.

        Args:
            ctx (AnyDict): The context to validate the condition against.

        Returns:
            bool: The result of the validation.

        """
        ctx = ctx or {}
        result = self._validate(ctx)
        ctx["_validate"] = result
        return result

    def try_condition(self, ctx: AnyDict) -> bool:
        """Run the condition while returning False on any errors."""
        try:
            condition = self.transform_callback_on_request(self._condition)
            return condition(ctx)
        except Exception as e:
            print(f"try_condtion ({self}) failed ({type(e)}):", e)
            return False

    def on_request(self, context: AnyDict) -> None:
        """Validate the condition on request and perform the or_else action if the condition is not met.

        Args:
            context (AnyDict): The context to validate the condition against.

        """
        self.or_else = self.transform_callback_on_request(self._or_else)
        self.condition = self.transform_callback_on_request(self._condition)

        if not self.validate(ctx=context):
            self.back(context)

        return None

    def back(self, context: AnyDict) -> t.Never:
        """Redirect the user (back).

        If or_else is not set, the user is redirected to where they came from (or index)
        If or_else is a string, the user is redirected to that url/route.
        If or_else is a callable, it is executed. This callable can raise or redirect,
            or return a str which will also be seen as an URL to redirect the user to.

        Args:
            context (AnyDict): The context to perform the or_else action against.

        """
        url = default = URL("index")
        match self.or_else:
            case None:
                if not (url := request.environ.get("HTTP_REFERER")):
                    url = default
            case str(value):
                url = value
            case func if callable(func):
                # matches functiontype, partial, class with __call__ etc.
                url = str(func(context) or default)

        if isinstance(url, BaseException):
            raise url

        self.session["flash"] = self.session.get("flash") or {
            "message": "Geen toegang tot deze pagina.",
            "class": "alert-danger",
        }

        return redirect(url)

    def __or__(self, other: t.Self) -> RequiresFixture:
        """Usage: `auth.requires(False) | auth.requires(True)` -> allowed."""
        return RequiresFixture(
            self.db,
            self.session,
            condition=lambda ctx: self.try_condition(ctx) or other.try_condition(ctx),
            or_else=other.or_else or self.or_else,  # always the last (available) one
        )

    def __and__(self, other: t.Self) -> RequiresFixture:
        """Usage: `auth.requires(False) & auth.requires(True)` -> not allowed."""

        def combined_condition(ctx: AnyDict) -> bool:
            ctx.setdefault("_or_else", self.or_else)
            if not self.try_condition(ctx):
                ctx["_or_else"] = self.or_else
                return False

            if not other.try_condition(ctx):
                ctx["_or_else"] = other.or_else
                return False

            return True

        return RequiresFixture(
            self.db,
            self.session,
            condition=combined_condition,
            or_else=lambda ctx: self.transform_callback_on_request(
                ctx.get("_or_else", self._or_else),
            )(ctx),
        )
