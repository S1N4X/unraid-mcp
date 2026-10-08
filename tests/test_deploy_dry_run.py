"""deploy/deploy.sh argument checks and --dry-run, with docker/ssh faked (#360)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SH = ROOT / "deploy" / "deploy.sh"
TARGET = "root@192.0.2.9"
STEPS = [
    "preflight",
    "build",
    "backup",
    "ship",
    "template",
    "secrets",
    "autostart",
    "rebuild",
    "verify",
]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not found")


@pytest.fixture
def fake_path(tmp_path: Path) -> str:
    """PATH whose docker and ssh fail loudly if anything calls them."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("docker", "ssh"):
        fake = bin_dir / tool
        fake.write_text(f'#!/bin/sh\necho "UNEXPECTED {tool} $*" >&2\nexit 99\n')
        fake.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _deploy(fake_path: str, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": fake_path, "MONOLITH": TARGET}
    return subprocess.run(
        ["bash", str(DEPLOY_SH), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_dry_run_calls_nothing_and_runs_steps_in_order(fake_path: str, tmp_path: Path) -> None:
    result = _deploy(fake_path, tmp_path, "--dry-run", "--backup-suffix", "20261008-360")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "UNEXPECTED" not in output
    assert TARGET in result.stdout
    steps = re.findall(r"^==> \[(\d)/9\] (\S+)$", result.stdout, re.MULTILINE)
    assert steps == [(str(i), name) for i, name in enumerate(STEPS, start=1)]
    # The two orderings the deploy depends on, checked on the actual output.
    names = [name for _, name in steps]
    assert names.index("backup") < names.index("ship")
    assert names.index("autostart") < names.index("rebuild")


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["--dry-run"], id="missing-suffix"),
        pytest.param(["--dry-run", "--backup-suffix", "a/b"], id="slash-suffix"),
    ],
)
def test_bad_suffix_is_a_usage_error(fake_path: str, tmp_path: Path, args: list[str]) -> None:
    result = _deploy(fake_path, tmp_path, *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "UNEXPECTED" not in result.stdout + result.stderr
