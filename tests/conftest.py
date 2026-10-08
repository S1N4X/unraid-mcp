"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from unraid_mcp.settings import Settings

MINIMAL_ENV = {"UNRAID_API_KEY": "test-key", "UNRAID_HOST": "tower.local"}


@pytest.fixture()
def read_only_settings() -> Settings:
    return Settings.from_env(MINIMAL_ENV)


@pytest.fixture()
def write_settings() -> Settings:
    return Settings.from_env({**MINIMAL_ENV, "UNRAID_ALLOW_WRITES": "true"})


@pytest.fixture()
def make_secret_file(tmp_path: Path) -> Callable[..., str]:
    """Factory writing *content* to a file with *mode*; returns its absolute path."""

    def _make(content: str, mode: int = 0o600, name: str = "secret") -> str:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        os.chmod(path, mode)
        return str(path.resolve())

    return _make


def make_ok_transport(data: Any = None) -> httpx.MockTransport:
    """Transport that returns ``{"data": data}`` for every request."""
    body = json.dumps({"data": data or {}}).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)
