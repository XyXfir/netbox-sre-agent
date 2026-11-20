#!/usr/bin/env python3
"""Alert-driven entry point.

Feeds an Alertmanager webhook payload into the agent. No HTTP server required
for the demo: pass a JSON file, and the adapter converts fired alerts to a goal.

    python run_alert.py examples/alert_payload.json        # offline MockLLM
    USE_LIVE_LLM=1 python run_alert.py examples/alert_payload.json

To use as a real webhook handler, import `handle(payload)` from this module.
"""
from __future__ import annotations

import json
import os
import sys

from app.agent import SREAgent
from app.alerting import AlertAdapter
from app.backends import MockBackend
from app.llm import MockLLM, OpenAICompatLLM
from app.playbook import PlaybookLibrary
from app.tools import ToolRegistry

_adapter = AlertAdapter()   # module-level so dedupe persists across webhook calls


def handle(payload: str | dict, use_live_llm: bool = False, verbose: bool = True) -> dict:
    """Webhook handler: Alertmanager payload -> agent run result (or empty)."""
    alerts = _adapter.parse(payload)
    fresh, skipped = _adapter.dedupe(alerts)
    if not fresh:
        return {"ok": True, "skipped": len(skipped), "note": "all alerts deduplicated, no run"}
    goal = _adapter.to_goal(fresh)

    llm = OpenAICompatLLM() if use_live_llm else MockLLM()
    registry = ToolRegistry(MockBackend(), playbooks=PlaybookLibrary())
    agent = SREAgent(llm, registry, verbose=verbose)
    result = agent.run(goal)
    result["goal"] = goal
    result["skipped"] = len(skipped)
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python run_alert.py <alert_payload.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        payload = fh.read()

    live = os.environ.get("USE_LIVE_LLM", "").lower() in {"1", "true", "yes"}
    result = handle(payload, use_live_llm=live)
    print(f"\n=== TRIGGER GOAL ===\n{result.get('goal')}")
    print(f"\n=== FINAL ANSWER ===\n{result['answer']}")
    print(f"\nok={result['ok']} steps={result['steps']} skipped={result.get('skipped', 0)}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
