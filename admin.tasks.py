"""Invoke tasks for managing users and feature flags through py4web."""

import getpass

import edwh.tasks
from edwh import DOCKER_COMPOSE, task
from ewok import Context
from rich import print as rprint
from rich.table import Table

# local:
from task_support import parse_boolean_result, py4web_call


def _ui_success(message: str) -> None:
    rprint(f"[green]{message}[/green]")


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
        args={"feature": flag_name, "enabled": "off" if disabled else "on"},
        result_parser=parse_boolean_result,
    )

    # needs restart after switching flag:
    edwh.tasks.up(ctx, service=["py4web"])


@task(aliases=("list",))
def list_users(ctx: Context, role: str = "") -> None:
    """Show the known users, optionally filtered by role."""
    data = py4web_call(ctx, "list_users", args={"role": (role or "").strip()})
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


def _prompt_user_name(email: str) -> tuple[str, str]:
    """Prompt for a complete name using defaults derived from the email."""
    guessed_first, guessed_last = _default_name_from_email(email)
    first_name = ""
    last_name = ""
    while not first_name:
        first_name = input(f"First name [{guessed_first}]: ").strip() or guessed_first
    while not last_name:
        if guessed_last:
            last_name = input(f"Last name [{guessed_last}]: ").strip() or guessed_last
        else:
            last_name = input("Last name: ").strip()
    return first_name, last_name


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
        first_name, last_name = _prompt_user_name(email)
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
        args={
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
    data = py4web_call(ctx, "remove_user", args={"email": email})
    _ui_success(f"Removed user: {data.get('email', email)}")


@task()
def set_password(ctx: Context, email: str, password: str = "") -> None:
    """Update a user's password, prompting for confirmation when needed."""
    if not password:
        password = getpass.getpass("New password: ").strip()
        confirm = getpass.getpass("Repeat password: ").strip()
        if password != confirm:
            raise ValueError("Passwords do not match")

    data = py4web_call(ctx, "set_password", args={"email": email, "password": password})
    _ui_success(f"Password updated for: {data.get('email', email)}")


@task()
def grant_role(ctx: Context, email: str, role: str) -> None:
    """Grant a role to a user."""
    role = (role or "").strip()
    data = py4web_call(ctx, "grant_role", args={"email": email, "role": role})
    _ui_success(f"Granted role {data.get('role', role)} to {data.get('email', email)}")


@task()
def revoke_role(ctx: Context, email: str, role: str) -> None:
    """Revoke a role from a user."""
    role = (role or "").strip()
    data = py4web_call(ctx, "revoke_role", args={"email": email, "role": role})
    _ui_success(f"Revoked role {data.get('role', role)} from {data.get('email', email)}")


@task()
def make_admin(ctx: Context, email: str) -> None:
    """Grant the internal admin role to a user."""
    grant_role(ctx, email, "admin@internal")


@task()
def clear_pgq(ctx: Context) -> None:
    """Clear all active PGQ jobs."""
    running_services = ctx.run(
        f"{DOCKER_COMPOSE} ps --services --status running",
        hide=True,
    ).stdout.splitlines()
    pgq_services = [service for service in running_services if service.startswith("pgq-")]

    if pgq_services:
        edwh.tasks.down(ctx, service=pgq_services)

    try:
        py4web_call(ctx, "clear_pgq")
    finally:
        if pgq_services:
            edwh.tasks.up(ctx, service=pgq_services)

    _ui_success("Cleared all active PGQ jobs.")
