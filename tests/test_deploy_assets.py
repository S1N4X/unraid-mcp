"""Static checks tying deploy/ and the Dockerfile together (#360) — no network."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "deploy" / "my-unraid-mcp.xml"
DEPLOY_SH = ROOT / "deploy" / "deploy.sh"
DOCKERFILE = ROOT / "Dockerfile"


@pytest.fixture(scope="module")
def container() -> ET.Element:
    return ET.parse(TEMPLATE).getroot()


@pytest.fixture(scope="module")
def config(container: ET.Element) -> dict[str, ET.Element]:
    return {c.attrib["Name"]: c for c in container.iter("Config")}


def _variable(config: dict[str, ET.Element], name: str) -> str:
    element = config[name]
    assert element.attrib["Type"] == "Variable"
    return (element.text or "").strip()


def _deploy_bind() -> str:
    match = re.search(r"^readonly BIND=(\S+)$", DEPLOY_SH.read_text(), re.MULTILINE)
    assert match, "readonly BIND=... not found in deploy/deploy.sh"
    return match.group(1)


def test_host_network_without_fixed_ip(container: ET.Element) -> None:
    assert container.findtext("Network") == "host"
    assert container.find("MyIP") is None


def test_bind_matches_deploy_script(config: dict[str, ET.Element]) -> None:
    host = _variable(config, "MCP_HOST")
    port = _variable(config, "MCP_PORT")
    assert f"{host}:{port}" == _deploy_bind()
    assert host != "0.0.0.0"
    assert _variable(config, "MCP_ALLOWED_HOSTS") == host


def test_extra_params_harden_the_container(container: ET.Element) -> None:
    params = (container.findtext("ExtraParams") or "").split()
    joined = " ".join(params)
    assert "--user 10078:10078" in joined
    assert "--read-only" in params
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined


def test_config_mounted_read_only(config: dict[str, ET.Element]) -> None:
    mount = config["Config"]
    assert mount.attrib["Type"] == "Path"
    assert mount.attrib["Target"] == "/config"
    assert mount.attrib["Mode"] == "ro"


def test_no_legacy_variables(config: dict[str, ET.Element]) -> None:
    targets = {c.attrib.get("Target", "") for c in config.values()} | set(config)
    assert "UNRAID_HOST" not in targets
    assert not [t for t in targets if t.startswith("FASTMCP_")]


def _dockerfile_env(text: str) -> str:
    """The ENV instruction with its continuation lines."""
    match = re.search(r"^ENV (?:.*\\\n)*.*$", text, re.MULTILINE)
    assert match, "ENV instruction not found in Dockerfile"
    return match.group(0)


def test_dockerfile_runs_non_root_without_bind_default() -> None:
    text = DOCKERFILE.read_text()
    assert re.search(r"^USER 10078:10078$", text, re.MULTILINE)
    assert "FASTMCP_HOST" not in text
    env = _dockerfile_env(text)
    assert "PYTHONDONTWRITEBYTECODE=1" in env
    for var in ("MCP_HOST", "MCP_PORT", "FASTMCP_PORT"):
        assert not re.search(rf"\b{var}=", env), var


def test_dockerfile_cmd_runs_venv_python() -> None:
    # `uv run` writes a cache, which fails on the --read-only root.
    cmds = re.findall(r"^CMD .*$", DOCKERFILE.read_text(), re.MULTILINE)
    assert cmds == ['CMD ["/app/.venv/bin/python", "-m", "unraid_mcp"]']
