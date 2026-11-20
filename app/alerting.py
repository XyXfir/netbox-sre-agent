"""Alertmanager webhook -> agent goal adapter with deduplication.

Prometheus/Alertmanager POSTs a JSON payload describing fired alerts. This
module converts that into a natural-language goal for SREAgent and keeps a
fingerprint cache so the same alert does not trigger repeated investigations.
No web framework needed: the entry point accepts a payload dict or JSON string.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


class AlertAdapter:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    @staticmethod
    def fingerprint(alert: Dict[str, Any]) -> str:
        labels = alert.get("labels", {})
        # stable identity: alert name + the object it concerns
        key = " | ".join(f"{k}={labels.get(k)}" for k in ("alertname", "ip", "prefix", "container")
                         if labels.get(k))
        return key or json.dumps(labels, sort_keys=True)

    def parse(self, payload: str | Dict[str, Any]) -> List[Dict[str, Any]]:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return [a for a in data.get("alerts", []) if a.get("status") == "firing"]

    def dedupe(self, alerts: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
        fresh: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for a in alerts:
            fp = self.fingerprint(a)
            if fp in self.seen:
                skipped.append(fp)
            else:
                fresh.append(a)
                self.seen.add(fp)
        return fresh, skipped

    @staticmethod
    def to_goal(alerts: List[Dict[str, Any]]) -> str:
        lines = ["以下告警触发了巡检，请定位根因、执行安全的处置并验证："]
        for a in alerts:
            labels = a.get("labels", {})
            ann = a.get("annotations", {})
            name = labels.get("alertname", "unknown")
            detail = ann.get("summary") or ann.get("description") or ""
            ctx = ", ".join(f"{k}={v}" for k, v in labels.items()
                            if k not in ("alertname", "severity"))
            lines.append(f"  - {name} [{labels.get('severity', 'n/a')}] {detail} ({ctx})")
        return "\n".join(lines)
