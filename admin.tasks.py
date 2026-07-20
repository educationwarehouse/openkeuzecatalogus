"""Invoke tasks for managing users and feature flags through py4web."""

import ast
import contextlib
import getpass
import json
import re
import shlex
import typing as t

import edwh.tasks
from edwh import DOCKER_COMPOSE, task
from ewok import Context
from invoke.exceptions import Exit
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
PY4WEB_HTTP_ERROR_RE = re.compile(r'py4web\.core\.HTTP:\s*\((\d+),\s*["\'](.+?)["\']\)', flags=re.DOTALL)


def _ui_error(message: str) -> None:
    rprint(Panel.fit(message, title="Error", border_style="red"))


def _ui_success(message: str) -> None:
    rprint(f"[green]{message}[/green]")


def _parse_json_line(line: str) -> dict[str, t.Any] | None:
    line = ANSI_ESCAPE_RE.sub("", line).strip()
    if not line:
        return None

    # If the payload is embedded in another line, try to extract a dict-like fragment.
    if "{" in line and "}" in line:
        line = line[line.find("{") : line.rfind("}") + 1]

    try:
        value = json.loads(line)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    with contextlib.suppress(ValueError, SyntaxError):
        value = ast.literal_eval(line)
        if isinstance(value, dict):
            return value
        if isinstance(value, bool):
            return {"ok": value}

    return None


def _extract_json(stdout: str) -> dict[str, t.Any]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        if parsed := _parse_json_line(line):
            return parsed

    raise ValueError(f"No JSON payload found in output:\n{stdout}")


def _extract_py4web_http_error(output: str) -> tuple[int, str] | None:
    # e.g. py4web.core.HTTP: (404, "User 'foo@bar' not found")
    match = PY4WEB_HTTP_ERROR_RE.search(output)
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip()


def py4web_call(ctx: Context, fn: str, args: dict | None = None) -> dict[str, t.Any]:
    """Call a py4web CLI helper inside the container and parse its JSON output."""
    args = args or {}
    args_json = shlex.quote(json.dumps(args))
    call = f"py4web call apps admin.models.cli_support.{fn} --args {args_json}"

    commands = (
        f"{DOCKER_COMPOSE} exec -T py4web {call}",
        f"{DOCKER_COMPOSE} run --rm --no-deps -T py4web {call}",
    )

    failures: list[str] = []
    for cmd in commands:
        result = ctx.run(cmd, warn=True, hide=True)
        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)

        if http_error := _extract_py4web_http_error(combined_output):
            code, message = http_error
            _ui_error(f"{message} (HTTP {code})")
            raise Exit(code=1)

        if not result.ok:
            failures.append(result.stderr or result.stdout or f"Command failed: {cmd}")
            continue

        if fn == "toggle_feature":
            if "True" in combined_output:
                return {"ok": True}
            if "False" in combined_output:
                return {"ok": False}

        try:
            return _extract_json(combined_output)
        except ValueError as err:
            failures.append(str(err))
            continue

    compact = "\n".join(
        line
        for line in "\n\n".join(failures).splitlines()
        if line.strip() and not line.strip().startswith("Container ")
    )
    _ui_error(compact or "Command failed")
    raise Exit(code=1)


def _default_name_from_email(email: str) -> tuple[str, str]:
    base = (email or "").split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").strip()
    parts = [p for p in base.split(" ") if p]

    if not parts:
        return "User", ""

    first = parts[0].capitalize()
    last = " ".join(part.capitalize() for part in parts[1:])
    return first, last


@task(flags={"disabled": ("disabled", "d")})
def featureflag(ctx: Context, flag_name: str, disabled: bool = False) -> None:
    """Set a feature flag. Use 'all' to set all."""
    py4web_call(
        ctx,
        "toggle_feature",
        {"feature": flag_name, "enabled": "off" if disabled else "on"},
    )

    # needs restart after switching flag:
    edwh.tasks.up(ctx, service=["py4web"])


@task(aliases=("list",))
def list_users(ctx: Context, role: str = "") -> None:
    """Show the known users, optionally filtered by role."""
    data = py4web_call(ctx, "list_users", {"role": (role or "").strip()})
    users = data.get("users", [])

    table = Table(title=f"Users ({len(users)})")
    table.add_column("Email")
    table.add_column("First Name")
    table.add_column("Last Name")
    table.add_column("Roles")

    for user in users:
        table.add_row(
            user.get("email", ""),
            user.get("first_name", ""),
            user.get("last_name", ""),
            ", ".join(user.get("roles", [])) or "—",
        )

    rprint(table)


@task()
def add_user(
    ctx: Context,
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    password: str = "",
    admin: bool = False,
    eddie: bool = False,
) -> None:
    """Create a new user, prompting for missing values when needed."""
    if not email:
        email = input("Email: ").strip().lower()
    if not email:
        raise ValueError("Email is required")

    if not first_name and not last_name:
        guessed_first, guessed_last = _default_name_from_email(email)
        while not first_name:
            first_name = input(f"First name [{guessed_first}]: ").strip() or guessed_first
        while not last_name:
            if guessed_last:
                last_name = input(f"Last name [{guessed_last}]: ").strip() or guessed_last
            else:
                last_name = input("Last name: ").strip()
    if not password:
        password = getpass.getpass("Password: ").strip()

    roles = []
    if admin:
        roles.append("admin")
    if eddie:
        roles.append("eddie")

    data = py4web_call(
        ctx,
        "add_user",
        {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "password": password,
            "roles": roles,
        },
    )
    _ui_success(f"Created user: {data.get('email', email)}")


@task()
def remove_user(ctx: Context, email: str) -> None:
    """Remove a user account by email."""
    data = py4web_call(ctx, "remove_user", {"email": email})
    _ui_success(f"Removed user: {data.get('email', email)}")


@task()
def set_password(ctx: Context, email: str, password: str = "") -> None:
    """Update a user's password, prompting for confirmation when needed."""
    if not password:
        password = getpass.getpass("New password: ").strip()
        confirm = getpass.getpass("Repeat password: ").strip()
        if password != confirm:
            raise ValueError("Passwords do not match")

    data = py4web_call(ctx, "set_password", {"email": email, "password": password})
    _ui_success(f"Password updated for: {data.get('email', email)}")


@task()
def grant_role(ctx: Context, email: str, role: str) -> None:
    """Grant a role to a user."""
    role = (role or "").strip()
    data = py4web_call(ctx, "grant_role", {"email": email, "role": role})
    _ui_success(f"Granted role {data.get('role', role)} to {data.get('email', email)}")


@task()
def revoke_role(ctx: Context, email: str, role: str) -> None:
    """Revoke a role from a user."""
    role = (role or "").strip()
    data = py4web_call(ctx, "revoke_role", {"email": email, "role": role})
    _ui_success(f"Revoked role {data.get('role', role)} from {data.get('email', email)}")


@task()
def make_admin(ctx: Context, email: str) -> None:
    """Grant the internal admin role to a user."""
    grant_role(ctx, email, "admin@internal")
