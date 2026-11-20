#!/usr/bin/env python3
"""Real LLM function calling + in-memory NetBox backend.

Proof that the agent uses genuine Tool Calling: the DECISION of which tool to
call next is made by the LLM (not by scripted rules). The backend is the same
MockBackend used by run_demo.py, so no NetBox/Docker/token is required.

    export LLM_BASE_URL=https://coding.dashscope.aliyuncs.com/v1
    export LLM_API_KEY=sk-...
    export LLM_MODEL=glm-5
    python run_live_mock.py

The agent runs in verbose mode, printing every step: model thinking, tool
calls, and tool results. Set DRY_RUN=true to block all write tools.
"""
from __future__ import annotations

import os
import sys

from app.agent import SREAgent
from app.backends import MockBackend
from app.llm import OpenAICompatLLM
from app.tools import ToolRegistry

GOAL = ("对 NetBox Docker 环境做一次 IPAM 与容器健康巡检。"
        "发现异常后定位根因、提出处置建议、执行安全的处置动作，并验证结果。")


def main() -> int:
    required = ("LLM_BASE_URL", "LLM_API_KEY")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print("Missing environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2

    dry_run = os.environ.get("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    backend = MockBackend()
    registry = ToolRegistry(backend, dry_run=dry_run)
    llm = OpenAICompatLLM()          # real function calling
    agent = SREAgent(llm, registry, verbose=True)

    print(f"Live LLM mode | model={llm.model} | backend=MockBackend | dry_run={dry_run}")
    result = agent.run(GOAL)

    print(f"\n{'='*64}\n  FINAL REPORT\n{'='*64}")
    print(result["answer"])
    print(f"\nok={result['ok']}  steps={result['steps']}  "
          f"tool_calls={sum(1 for t in result['trace'] if t['type']=='tool')}  "
          f"audit={len(result['audit'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
