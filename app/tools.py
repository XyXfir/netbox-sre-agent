"""Tool schema definitions, registry and execution guardrails.

Schemas follow the OpenAI / Chat Completions `tools` format so the exact same
list can be handed to Qwen, GPT, Claude (via compatible endpoint), etc.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from .backends import MockBackend, NetBoxBackend

Backend = MockBackend | NetBoxBackend

WRITE_TOOLS = {"update_ip_status", "add_ip_tag", "create_journal_entry", "restart_container"}


def _fn(name: str, description: str, properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _fn("get_system_health",
        "Check NetBox API reachability and the status of all Docker containers in the NetBox Docker stack.",
        {}),
    _fn("list_prefixes",
        "List NetBox IP prefixes whose utilization is >= min_utilization. Use this to find address exhaustion risks.",
        {"min_utilization": {"type": "number", "description": "Minimum utilization percentage, e.g. 85"}}),
    _fn("list_ip_addresses",
        "List IP addresses from NetBox. Set duplicate_only=true to return only addresses recorded more than once.",
        {"duplicate_only": {"type": "boolean", "description": "Only return duplicated addresses"},
         "status": {"type": "string", "description": "Optional status filter, e.g. active / reserved"}}),
    _fn("get_ip_address",
        "Get full details of one IP address by its numeric NetBox id.",
        {"ip_id": {"type": "integer", "description": "NetBox IP address id"}}, ["ip_id"]),
    _fn("list_devices",
        "List devices registered in NetBox, optionally filtered by status.",
        {"status": {"type": "string", "description": "Optional status filter"}}),
    _fn("get_container_logs",
        "Read the tail of a Docker container's logs. Use it to rule in/out container-level faults.",
        {"container": {"type": "string", "description": "Container name, e.g. netbox"},
         "lines": {"type": "integer", "description": "Number of trailing log lines (default 50)"}}, ["container"]),
    _fn("update_ip_status",
        "WRITE. Change the status of an IP address, e.g. mark a stale record as reserved or deprecated.",
        {"ip_id": {"type": "integer", "description": "NetBox IP address id"},
         "status": {"type": "string", "description": "Target status: active / reserved / deprecated"}},
        ["ip_id", "status"]),
    _fn("add_ip_tag",
        "WRITE. Attach a tag to an IP address for traceability.",
        {"ip_id": {"type": "integer", "description": "NetBox IP address id"},
         "tag": {"type": "string", "description": "Tag name"}}, ["ip_id", "tag"]),
    _fn("create_journal_entry",
        "WRITE. Append an audit/journal note to a NetBox object explaining why a change was made.",
        {"object_type": {"type": "string", "description": "NetBox object type, e.g. ipam.ipaddress"},
         "object_id": {"type": "integer", "description": "Object id"},
         "comment": {"type": "string", "description": "What was found and what was done"}},
        ["object_type", "object_id", "comment"]),
    _fn("verify_remediation",
        "Re-run a check after a write action to confirm the incident is actually resolved.",
        {"check": {"type": "string", "description": "Check name, currently: duplicate_address"},
         "address": {"type": "string", "description": "Address to verify, e.g. 10.42.7.15/24"}},
        ["check", "address"]),
    _fn("restart_container",
        "WRITE. Restart one Docker container of the NetBox stack. Only use when logs show a container-level fault.",
        {"container": {"type": "string", "description": "Container name"}}, ["container"]),
]


class ToolRegistry:
    """Executes a tool call; enforces dry-run, allowlist and an append-only audit log."""

    def __init__(self, backend: Backend, dry_run: bool = False, allowed_write_tools: set[str] | None = None) -> None:
        self.backend = backend
        self.dry_run = dry_run
        self.allowed_write_tools = set(WRITE_TOOLS) if allowed_write_tools is None else set(allowed_write_tools)
        self.audit: List[Dict[str, Any]] = []

    def schemas(self) -> List[Dict[str, Any]]:
        return TOOL_SCHEMAS

    @staticmethod
    def _ok(data: Any) -> str:
        return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)

    def execute(self, name: str, arguments: Any) -> str:
        """Return a JSON string, which is what the `role=tool` message expects."""
        try:
            args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
        except (ValueError, TypeError) as exc:
            return json.dumps({"ok": False, "error": f"invalid arguments: {exc}"}, ensure_ascii=False)

        handler = self._handlers().get(name)
        if handler is None:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"}, ensure_ascii=False)

        if name in WRITE_TOOLS:
            if name not in self.allowed_write_tools:
                return json.dumps({"ok": False, "error": f"tool {name} is not in the write allowlist"},
                                  ensure_ascii=False)
            if self.dry_run:
                record = {"dry_run": True, "tool": name, "args": args}
                self.audit.append(record)
                return json.dumps({"ok": True, "dry_run": True, "would_call": name, "args": args},
                                  ensure_ascii=False)

        try:
            result = handler(**args)
            if isinstance(result, str):
                return result
            if name in WRITE_TOOLS:
                self.audit.append({"tool": name, "args": args, "result": result})
            return self._ok(result)
        except TypeError as exc:
            return json.dumps({"ok": False, "error": f"bad arguments for {name}: {exc}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - tool errors must reach the LLM as data, not crash the loop
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)

    def _handlers(self) -> Dict[str, Callable[..., Any]]:
        b = self.backend

        def verify(check: str, address: str) -> Any:
            if check != "duplicate_address":
                return {"ok": False, "error": f"unsupported check: {check}"}
            return b.verify_duplicate(address)

        return {
            "get_system_health": b.health,
            "list_prefixes": b.list_prefixes,
            "list_ip_addresses": b.list_ip_addresses,
            "get_ip_address": b.get_ip_address,
            "list_devices": b.list_devices,
            "get_container_logs": b.container_logs,
            "update_ip_status": b.update_ip_status,
            "add_ip_tag": b.add_ip_tag,
            "create_journal_entry": b.create_journal_entry,
            "verify_remediation": verify,
            "restart_container": b.restart_container,
        }
