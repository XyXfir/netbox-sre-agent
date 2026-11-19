#!/usr/bin/env python3
"""Offline demo: no API key, no NetBox, no Docker required.

    python run_demo.py
"""
from __future__ import annotations

import json
import sys

from app.agent import SREAgent
from app.backends import MockBackend
from app.llm import MockLLM
from app.tools import ToolRegistry

GOAL = ("对 NetBox Docker 环境做一次 IPAM 与容器健康巡检。"
        "发现异常后定位根因、提出处置建议、执行安全的处置动作，并验证结果。")


def run() -> dict:
    backend = MockBackend()
    registry = ToolRegistry(backend, dry_run=False)
    agent = SREAgent(MockLLM(), registry)
    result = agent.run(GOAL)

    names = [t["name"] for t in result["trace"] if t["type"] == "tool"]
    assert "get_system_health" in names, "缺少发现阶段"
    assert "get_ip_address" in names, "缺少诊断阶段"
    assert "update_ip_status" in names, "缺少执行阶段"
    assert "verify_remediation" in names, "缺少验证阶段"
    assert backend.get_ip_address(102)["status"] == "reserved", "处置未生效"
    assert backend.verify_duplicate("10.42.7.15/24")["resolved"], "异常未消除"
    result["backend"] = backend
    return result


def _short(text: str, limit: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def main() -> int:
    result = run()
    print("=" * 72)
    print(" NetBox SRE Agent - OFFLINE TOOL CALLING DEMO")
    print("=" * 72)
    for item in result["trace"]:
        if item["type"] == "tool":
            print(f"\n[step {item['step']}] TOOL CALL  {item['name']}({json.dumps(item['args'], ensure_ascii=False)})")
            if item.get("reasoning"):
                print(f"          REASONING: {_short(item['reasoning'], 300)}")
            print(f"          RESULT   : {_short(item['result'])}")
        else:
            print(f"\n[step {item['step']}] FINAL ANSWER\n{item['content']}")
    print("\n" + "-" * 72)
    print("AUDIT TRAIL:")
    for entry in result["audit"]:
        print("  " + json.dumps(entry, ensure_ascii=False))
    print("-" * 72)
    print(f"PASS: closed loop finished in {result['steps']} steps, "
          f"{len(result['audit'])} audit records written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
