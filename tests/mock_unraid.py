"""Mock Unraid GraphQL server using graphql-core execute against the real SDL."""

from __future__ import annotations

import json
from typing import Any

import httpx
from graphql import build_schema, graphql

from unraid_mcp.domains.health import load_snapshot_schema

# Root value stubs — one key per Query/Mutation top-level field.
ROOT: dict[str, Any] = {
    "info": {
        "id": "info:1",
        "time": "2026-09-12T10:00:00Z",
        "os": {
            "id": "os:1",
            "hostname": "tower",
            "platform": "linux",
            "distro": "Slackware",
            "release": "15.0",
            "kernel": "6.6.44-Unraid",
            "arch": "x86_64",
            "uptime": "1234567",
        },
        "cpu": {
            "id": "cpu:1",
            "manufacturer": "AMD",
            "brand": "Ryzen 9 5950X",
            "vendor": "AMD",
            "family": "25",
            "model": "Ryzen",
            "stepping": 0,
            "revision": "",
            "voltage": "1.1",
            "speed": 3400.0,
            "speedmin": 2200.0,
            "speedmax": 4900.0,
            "threads": 32,
            "cores": 16,
            "processors": 1,
            "socket": "AM4",
            "cache": {},
            "flags": ["sse4_2", "avx2"],
            "topology": [[[0, 1]]],
            "packages": {"id": "pkg:1", "totalPower": 65.0, "power": [65.0], "temp": [45.0]},
        },
        "memory": {
            "id": "mem:1",
            "layout": [
                {
                    "id": "memlayout:1",
                    "size": 34359738368,
                    "bank": "BANK0",
                    "type": "DDR4",
                    "clockSpeed": 3200,
                    "partNum": "CMK32GX4M2E3200C16",
                    "serialNum": "SN001",
                    "manufacturer": "Corsair",
                    "formFactor": "DIMM",
                    "voltageConfigured": 1200,
                    "voltageMin": 1100,
                    "voltageMax": 1300,
                }
            ],
        },
        "baseboard": {
            "id": "bb:1",
            "manufacturer": "ASRock",
            "model": "X570 Taichi",
            "version": "1.0",
            "serial": "SN-BB",
            "assetTag": "",
            "memMax": 128.0,
            "memSlots": 4.0,
        },
        "system": {
            "id": "sys:1",
            "manufacturer": "Custom",
            "model": "Tower",
            "version": "1.0",
            "serial": "SN-SYS",
            "uuid": "uuid-1",
            "sku": "",
            "virtual": False,
        },
        "devices": {"id": "dev:1", "gpu": [], "network": [], "pci": [], "usb": []},
        "display": {
            "id": "disp:1",
            "case": {"id": "case:1", "url": "", "icon": "", "error": "", "base64": ""},
            "theme": "azure",
            "unit": "CELSIUS",
            "scale": False,
            "tabs": False,
            "resize": False,
            "wwn": False,
            "total": False,
            "usage": False,
            "text": False,
            "warning": 60,
            "critical": 70,
            "hot": 50,
            "max": None,
            "locale": "en",
        },
        "machineId": "machine-1",
        "versions": {
            "id": "ver:1",
            "core": {"unraid": "7.3.2", "api": "4.35.1", "kernel": "6.6.44"},
            "packages": {
                "openssl": "3.1.4",
                "node": "20.11.0",
                "docker": "24.0.7",
                "php": "8.2.14",
                "nginx": "1.24.0",
                "git": "2.43.0",
                "npm": "10.2.4",
                "pm2": "5.3.0",
            },
        },
        "networkInterfaces": [],
        "primaryNetwork": None,
    },
    "server": {
        "id": "server:1",
        "name": "tower",
        "status": "ONLINE",
        "lanip": "192.168.1.100",
        "localurl": "http://tower.local",
        "owner": {"id": "profile:1", "username": "admin", "url": "", "avatar": ""},
        "guid": "guid-1",
        "apikey": "***",
        "comment": "",
        "wanip": "1.2.3.4",
        "remoteurl": "",
    },
    "systemTime": {
        "currentTime": "2026-09-12T10:00:00Z",
        "timeZone": "America/Toronto",
        "useNtp": True,
        "ntpServers": ["pool.ntp.org"],
    },
    "plugins": [
        {"name": "unraid-api", "version": "4.35.1", "hasApiModule": None, "hasCliModule": None},
        {"name": "dynamix", "version": "7.3.2", "hasApiModule": None, "hasCliModule": None},
    ],
    "vars": {
        "id": "vars:1",
        "version": "7.3.2",
        "name": "tower",
        "timeZone": "America/Toronto",
        "comment": "",
        "security": "simple",
        "workgroup": "WORKGROUP",
        "useSsl": False,
        "port": 80,
        "portssl": 443,
        "useSsh": True,
        "portssh": 22,
        "regTy": "PRO",
        "regState": "PRO",
        "regTo": "user@example.com",
        "mdState": "STARTED",
        "mdNumDisks": 4,
        "mdNumDisabled": 0,
        "mdNumInvalid": 0,
        "mdNumMissing": 0,
        "sbName": "parity1",
        "sbVersion": "2.9",
        "sbClean": True,
        "sbSynced": 100,
        "sbSyncErrs": 0,
    },
    "array": {
        "id": "array:1",
        "state": "STARTED",
        "capacity": {
            "kilobytes": {"free": "5000000", "used": "3000000", "total": "8000000"},
            "disks": {"free": "2", "used": "4", "total": "6"},
        },
        "parityCheckStatus": {
            "date": None,
            "duration": None,
            "speed": None,
            "status": "COMPLETED",
            "errors": 0,
            "progress": None,
            "correcting": False,
            "paused": False,
            "running": False,
        },
        "boot": None,
        "bootDevices": [],
        "disks": [
            {
                "id": "disk:1",
                "idx": 0,
                "name": "disk1",
                "device": "sda",
                "size": 4000000000000,
                "status": "DISK_OK",
                "rotational": True,
                "temp": 35,
                "numReads": 1000,
                "numWrites": 500,
                "numErrors": 0,
                "fsSize": 3900000000000,
                "fsFree": 1000000000000,
                "fsUsed": 2900000000000,
                "exportable": True,
                "type": "DATA",
                "warning": 45,
                "critical": 55,
                "fsType": "xfs",
                "comment": "",
                "format": "",
                "transport": "SATA",
                "color": "GREEN_ON",
                "isSpinning": True,
            },
        ],
        "parities": [
            {
                "id": "parity:1",
                "idx": 0,
                "name": "parity1",
                "device": "sdb",
                "size": 4000000000000,
                "status": "DISK_OK",
                "rotational": True,
                "temp": 33,
                "numReads": 2000,
                "numWrites": 1000,
                "numErrors": 0,
                "type": "PARITY",
                "color": "GREEN_ON",
            },
        ],
        "caches": [
            {
                "id": "cache:1",
                "idx": 0,
                "name": "cache",
                "device": "nvme0n1",
                "size": 500000000000,
                "status": "DISK_OK",
                "rotational": False,
                "temp": 40,
                "fsSize": 480000000000,
                "fsFree": 200000000000,
                "fsUsed": 280000000000,
                "type": "CACHE",
                "fsType": "btrfs",
                "color": "GREEN_ON",
            },
        ],
    },
    "parityHistory": [
        {
            "date": "2026-09-01T00:00:00Z",
            "duration": 3600,
            "speed": "100 MB/s",
            "status": "COMPLETED",
            "errors": 0,
            "correcting": False,
        },
    ],
    "docker": {
        "id": "docker:1",
        "containers": [
            {
                "id": "container:abc123",
                "names": ["/plex"],
                "image": "plexinc/pms-docker:latest",
                "imageId": "sha256:abc",
                "command": "/init",
                "created": 1694500000,
                "ports": [
                    {"ip": "0.0.0.0", "privatePort": 32400, "publicPort": 32400, "type": "TCP"}
                ],
                "lanIpPorts": None,
                "sizeRootFs": None,
                "sizeRw": None,
                "sizeLog": None,
                "labels": {},
                "state": "RUNNING",
                "status": "Up 2 days",
                "hostConfig": {"networkMode": "bridge"},
                "networkSettings": None,
                "mounts": None,
                "autoStart": True,
                "autoStartOrder": None,
                "autoStartWait": None,
                "templatePath": None,
                "projectUrl": None,
                "registryUrl": None,
                "supportUrl": "https://plex.tv",
                "iconUrl": "https://plex.tv/icon.png",
                "webUiUrl": "http://tower:32400/web",
                "shell": None,
                "templatePorts": None,
                "isOrphaned": False,
                "isUpdateAvailable": False,
                "isRebuildReady": None,
                "tailscaleEnabled": False,
                "tailscaleStatus": None,
            },
        ],
        "networks": [
            {
                "id": "net:bridge",
                "name": "bridge",
                "created": "2026-01-01",
                "scope": "local",
                "driver": "bridge",
                "enableIPv6": False,
                "ipam": {},
                "internal": False,
                "attachable": False,
                "ingress": False,
                "configFrom": {},
                "configOnly": False,
                "containers": {},
                "options": {},
                "labels": {},
            }
        ],
        "portConflicts": {"containerPorts": [], "lanPorts": []},
        "containerUpdateStatuses": [
            {"name": "plex", "updateStatus": "UP_TO_DATE"},
        ],
    },
    "vms": {
        "id": "vms:1",
        "domains": [
            {"id": "vm:win10", "name": "Windows 10", "state": "SHUTOFF", "uuid": "uuid-vm1"},
        ],
        "domain": [
            {"id": "vm:win10", "name": "Windows 10", "state": "SHUTOFF", "uuid": "uuid-vm1"},
        ],
    },
    "shares": [
        {
            "id": "share:appdata",
            "name": "appdata",
            "free": 200000000000,
            "used": 50000000000,
            "size": 250000000000,
            "include": [],
            "exclude": [],
            "cache": True,
            "nameOrig": "appdata",
            "comment": "Application data",
            "allocator": "highwater",
            "splitLevel": "",
            "floor": "",
            "cow": "auto",
            "color": "",
            "luksStatus": "",
        },
        {
            "id": "share:media",
            "name": "media",
            "free": 1000000000000,
            "used": 2000000000000,
            "size": 3000000000000,
            "include": [],
            "exclude": [],
            "cache": False,
            "nameOrig": "media",
            "comment": "Media files",
            "allocator": "highwater",
            "splitLevel": "",
            "floor": "",
            "cow": "auto",
            "color": "",
            "luksStatus": "",
        },
    ],
    "notifications": {
        "id": "notif:1",
        "overview": {
            "unread": {"info": 2, "warning": 1, "alert": 0, "total": 3},
            "archive": {"info": 10, "warning": 5, "alert": 1, "total": 16},
        },
        "warningsAndAlerts": [],
    },
    "metrics": {
        "id": "metrics:1",
        "cpu": {
            "id": "cpu-util:1",
            "percentTotal": 15.5,
            "cpus": [
                {
                    "percentTotal": 15.5,
                    "percentUser": 10.0,
                    "percentSystem": 3.0,
                    "percentNice": 0.0,
                    "percentIdle": 84.5,
                    "percentIrq": 0.5,
                    "percentGuest": 0.0,
                    "percentSteal": 0.0,
                }
            ],
        },
        "memory": {
            "id": "mem-util:1",
            "total": 68719476736,
            "used": 34359738368,
            "free": 17179869184,
            "available": 34359738368,
            "active": 17179869184,
            "buffcache": 17179869184,
            "percentTotal": 50.0,
            "swapTotal": 0,
            "swapUsed": 0,
            "swapFree": 0,
            "percentSwapTotal": 0.0,
        },
        "temperature": {
            "id": "temp:1",
            "sensors": [
                {
                    "id": "sensor:cpu0",
                    "name": "CPU Package",
                    "type": "CPU_PACKAGE",
                    "location": "CPU",
                    "current": {
                        "value": 45.0,
                        "unit": "CELSIUS",
                        "timestamp": "2026-09-12T10:00:00Z",
                        "status": "NORMAL",
                    },
                    "min": None,
                    "max": None,
                    "warning": 80.0,
                    "critical": 100.0,
                    "history": None,
                },
            ],
            "summary": {
                "average": 45.0,
                "hottest": {
                    "id": "sensor:cpu0",
                    "name": "CPU Package",
                    "type": "CPU_PACKAGE",
                    "location": "CPU",
                    "current": {
                        "value": 45.0,
                        "unit": "CELSIUS",
                        "timestamp": "2026-09-12T10:00:00Z",
                        "status": "NORMAL",
                    },
                    "min": None,
                    "max": None,
                    "warning": 80.0,
                    "critical": 100.0,
                    "history": None,
                },
                "coolest": {
                    "id": "sensor:cpu0",
                    "name": "CPU Package",
                    "type": "CPU_PACKAGE",
                    "location": "CPU",
                    "current": {
                        "value": 45.0,
                        "unit": "CELSIUS",
                        "timestamp": "2026-09-12T10:00:00Z",
                        "status": "NORMAL",
                    },
                    "min": None,
                    "max": None,
                    "warning": 80.0,
                    "critical": 100.0,
                    "history": None,
                },
                "warningCount": 0,
                "criticalCount": 0,
            },
        },
        "network": [
            {
                "id": "net-metric:eth0",
                "name": "eth0",
                "operstate": "up",
                "bytesReceived": 1000000,
                "bytesSent": 500000,
                "packetsReceived": 10000,
                "packetsSent": 5000,
                "receiveErrors": 0,
                "transmitErrors": 0,
                "receiveDropped": 0,
                "transmitDropped": 0,
                "rxSec": 1000.0,
                "txSec": 500.0,
                "utilizationPercent": 1.5,
                "lastUpdated": "2026-09-12T10:00:00Z",
            }
        ],
    },
    "upsDevices": [
        {
            "id": "ups:1",
            "name": "UPS1",
            "model": "APC 1500",
            "status": "OL",
            "battery": {"chargeLevel": 100, "estimatedRuntime": 60, "health": "Good"},
            "power": {
                "inputVoltage": 120.0,
                "outputVoltage": 120.0,
                "loadPercentage": 25,
                "nominalPower": 900,
                "currentPower": 225.0,
            },
        }
    ],
    "logFiles": [
        {"name": "syslog", "path": "/var/log/syslog", "size": 102400, "modifiedAt": "2026-09-12"},
    ],
    "logFile": {
        "path": "/var/log/syslog",
        "content": "Sep 12 10:00:00 tower kernel: test line",
        "totalLines": 1,
        "startLine": 1,
    },
}


