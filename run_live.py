#!/usr/bin/env python3
"""Live mode: real NetBox REST API + real LLM function calling.

    cp .env.example .env     # fill in your values
    python run_live.py

Set DRY_RUN=true to observe the full plan without mutating NetBox.
"""
from __future__ import annotations

import os
import sys

from app.agent import SREAgent
from app.backends import NetBoxBackend
from app.llm import OpenAICompatLLM
from app.tools import ToolRegistry

GOAL = ("对 NetBox Docker 环境做一次 IPAM 与容器健康巡检。"
        "发现异常后定位根因、提出处置建议、执行安全的处置动作，并验证结果。")


def _load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    required = ("NETBOX_URL", "NETBOX_TOKEN", "LLM_BASE_URL", "LLM_API_KEY")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print("Missing environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2

    dry_run = os.environ.get("DRY_RUN", "true").lower() in {"1", "true", "yes"}
    backend = NetBoxBackend()
    registry = ToolRegistry(backend, dry_run=dry_run)
    llm = OpenAICompatLLM()
    agent = SREAgent(llm, registry)

    print(f"Live mode | model={llm.model} | netbox={backend.base} | dry_run={dry_run}")
    result = agent.run(GOAL)
    for item in result["trace"]:
        if item["type"] == "tool":
            print(f"[step {item['step']}] {item['name']}({item['args']}) -> {item['result'][:300]}")
    print("\n=== FINAL ANSWER ===\n" + result["answer"])
    print(f"\nok={result['ok']} steps={result['steps']} audit={len(result['audit'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
