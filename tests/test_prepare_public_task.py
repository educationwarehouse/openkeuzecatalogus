"""Tests for prepare_public task command assembly."""

import sys
from pathlib import Path

import invoke
import pytest
from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tasks


def test_prepare_public_builds_rsync_command(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """prepare_public should build rsync args from env and CLI flags."""
    fake_repo = tmp_path / "private-repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    public_repo = tmp_path / "openkeuzecatalogus"
    public_repo.mkdir(parents=True, exist_ok=True)

    (fake_repo / "py4web/apps/private_one").mkdir(parents=True, exist_ok=True)
    (fake_repo / "py4web/apps/private_two").mkdir(parents=True, exist_ok=True)
    (fake_repo / "py4web/apps/public_one").mkdir(parents=True, exist_ok=True)
    (fake_repo / "py4web/apps/private_one/secret.txt").write_text("private\n")
    (fake_repo / "py4web/apps/private_two/secret2.txt").write_text("private\n")
    (fake_repo / "py4web/apps/public_one/public.txt").write_text("public\n")

    monkeypatch.setattr(tasks, "__file__", str(fake_repo / "tasks.py"))  # needed for proper usage of inv
    monkeypatch.delenv("PUBLIC_TARGET", raising=False)
    monkeypatch.setenv("PRIVATE_APPS", "private_one,private_two")

    command = tasks.build_rsync_command(fake_repo, test=True, files=True)

    source = fake_repo.resolve()
    target = fake_repo.parent.resolve() / "openkeuzecatalogus"

    assert command.startswith("rsync -rnv ")
    assert "--exclude .git/ " in command
    assert "--exclude py4web/apps/private_one " in command
    assert "--exclude py4web/apps/private_two " in command
    assert "--filter=':- .gitignore'" in command
    assert f" {source}/ {target}" in command

    # note: different from ewok.Context (from fabric.Connection)
    #       since that requires a 'host'
    c = invoke.Context()
    tasks.prepare_public.body(c, test=False, files=True)

    captured = capsys.readouterr()

    assert (public_repo / "py4web/apps/public_one/public.txt").exists()
    assert not (public_repo / "py4web/apps/private_one/secret.txt").exists()
    assert not (public_repo / "py4web/apps/private_two/secret2.txt").exists()
    assert "public.txt" in captured.out
    assert "private_one" not in captured.out
    assert "private_two" not in captured.out
    assert captured.err == ""