def _build_schema_with_resolvers():  # type: ignore[no-untyped-def]
    """Build schema and attach resolvers for fields that take arguments."""
    sdl = load_snapshot_schema()
    schema = build_schema(sdl)

    # Docker.logs(id, since, tail) -> DockerContainerLogs
    docker_type = schema.type_map.get("Docker")
    if docker_type and hasattr(docker_type, "fields"):
        logs_field = docker_type.fields.get("logs")  # type: ignore[union-attr]
        if logs_field:
            logs_field.resolve = lambda obj, info, **kwargs: {  # type: ignore[attr-defined]
                "containerId": kwargs.get("id", "unknown"),
                "lines": [{"timestamp": "2026-09-12T10:00:00Z", "message": "test log line"}],
                "cursor": None,
            }

        # Docker.container(id) -> DockerContainer
        container_field = docker_type.fields.get("container")  # type: ignore[union-attr]
        if container_field:

            def resolve_container(obj: Any, info: Any, **kwargs: Any) -> Any:
                cid = kwargs.get("id", "")
                containers = obj.get("containers", []) if isinstance(obj, dict) else []
                for c in containers:
                    if isinstance(c, dict) and c.get("id") == cid:
                        return c
                return None

            container_field.resolve = resolve_container  # type: ignore[attr-defined]

    # Notifications.list(filter) -> [Notification!]!
    notifications_type = schema.type_map.get("Notifications")
    if notifications_type and hasattr(notifications_type, "fields"):
        list_field = notifications_type.fields.get("list")  # type: ignore[union-attr]
        if list_field:
            list_field.resolve = lambda obj, info, **kwargs: [  # type: ignore[attr-defined]
                {
                    "id": "notif:msg1",
                    "title": "Array Started",
                    "subject": "Array",
                    "description": "Array started successfully",
                    "importance": "INFO",
                    "link": None,
                    "type": "UNREAD",
                    "timestamp": "2026-09-12T08:00:00Z",
                    "formattedTimestamp": "Sep 12 08:00",
                }
            ]

    # Query.logFile(path, lines, startLine) -> LogFileContent
    query_type = schema.query_type
    if query_type:
        logfile_field = query_type.fields.get("logFile")
        if logfile_field:
            logfile_field.resolve = lambda obj, info, **kwargs: {  # type: ignore[attr-defined]
                "path": kwargs.get("path", "/var/log/syslog"),
                "content": "Sep 12 10:00:00 tower kernel: test line",
                "totalLines": 1,
                "startLine": 1,
            }

    # Mutation resolvers
    mutation_type = schema.mutation_type
    if mutation_type:
        # array -> ArrayMutations
        array_field = mutation_type.fields.get("array")
        if array_field:
            array_field.resolve = lambda obj, info: _MutationNamespace("array")  # type: ignore[attr-defined]

        # parityCheck -> ParityCheckMutations
        parity_field = mutation_type.fields.get("parityCheck")
        if parity_field:
            parity_field.resolve = lambda obj, info: _MutationNamespace("parityCheck")  # type: ignore[attr-defined]

        # docker -> DockerMutations
        docker_field = mutation_type.fields.get("docker")
        if docker_field:
            docker_field.resolve = lambda obj, info: _MutationNamespace("docker")  # type: ignore[attr-defined]

        # vm -> VmMutations
        vm_field = mutation_type.fields.get("vm")
        if vm_field:
            vm_field.resolve = lambda obj, info: _MutationNamespace("vm")  # type: ignore[attr-defined]

        # archiveNotification, unreadNotification, archiveAll
        for fname in ["archiveNotification", "unreadNotification", "archiveAll"]:
            f = mutation_type.fields.get(fname)
            if f:
                f.resolve = _make_mutation_resolver(fname)  # type: ignore[attr-defined]

    # ArrayMutations type resolvers
    array_mutations = schema.type_map.get("ArrayMutations")
    if array_mutations and hasattr(array_mutations, "fields"):
        ss = array_mutations.fields.get("setState")  # type: ignore[union-attr]
        if ss:
            ss.resolve = lambda obj, info, **kw: {"id": "array:1", "state": "STARTED"}  # type: ignore[attr-defined]

    # ParityCheckMutations type resolvers
    parity_mutations = schema.type_map.get("ParityCheckMutations")
    if parity_mutations and hasattr(parity_mutations, "fields"):
        for name in ["start", "pause", "resume", "cancel"]:
            f = parity_mutations.fields.get(name)  # type: ignore[union-attr]
            if f:
                f.resolve = lambda obj, info, **kw: "{}"  # type: ignore[attr-defined]

    # DockerMutations type resolvers
    docker_mutations = schema.type_map.get("DockerMutations")
    if docker_mutations and hasattr(docker_mutations, "fields"):
        for name, state, status in [
            ("start", "RUNNING", "Up 1 second"),
            ("stop", "EXITED", "Exited (0)"),
            ("pause", "PAUSED", "Paused"),
            ("unpause", "RUNNING", "Up 1 second"),
        ]:
            f = docker_mutations.fields.get(name)  # type: ignore[union-attr]
            if f:
                f.resolve = _make_docker_mutation_resolver(state, status)  # type: ignore[attr-defined]

    # VmMutations type resolvers
    vm_mutations = schema.type_map.get("VmMutations")
    if vm_mutations and hasattr(vm_mutations, "fields"):
        for name in ["start", "stop", "pause", "resume", "forceStop", "reboot", "reset"]:
            f = vm_mutations.fields.get(name)  # type: ignore[union-attr]
            if f:
                f.resolve = lambda obj, info, **kw: True  # type: ignore[attr-defined]

    return schema


