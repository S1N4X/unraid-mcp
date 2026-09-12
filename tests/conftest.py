"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
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


def make_ok_transport(data: Any = None) -> httpx.MockTransport:
    """Transport that returns ``{"data": data}`` for every request."""
    body = json.dumps({"data": data or {}}).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)
