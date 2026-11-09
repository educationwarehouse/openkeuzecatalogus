"""Shared helpers for invoke tasks that call py4web CLI functions."""

import ast
import contextlib
import json
import re
import shlex
import typing as t

from edwh import DOCKER_COMPOSE
from ewok import Context
from invoke.exceptions import Exit
from rich import print as rprint
from rich.panel import Panel

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
PY4WEB_HTTP_ERROR_RE = re.compile(r'py4web\.core\.HTTP:\s*\((\d+),\s*["\'](.+?)["\']\)', flags=re.DOTALL)

type AnyDict = dict[str, t.Any]
type ResultParser = t.Callable[[str], AnyDict | None]


def _ui_error(message: str) -> None:
    rprint(Panel.fit(message, title="Error", border_style="red"))


def _parse_json_line(line: str) -> AnyDict | None:
    line = ANSI_ESCAPE_RE.sub("", line).strip()
    if not line:
        return None
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


def _extract_json(stdout: str) -> AnyDict:
    for line in reversed((stdout or "").splitlines()):
        if parsed := _parse_json_line(line):
            return parsed
    raise ValueError(f"No JSON payload found in output:\n{stdout}")


def _extract_py4web_http_error(output: str) -> tuple[int, str] | None:
    if not (match := PY4WEB_HTTP_ERROR_RE.search(output)):
        return None
    return int(match.group(1)), match.group(2).strip()


def parse_boolean_result(output: str) -> dict[str, bool] | None:
    """Recognize py4web CLI commands that print a bare Python boolean."""
    if "True" in output:
        return {"ok": True}
    if "False" in output:
        return {"ok": False}
    return None


def py4web_call(
    ctx: Context,
    fn: str,
    args: AnyDict | None = None,
    result_parser: ResultParser | None = None,
) -> AnyDict:
    """Call a py4web CLI helper inside the container and parse its JSON output."""
    args_json = shlex.quote(json.dumps(args or {}))
    call = f"py4web call apps admin.models.cli_support.{fn} --args {args_json}"
    commands = (
        f"{DOCKER_COMPOSE} exec -T py4web {call}",
        f"{DOCKER_COMPOSE} run --rm --no-deps -T py4web {call}",
    )

    failures: list[str] = []
    for command in commands:
        result = ctx.run(command, warn=True, hide=True)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)

        if http_error := _extract_py4web_http_error(output):
            code, message = http_error
            _ui_error(f"{message} (HTTP {code})")
            raise Exit(code=1)

        if not result.ok:
            failures.append(result.stderr or result.stdout or f"Command failed: {command}")
            continue

        if result_parser and (parsed := result_parser(output)):
            return parsed

        try:
            return _extract_json(output)
        except ValueError as error:
            failures.append(str(error))

    compact = "\n".join(
        line
        for line in "\n\n".join(failures).splitlines()
        if line.strip() and not line.strip().startswith("Container ")
    )
    _ui_error(compact or "Command failed")
    raise Exit(code=1)