class _MutationNamespace:
    """Dummy object for nested mutation resolution."""

    def __init__(self, name: str) -> None:
        self._name = name


def _make_mutation_resolver(fname: str):  # type: ignore[no-untyped-def]
    stubs: dict[str, Any] = {
        "archiveNotification": lambda obj, info, **kw: {
            "id": kw.get("id", "notif:msg1"),
            "title": "Array Started",
            "subject": "Array",
            "description": "Archived",
            "importance": "INFO",
            "type": "ARCHIVE",
            "link": None,
            "timestamp": None,
            "formattedTimestamp": None,
        },
        "unreadNotification": lambda obj, info, **kw: {
            "id": kw.get("id", "notif:msg1"),
            "title": "Array Started",
            "subject": "Array",
            "description": "Unread",
            "importance": "INFO",
            "type": "UNREAD",
            "link": None,
            "timestamp": None,
            "formattedTimestamp": None,
        },
        "archiveAll": lambda obj, info, **kw: {
            "unread": {"info": 0, "warning": 0, "alert": 0, "total": 0},
            "archive": {"info": 12, "warning": 6, "alert": 1, "total": 19},
        },
    }
    return stubs[fname]


def _make_docker_mutation_resolver(state: str, status: str):  # type: ignore[no-untyped-def]
    def resolve(obj: Any, info: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": kwargs.get("id", "container:abc123"),
            "names": ["/plex"],
            "image": "plexinc/pms-docker:latest",
            "imageId": "sha256:abc",
            "command": "/init",
            "created": 1694500000,
            "ports": [],
            "lanIpPorts": None,
            "sizeRootFs": None,
            "sizeRw": None,
            "sizeLog": None,
            "labels": {},
            "state": state,
            "status": status,
            "hostConfig": {"networkMode": "bridge"},
            "networkSettings": None,
            "mounts": None,
            "autoStart": True,
            "autoStartOrder": None,
            "autoStartWait": None,
            "templatePath": None,
            "projectUrl": None,
            "registryUrl": None,
            "supportUrl": None,
            "iconUrl": None,
            "webUiUrl": None,
            "shell": None,
            "templatePorts": None,
            "isOrphaned": False,
            "isUpdateAvailable": False,
            "isRebuildReady": None,
            "tailscaleEnabled": False,
            "tailscaleStatus": None,
        }

    return resolve


_SCHEMA = _build_schema_with_resolvers()


async def _execute_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a query against the mock schema."""
    result = await graphql(
        _SCHEMA,
        query,
        root_value=ROOT,
        variable_values=variables,
    )
    response: dict[str, Any] = {}
    if result.data is not None:
        response["data"] = result.data
    if result.errors:
        response["errors"] = [
            {"message": str(e), "extensions": {"code": "UPSTREAM_ERROR"}} for e in result.errors
        ]
    return response


def make_transport() -> httpx.MockTransport:
    """Return an httpx.MockTransport wired to the mock GraphQL server."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body.get("query", "")
        variables = body.get("variables")
        result = await _execute_graphql(query, variables)
        return httpx.Response(200, json=result)

    return httpx.MockTransport(handler)
