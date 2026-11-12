"""Selection of the opt-in test-suite optimizations and the RAM compose overlay."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_TASKS_PATH = Path(__file__).parents[1] / "test.tasks.py"
TEST_TASKS_SPEC = importlib.util.spec_from_file_location("test_tasks", TEST_TASKS_PATH)
assert TEST_TASKS_SPEC is not None
assert TEST_TASKS_SPEC.loader is not None
test_tasks = importlib.util.module_from_spec(TEST_TASKS_SPEC)
sys.modules[TEST_TASKS_SPEC.name] = test_tasks
TEST_TASKS_SPEC.loader.exec_module(test_tasks)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("none", set()),
        (" None ", set()),
        ("ram", {"ram"}),
        ("RAM, template", {"ram", "template"}),
        ("ram,template,startup", {"ram", "template", "startup"}),
    ],
)
def test_explicit_optimizations_are_normalized(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: set[str]
) -> None:
    """Names are case-insensitive, may carry whitespace, and `none` disables everything."""
    monkeypatch.setenv("TEST_OPTIMIZATIONS", configured)

    assert test_tasks.enabled_test_optimizations() == expected


@pytest.mark.parametrize("configured", ["", "ram,", "fast", "none,ram"])
def test_invalid_optimizations_are_rejected(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    """Empty entries, unknown names and `none` combined with others fail with the accepted values."""
    monkeypatch.setenv("TEST_OPTIMIZATIONS", configured)

    with pytest.raises(ValueError, match="ram, template, startup"):
        test_tasks.enabled_test_optimizations()


@pytest.mark.parametrize(("state", "expected"), [("ONT", {"ram", "template"}), ("TEST", set()), ("", set())])
def test_unset_optimizations_default_to_ram_and_template_only_on_development_hosts(
    monkeypatch: pytest.MonkeyPatch, state: str, expected: set[str]
) -> None:
    """Without an explicit setting, only development hosts opt in."""
    monkeypatch.delenv("TEST_OPTIMIZATIONS", raising=False)
    monkeypatch.setenv("STATE_OF_DEVELOPMENT", state)

    assert test_tasks.enabled_test_optimizations() == expected


def test_ram_overlay_keeps_the_default_override_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit -f flags would skip docker-compose.override.yml, so the overlay list includes it."""
    monkeypatch.delenv("COMPOSE_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert test_tasks.ram_compose_files() == ["docker-compose.yml", "docker-compose.test-ram.yml"]

    (tmp_path / "docker-compose.override.yml").write_text("services: {}\n")

    assert test_tasks.ram_compose_files() == [
        "docker-compose.yml",
        "docker-compose.override.yml",
        "docker-compose.test-ram.yml",
    ]


def test_ram_overlay_keeps_configured_compose_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured COMPOSE_FILE replaces the defaults, and the RAM overlay is appended last."""
    monkeypatch.setenv("COMPOSE_FILE", os.pathsep.join(["base.yml", "local.yml"]))
    monkeypatch.delenv("COMPOSE_PATH_SEPARATOR", raising=False)

    assert test_tasks.ram_compose_files() == ["base.yml", "local.yml", "docker-compose.test-ram.yml"]
