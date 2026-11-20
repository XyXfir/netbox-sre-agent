#!/usr/bin/env python3
"""Agent 行为评估集。

检验三件事：
  1. 工具调用序列是否正确（发现 -> 诊断 -> 执行 -> 验证）
  2. 无异常时是否误触发写操作
  3. dry-run / 白名单收紧时是否真的拦住写操作、后端数据是否零变更

    python eval/agent_eval.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import SREAgent
from app.backends import MockBackend
from app.llm import MockLLM
from app.tools import WRITE_TOOLS, ToolRegistry

GOAL = ("对 NetBox Docker 环境做一次 IPAM 与容器健康巡检。"
        "发现异常后定位根因、提出处置建议、执行安全的处置动作，并验证结果。")


def dirty_backend() -> MockBackend:
    """默认种子：有重复 IP + 高危前缀。"""
    return MockBackend()


def clean_backend() -> MockBackend:
    """干净环境：无重复 IP、无高危前缀。"""
    b = MockBackend()
    b.ips = [ip for ip in b.ips if ip["id"] != 102]
    for p in b.prefixes:
        p["utilization"] = 10
    return b


@dataclass
class Scenario:
    name: str
    factory: Callable[[], MockBackend]
    dry_run: bool = False
    allowed_writes: set[str] | None = None
    expect_write: bool = True
    expect_state_change: bool = True


SCENARIOS = [
    Scenario("异常环境 - 完整闭环", dirty_backend),
    Scenario("异常环境 - dry-run 拦截", dirty_backend, dry_run=True, expect_state_change=False),
    Scenario("异常环境 - 写白名单收紧", dirty_backend, allowed_writes=set(), expect_state_change=False),
    Scenario("干净环境 - 不误写", clean_backend, expect_write=False, expect_state_change=False),
]


def evaluate(s: Scenario) -> Tuple[List[Tuple[str, bool, str]], bool]:
    backend = s.factory()
    registry = ToolRegistry(backend, dry_run=s.dry_run, allowed_write_tools=s.allowed_writes)
    result = SREAgent(MockLLM(), registry).run(GOAL)

    called = [t["name"] for t in result["trace"] if t["type"] == "tool"]
    write_called = [n for n in called if n in WRITE_TOOLS]
    ip_after = backend.get_ip_address(102)
    state_changed = bool(ip_after and ip_after["status"] == "reserved")

    checks: List[Tuple[str, bool, str]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append((name, passed, detail))

    discovery = {"get_system_health", "list_prefixes", "list_ip_addresses"}
    add("发现阶段完整", discovery.issubset(called), f"实际调用: {called}")

    if s.expect_write:
        add("诊断阶段完整", {"get_ip_address", "get_container_logs"}.issubset(called))
        add("触发写操作", len(write_called) > 0, f"写工具: {write_called}")
        add("写后验证", "verify_remediation" in called, f"工具序列尾部: {called[-3:]}")
    else:
        add("未误触发写操作", len(write_called) == 0, f"写工具: {write_called}")

    add("后端状态符合预期", state_changed == s.expect_state_change,
        f"id=102 status={ip_after['status'] if ip_after else 'deleted'}, 期望变更={s.expect_state_change}")

    if s.dry_run:
        dry_records = [r for r in registry.audit if r.get("dry_run")]
        add("dry-run 审计留痕", len(dry_records) == len(write_called),
            f"拦截 {len(dry_records)} 条 / 调用 {len(write_called)} 条")

    if s.allowed_writes is not None:
        rejected = []
        for item in result["trace"]:
            if item["type"] == "tool" and item["name"] in WRITE_TOOLS:
                import json
                if json.loads(item["result"]).get("ok") is False:
                    rejected.append(item["name"])
        add("白名单外写被拒", len(rejected) == len(write_called),
            f"拒绝 {len(rejected)} 条 / 调用 {len(write_called)} 条")

    all_pass = all(ok for _, ok, _ in checks)
    return checks, all_pass


def main() -> int:
    total = 0
    passed = 0
    scenarios_passed = 0

    print("=" * 68)
    print(" Agent 行为评估集")
    print("=" * 68)
    for s in SCENARIOS:
        checks, ok = evaluate(s)
        scenarios_passed += int(ok)
        print(f"\n场景: {s.name}  ->  {'PASS' if ok else 'FAIL'}")
        for name, item_ok, detail in checks:
            print(f"  [{'PASS' if item_ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not item_ok else ""))
            total += 1
            passed += int(item_ok)

    print("\n" + "-" * 68)
    print(f"场景通过: {scenarios_passed}/{len(SCENARIOS)}")
    print(f"断言通过: {passed}/{total}  ({passed / total * 100:.1f}%)")
    print("-" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
