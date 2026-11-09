"""Production-mode error-page registration checks."""

import os
import subprocess
import sys
from pathlib import Path


def test_custom_5xx_renderer_is_registered_without_debug_mode() -> None:
    """Demo and production still need the shared 5xx page and error tickets."""
    env = {**os.environ, "PY4WEB_DEBUG_MODE": "0"}
    script = """
from common.controllers.error import error_renderer_5xx
from py4web_debug import tools
from py4web_debug.internals import patch_py4
import common

assert tools.enabled
assert patch_py4.renderer is error_renderer_5xx
"""
    result = subprocess.run(  # noqa: S603 - fixed in-file script, current interpreter
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
