"""The Tool Calling agent loop.

One loop serves both the real LLM and the offline mock: the model returns
`tool_calls`, we execute them, we feed results back as `role=tool` messages,
and repeat until the model produces a final answer.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .llm import MockLLM, OpenAICompatLLM
from .prompt import SYSTEM_PROMPT
from .tools import ToolRegistry

LLM = MockLLM | OpenAICompatLLM


class SREAgent:
    def __init__(self, llm: LLM, registry: ToolRegistry, max_steps: int = 12) -> None:
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps

    def run(self, goal: str) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]
        trace: List[Dict[str, Any]] = []

        for step in range(1, self.max_steps + 1):
            message = self.llm.chat(messages, tools=self.registry.schemas())
            messages.append(message)
            calls = message.get("tool_calls") or []

            if not calls:
                trace.append({"step": step, "type": "final", "content": message.get("content", "")})
                return {"ok": True, "steps": step, "trace": trace,
                        "answer": message.get("content", ""), "audit": self.registry.audit}

            for call in calls:
                func = call.get("function", {})
                name = func.get("name", "")
                raw_args = func.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except ValueError:
                    args = {}
                result = self.registry.execute(name, args)
                tool_message = {"role": "tool", "tool_call_id": call.get("id", f"auto-{step}"),
                                "content": result}
                messages.append(tool_message)
                trace.append({"step": step, "type": "tool", "name": name,
                              "args": args, "result": result})

                if message.get("content"):
                    trace[-1]["reasoning"] = message["content"]

        return {"ok": False, "steps": self.max_steps, "trace": trace,
                "answer": "达到最大步数仍未收敛，请检查提示词或模型工具调用质量。",
                "audit": self.registry.audit}
