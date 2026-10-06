"""Tests for CLI edge cases, exit codes, and error reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner

from splitstitch.cli.main import app

runner = CliRunner()


def test_cli_help() -> None:
    """Verify CLI root help display and command availability."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "probe" in res.output
    assert "plan" in res.output
    assert "split" in res.output
    assert "verify" in res.output
    assert "stitch" in res.output
    assert "gui" in res.output


def test_cli_probe_missing_file(tmp_path: Path) -> None:
    """Verify probe on non-existent video exits with code 3."""
    missing = tmp_path / "does_not_exist.mp4"
    res = runner.invoke(app, ["probe", str(missing)])
    assert res.exit_code == 3
    assert "Error probing video" in res.output


def test_cli_plan_missing_file(tmp_path: Path) -> None:
    """Verify plan on non-existent video exits with code 4."""
    missing = tmp_path / "does_not_exist.mp4"
    res = runner.invoke(app, ["plan", "-i", str(missing), "-p", "free"])
    assert res.exit_code == 4
    assert "Planning failed" in res.output


def test_cli_plan_invalid_plan_name(tmp_path: Path) -> None:
    """Verify plan with invalid plan name reports error."""
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"mock")
    res = runner.invoke(app, ["plan", "-i", str(dummy), "-p", "super_nonexistent_plan"])
    assert res.exit_code in (3, 4)


def test_cli_verify_missing_manifest(tmp_path: Path) -> None:
    """Verify verify command on non-existent manifest fails with exit code 1."""
    missing_dir = tmp_path / "non_existent_session"
    res = runner.invoke(app, ["verify", "-s", str(missing_dir)])
    assert res.exit_code == 1
    assert "Verification failed" in res.output


def test_cli_stitch_missing_manifest(tmp_path: Path) -> None:
    """Verify stitch command on non-existent manifest fails with exit code 7."""
    missing_manifest = tmp_path / "non_existent.json"
    motion_dir = tmp_path / "motion"
    motion_dir.mkdir()
    out = tmp_path / "out.bvh"
    res = runner.invoke(app, ["stitch", "-m", str(missing_manifest), "-d", str(motion_dir), "-o", str(out)])
    assert res.exit_code == 7
    assert "Stitching error" in res.output


def test_cli_merge_alias_help() -> None:
    """Verify merge alias exists and accepts stitch options."""
    res = runner.invoke(app, ["merge", "--help"])
    assert res.exit_code == 0
    assert "--manifest" in res.output
    assert "--motion-dir" in res.output
    assert "--output" in res.output
