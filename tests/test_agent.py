"""Minimal regression tests: python -m unittest discover -s tests -v"""
from __future__ import annotations

import unittest

from app.agent import SREAgent
from app.backends import MockBackend
from app.llm import MockLLM
from app.tools import TOOL_SCHEMAS, ToolRegistry

from run_demo import GOAL, run


class TestToolCallingLoop(unittest.TestCase):
    def test_closed_loop(self) -> None:
        result = run()
        names = [t["name"] for t in result["trace"] if t["type"] == "tool"]
        self.assertEqual(names, [
            "get_system_health", "list_prefixes", "list_ip_addresses",
            "get_ip_address", "get_container_logs",
            "update_ip_status", "add_ip_tag", "create_journal_entry",
            "verify_remediation",
        ])
        self.assertTrue(result["ok"])
        self.assertIn("reserved", result["answer"] + str(result["audit"]))

    def test_dry_run_does_not_mutate(self) -> None:
        backend = MockBackend()
        registry = ToolRegistry(backend, dry_run=True)
        result = SREAgent(MockLLM(), registry).run(GOAL)
        self.assertEqual(backend.get_ip_address(102)["status"], "active")
        self.assertTrue(result["audit"])
        self.assertTrue(any(r.get("dry_run") for r in result["audit"]))

    def test_write_allowlist(self) -> None:
        registry = ToolRegistry(MockBackend(), allowed_write_tools=set())
        result = registry.execute("update_ip_status", {"ip_id": 102, "status": "reserved"})
        self.assertFalse(__import__("json").loads(result)["ok"])

    def test_tool_schemas_are_openai_compatible(self) -> None:
        for tool in TOOL_SCHEMAS:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertEqual(tool["function"]["parameters"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
