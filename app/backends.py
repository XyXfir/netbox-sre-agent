"""Backend adapters.

Two interchangeable implementations:
  * MockBackend  - in-memory, zero dependency, ships with seeded anomalies for the demo.
  * NetBoxBackend - real NetBox REST API + Docker CLI (used by run_live.py).

The agent and the tool layer never talk to either directly: everything goes
through the same method names, so the offline demo exercises the exact same
tool-calling loop as production.
"""
from __future__ import annotations

import ipaddress
import os
import subprocess
from typing import Any, Dict, List

import requests


# --------------------------------------------------------------------------- #
# Offline backend
# --------------------------------------------------------------------------- #
class MockBackend:
    """A small in-memory NetBox/Docker simulator with a deliberately dirty IPAM."""

    def __init__(self) -> None:
        self.prefixes: List[Dict[str, Any]] = [
            {"id": 1, "prefix": "10.42.7.0/24", "utilization": 94.0, "status": "active", "site": "bj-dc-01"},
            {"id": 2, "prefix": "10.42.8.0/24", "utilization": 31.0, "status": "active", "site": "bj-dc-01"},
            {"id": 3, "prefix": "10.42.9.0/24", "utilization": 12.0, "status": "active", "site": "sh-dc-02"},
        ]
        self.ips: List[Dict[str, Any]] = [
            {"id": 101, "address": "10.42.7.15/24", "status": "active", "assigned_object": "web-01",
             "description": "prod web node", "created": "2025-02-11", "tags": ["prod"]},
            # Rogue record: same address, no owner, no description, created recently.
            {"id": 102, "address": "10.42.7.15/24", "status": "active", "assigned_object": None,
             "description": "", "created": "2025-08-20", "tags": []},
            {"id": 103, "address": "10.42.7.16/24", "status": "active", "assigned_object": "web-02",
             "description": "prod web node", "created": "2025-02-11", "tags": ["prod"]},
            {"id": 104, "address": "10.42.8.10/24", "status": "reserved", "assigned_object": None,
             "description": "gateway", "created": "2025-03-01", "tags": []},
        ]
        self.devices = [
            {"id": 11, "name": "web-01", "status": "active", "site": "bj-dc-01"},
            {"id": 12, "name": "web-02", "status": "active", "site": "bj-dc-01"},
            {"id": 13, "name": "gw-01", "status": "active", "site": "bj-dc-01"},
        ]
        self.containers = [
            {"name": "netbox", "status": "Up 3 days (healthy)"},
            {"name": "netbox-postgres", "status": "Up 3 days (healthy)"},
            {"name": "netbox-redis", "status": "Up 3 days (healthy)"},
            {"name": "netbox-worker", "status": "Up 3 days (healthy)"},
        ]
        self.logs = {
            "netbox": "INFO  gunicorn ready\nINFO  GET /api/ipam/ip-addresses/ 200\nINFO  health check ok",
            "netbox-worker": "INFO  rq worker booted\nINFO  job ok\nINFO  heartbeat ok",
        }
        self.audit: List[Dict[str, Any]] = []

    # -- read ------------------------------------------------------------- #
    def health(self) -> Dict[str, Any]:
        return {"ok": True, "netbox_api": "reachable", "version": "mock-4.1", "containers": self.containers}

    def _duplicate_addresses(self) -> set:
        seen: Dict[str, int] = {}
        for ip in self.ips:
            seen[ip["address"]] = seen.get(ip["address"], 0) + 1
        return {addr for addr, n in seen.items() if n > 1}

    def list_prefixes(self, min_utilization: float = 0) -> List[Dict[str, Any]]:
        return [p for p in self.prefixes if p["utilization"] >= min_utilization]

    def list_ip_addresses(self, duplicate_only: bool = False, status: str | None = None) -> List[Dict[str, Any]]:
        dup = self._duplicate_addresses()
        return [i for i in self.ips
                if (not duplicate_only or i["address"] in dup)
                and (not status or i["status"] == status)]

    def get_ip_address(self, ip_id: int) -> Dict[str, Any] | None:
        return next((i for i in self.ips if i["id"] == ip_id), None)

    def list_devices(self, status: str | None = None) -> List[Dict[str, Any]]:
        return [d for d in self.devices if not status or d["status"] == status]

    def container_logs(self, container: str, lines: int = 50) -> str:
        text = self.logs.get(container, "no log lines available")
        return "\n".join(text.strip().splitlines()[-lines:])

    # -- write ------------------------------------------------------------ #
    def update_ip_status(self, ip_id: int, status: str) -> Dict[str, Any]:
        ip = self.get_ip_address(ip_id)
        if not ip:
            return {"ok": False, "error": f"IP id {ip_id} not found"}
        before = ip["status"]
        ip["status"] = status
        self.audit.append({"action": "update_ip_status", "target": ip_id, "before": before, "after": status})
        return {"ok": True, "id": ip_id, "before": before, "after": status}

    def add_ip_tag(self, ip_id: int, tag: str) -> Dict[str, Any]:
        ip = self.get_ip_address(ip_id)
        if not ip:
            return {"ok": False, "error": f"IP id {ip_id} not found"}
        ip.setdefault("tags", []).append(tag)
        self.audit.append({"action": "add_ip_tag", "target": ip_id, "tag": tag})
        return {"ok": True, "id": ip_id, "tags": ip["tags"]}

    def create_journal_entry(self, object_type: str, object_id: int, comment: str) -> Dict[str, Any]:
        entry = {"action": "journal", "object_type": object_type, "object_id": object_id, "comment": comment}
        self.audit.append(entry)
        return {"ok": True, **entry}

    def rollback_status(self, ip_id: int) -> Dict[str, Any]:
        """Restore status to the `before` value of the last recorded change."""
        record = next((r for r in reversed(self.audit)
                       if r.get("action") == "update_ip_status" and r.get("target") == ip_id), None)
        if not record:
            return {"ok": False, "error": f"no status change recorded for IP {ip_id}"}
        ip = self.get_ip_address(ip_id)
        if not ip:
            return {"ok": False, "error": f"IP id {ip_id} not found"}
        before, current = ip["status"], record["before"]
        ip["status"] = current
        self.audit.append({"action": "rollback", "target": ip_id, "before": before, "after": current})
        return {"ok": True, "id": ip_id, "restored_to": current, "from": before}

    def restart_container(self, container: str) -> Dict[str, Any]:
        self.audit.append({"action": "restart_container", "target": container})
        return {"ok": True, "container": container, "result": "restarted (mock)"}

    # -- verify ----------------------------------------------------------- #
    def verify_duplicate(self, address: str) -> Dict[str, Any]:
        active = [i for i in self.ips if i["address"] == address and i["status"] == "active"]
        return {"ok": True, "check": "duplicate_address", "address": address,
                "active_count": len(active), "resolved": len(active) <= 1}


