"""LLM adapters.

OpenAICompatLLM : real function calling over any OpenAI-compatible endpoint
                  (DashScope / Qwen, OpenAI, DeepSeek, vLLM, Ollama ...).
MockLLM         : deterministic stand-in that emits the *same* tool_calls
                  structure. It lets the whole loop run offline with no key.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

import requests


class OpenAICompatLLM:
    """Minimal OpenAI-compatible client; only stdlib requests is required."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int = 90) -> None:
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "qwen-plus")
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


# --------------------------------------------------------------------------- #
# Offline "LLM" - emits valid OpenAI tool_calls without any network access.
# --------------------------------------------------------------------------- #
def _tc(call_id: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def _assistant(calls: List[Dict[str, Any]], content: str = "") -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


def _scan(messages: List[Dict[str, Any]]) -> tuple[List[str], Dict[str, Any]]:
    """Return (called tool names, parsed outputs keyed by tool name)."""
    id_to_name: Dict[str, str] = {}
    called: List[str] = []
    outputs: Dict[str, Any] = {}
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                name = tc["function"]["name"]
                id_to_name[tc["id"]] = name
                called.append(name)
        elif m.get("role") == "tool":
            name = id_to_name.get(m.get("tool_call_id"))
            if not name:
                continue
            try:
                outputs[name] = json.loads(m["content"])
            except (ValueError, TypeError):
                outputs[name] = {"raw": m["content"]}
    return called, outputs


class MockLLM:
    """A scripted but protocol-real tool caller for the demo.

    It inspects prior tool outputs, so its decisions still depend on the data
    returned by the tools - it is not just replaying a fixed transcript.
    """

    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        called, out = _scan(messages)

        ips_payload = out.get("list_ip_addresses", {})
        dups = ips_payload.get("data") or []
        if not isinstance(dups, list):
            dups = []
        rogue = next((d for d in dups if not d.get("assigned_object")), dups[0] if dups else None)
        address = rogue.get("address") if rogue else ""
        rogue_id = rogue.get("id") if rogue else None

        prefix_payload = out.get("list_prefixes", {})
        prefixes = prefix_payload.get("data") or []
        hot = max(prefixes, key=lambda p: p.get("utilization", 0)) if prefixes else None

        # 1) Discover
        if "get_system_health" not in called:
            return _assistant([
                _tc("c1", "get_system_health", {}),
                _tc("c2", "list_prefixes", {"min_utilization": 85}),
                _tc("c3", "list_ip_addresses", {"duplicate_only": True}),
            ], "先做一次面和容器的健康巡检，并筛出高危前缀与重复 IP。")

        # 2) Diagnose
        if rogue and "get_ip_address" not in called:
            return _assistant([
                _tc("c4", "get_ip_address", {"ip_id": rogue_id}),
                _tc("c5", "get_container_logs", {"container": "netbox", "lines": 40}),
            ], "发现重复地址，进一步核对两条记录的属性，并查看 netbox 容器日志以排除服务自身异常。")

        # 3) Recommend + execute (the reasoning text is the recommendation)
        if rogue and "update_ip_status" not in called:
            rec = (
                f"诊断：{address} 在 NetBox 中存在两条 active 记录；id={rogue_id} 的记录无归属设备、无描述，"
                "而另一条绑定在 prod web 节点上，判定为过期/孤立记录。netbox 容器日志无异常，"
                "可排除容器故障。建议：将孤立记录置为 reserved、打上 sre-agent-triage 标签并写入 journal；"
                "前缀容量问题涉及地址规划，仅提示不自动变更。"
            )
            return _assistant([
                _tc("c6", "update_ip_status", {"ip_id": rogue_id, "status": "reserved"}),
                _tc("c7", "add_ip_tag", {"ip_id": rogue_id, "tag": "sre-agent-triage"}),
                _tc("c8", "create_journal_entry", {
                    "object_type": "ipam.ipaddress", "object_id": rogue_id,
                    "comment": f"SRE agent: duplicate {address}, stale record without owner -> reserved",
                }),
            ], rec)

        # 4) Verify
        if rogue and "verify_remediation" not in called:
            return _assistant([
                _tc("c9", "verify_remediation", {"check": "duplicate_address", "address": address}),
            ], "处置已执行，重新校验该地址是否仍存在冲突。")

        # 5) Final answer - 无异常时给出干净的"无需处置"结论
        health = out.get("get_system_health", {}).get("data", {})
        verify = (out.get("verify_remediation", {}).get("data") or {})
        containers = health.get("containers", [])
        healthy = sum(1 for c in containers if "healthy" in str(c.get("status", "")))
        prefix_txt = (f"{hot['prefix']} 利用率 {hot['utilization']}%" if hot else "未发现高危前缀")
        resolved = verify.get("resolved")
        if not rogue:
            return _assistant([], (
                "【SRE 巡检报告】\n"
                f"发现：容器 {healthy}/{len(containers)} 健康；高危前缀：{prefix_txt}；未发现重复 IP。\n"
                "诊断：当前 IPAM 数据无冲突，无需处置。\n"
                "建议：保持现状；若后续出现容量告警再走变更评审。\n"
                "执行：无写操作。\n"
                "验证：不适用。"
            ))
        return _assistant([], (
            "【SRE 巡检闭环报告】\n"
            f"发现：容器 {healthy}/{len(containers)} 健康；高危前缀 {prefix_txt}；"
            f"重复地址 {address or '无'}。\n"
            f"诊断：孤立 IP id={rogue_id} 无归属、无描述，容器日志正常，判定为陈旧 IPAM 记录。"
            "根因是人工变更未回收地址。\n"
            "建议：已按低风险策略处置；前缀扩容需变更评审，未自动执行。\n"
            "执行：status -> reserved、添加 sre-agent-triage 标签、写入 NetBox journal。\n"
            f"验证：冲突是否解除 = {resolved}；审计记录已写入 tool registry。"
        ))