# --------------------------------------------------------------------------- #
# Live backend
# --------------------------------------------------------------------------- #
class NetBoxBackend:
    """Real adapter. Env: NETBOX_URL, NETBOX_TOKEN (optional NETBOX_TIMEOUT)."""

    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: int = 20) -> None:
        self.base = (base_url or os.environ["NETBOX_URL"]).rstrip("/")
        token = token or os.environ["NETBOX_TOKEN"]
        self.headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
        self.timeout = timeout
        self.audit: List[Dict[str, Any]] = []

    # -- low level -------------------------------------------------------- #
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = requests.request(method, self.base + path, headers=self.headers,
                                timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _patch(self, path: str, payload: Dict[str, Any]) -> Any:
        return self._request("PATCH", path, json=payload)

    @staticmethod
    def _docker(*args: str) -> str:
        try:
            proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=20)
            return proc.stdout.strip() if proc.returncode == 0 else f"docker error: {proc.stderr.strip()}"
        except FileNotFoundError:
            return "docker CLI not available on this host"

    # -- read ------------------------------------------------------------- #
    def health(self) -> Dict[str, Any]:
        status = self._get("/api/status/")
        ps = self._docker("ps", "--format={{.Names}}|{{.Status}}")
        containers = [{"name": line.split("|")[0], "status": line.split("|")[-1]}
                      for line in ps.splitlines() if "|" in line]
        return {"ok": True, "netbox_api": "reachable", "version": status.get("version"),
                "containers": containers}

    def _estimate_utilization(self, prefix: Dict[str, Any]) -> float:
        try:
            net = ipaddress.ip_network(prefix["prefix"], strict=False)
            total = int(net.num_addresses)
            if total == 0:
                return 0.0
            avail_resp = self._get(f"/api/ipam/prefixes/{prefix['id']}/available-ips/", {"limit": 1})
            avail = int(avail_resp.get("count", 0)) if isinstance(avail_resp, dict) else 0
            return round((total - avail) / total * 100, 2)
        except Exception:
            return 0.0

    def list_prefixes(self, min_utilization: float = 0) -> List[Dict[str, Any]]:
        data = self._get("/api/ipam/prefixes/", {"limit": 1000}).get("results", [])
        out = []
        for p in data:
            util = p.get("utilization")
            if util is None:
                util = self._estimate_utilization(p)
            if float(util) >= min_utilization:
                out.append({"id": p["id"], "prefix": p["prefix"], "utilization": float(util),
                            "status": p.get("status"), "site": (p.get("site") or {}).get("name")})
        return out

    @staticmethod
    def _normalize_ip(i: Dict[str, Any]) -> Dict[str, Any]:
        status = i.get("status")
        if isinstance(status, dict):
            status = status.get("value")
        assigned = i.get("assigned_object")
        if isinstance(assigned, dict):
            assigned = assigned.get("display") or assigned.get("name")
        return {"id": i["id"], "address": i["address"], "status": status,
                "assigned_object": assigned, "description": i.get("description", ""),
                "created": i.get("created"), "tags": [t.get("name") if isinstance(t, dict) else t
                                                      for t in i.get("tags", [])]}

    def list_ip_addresses(self, duplicate_only: bool = False, status: str | None = None) -> List[Dict[str, Any]]:
        data = self._get("/api/ipam/ip-addresses/", {"limit": 5000}).get("results", [])
        rows = [self._normalize_ip(i) for i in data]
        counts: Dict[str, int] = {}
        for r in rows:
            counts[r["address"]] = counts.get(r["address"], 0) + 1
        dup = {a for a, n in counts.items() if n > 1}
        return [r for r in rows
                if (not duplicate_only or r["address"] in dup)
                and (not status or r["status"] == status)]

    def get_ip_address(self, ip_id: int) -> Dict[str, Any] | None:
        try:
            return self._normalize_ip(self._get(f"/api/ipam/ip-addresses/{ip_id}/"))
        except requests.HTTPError:
            return None

    def list_devices(self, status: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": 1000}
        if status:
            params["status"] = status
        data = self._get("/api/dcim/devices/", params).get("results", [])
        return [{"id": d["id"], "name": d["name"], "status": d.get("status"),
                 "site": (d.get("site") or {}).get("name")} for d in data]

    def container_logs(self, container: str, lines: int = 50) -> str:
        return self._docker("logs", "--tail", str(lines), container)

    # -- write ------------------------------------------------------------ #
    def update_ip_status(self, ip_id: int, status: str) -> Dict[str, Any]:
        before = self.get_ip_address(ip_id)
        result = self._patch(f"/api/ipam/ip-addresses/{ip_id}/", {"status": status})
        self.audit.append({"action": "update_ip_status", "target": ip_id,
                           "before": (before or {}).get("status"), "after": status})
        return {"ok": True, "id": ip_id, "status": (result.get("status") or {}).get("value", status)}

    def add_ip_tag(self, ip_id: int, tag: str) -> Dict[str, Any]:
        # NetBox requires the tag object to exist before it can be attached.
        try:
            self._request("POST", "/api/extras/tags/", json={"name": tag, "slug": tag})
        except requests.HTTPError:
            pass  # already exists
        result = self._patch(f"/api/ipam/ip-addresses/{ip_id}/", {"tags": [{"name": tag}]})
        self.audit.append({"action": "add_ip_tag", "target": ip_id, "tag": tag})
        return {"ok": True, "id": ip_id, "tags": [t.get("name") for t in result.get("tags", [])
                                                  if isinstance(t, dict)]}

    def create_journal_entry(self, object_type: str, object_id: int, comment: str) -> Dict[str, Any]:
        payload = {"assigned_object_type": object_type, "assigned_object_id": object_id,
                   "comment": comment}
        try:
            result = self._request("POST", "/api/extras/journal-entries/", json=payload)
            self.audit.append({"action": "journal", "object_type": object_type,
                               "object_id": object_id, "comment": comment})
            return {"ok": True, "id": result.get("id")}
        except requests.HTTPError as exc:
            return {"ok": False, "error": f"journal entry failed: {exc}"}

    def rollback_status(self, ip_id: int) -> Dict[str, Any]:
        """Restore status to the `before` value of the last recorded change."""
        record = next((r for r in reversed(self.audit)
                       if r.get("action") == "update_ip_status" and r.get("target") == ip_id), None)
        if not record:
            return {"ok": False, "error": f"no status change recorded for IP {ip_id}"}
        before = self.get_ip_address(ip_id)
        current = record.get("before")
        self._patch(f"/api/ipam/ip-addresses/{ip_id}/", {"status": current})
        self.audit.append({"action": "rollback", "target": ip_id,
                           "before": (before or {}).get("status"), "after": current})
        return {"ok": True, "id": ip_id, "restored_to": current,
                "from": (before or {}).get("status")}

    def restart_container(self, container: str) -> Dict[str, Any]:
        output = self._docker("restart", container)
        self.audit.append({"action": "restart_container", "target": container})
        return {"ok": not output.startswith("docker error"), "container": container, "result": output}

    # -- verify ----------------------------------------------------------- #
    def verify_duplicate(self, address: str) -> Dict[str, Any]:
        active = [i for i in self.list_ip_addresses() if i["address"] == address and i["status"] == "active"]
        return {"ok": True, "check": "duplicate_address", "address": address,
                "active_count": len(active), "resolved": len(active) <= 1}
