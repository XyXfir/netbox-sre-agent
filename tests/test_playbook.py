"""Playbook routing regression tests."""
from __future__ import annotations

import json
import unittest

from app.backends import MockBackend
from app.playbook import PlaybookLibrary
from app.tools import ToolRegistry


class TestPlaybook(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = PlaybookLibrary()

    def test_loads_all_playbooks(self) -> None:
        ids = {p["id"] for p in self.lib.items}
        self.assertEqual(ids, {"duplicate_ip", "prefix_exhaustion", "container_fault"})

    def test_route_duplicate_signal(self) -> None:
        self.assertEqual(self.lib.route("duplicate_only returned 2 records")["id"], "duplicate_ip")

    def test_route_prefix_signal(self) -> None:
        self.assertEqual(self.lib.route("prefix utilization 94%")["id"], "prefix_exhaustion")

    def test_route_container_signal(self) -> None:
        self.assertEqual(self.lib.route("container ERROR in logs")["id"], "container_fault")

    def test_route_no_match_returns_none(self) -> None:
        self.assertIsNone(self.lib.route("totally unrelated signal xyz"))

    def test_get_playbook_tool_registered(self) -> None:
        reg = ToolRegistry(MockBackend(), playbooks=self.lib)
        names = [s["function"]["name"] for s in reg.schemas()]
        self.assertIn("get_playbook", names)

    def test_get_playbook_tool_routes(self) -> None:
        reg = ToolRegistry(MockBackend(), playbooks=self.lib)
        out = json.loads(reg.execute("get_playbook", {"signal": "duplicate_address conflict"}))
        self.assertEqual(out["data"]["id"], "duplicate_ip")
        self.assertTrue(out["data"]["high_risk_advice_only"])

    def test_no_playbooks_by_default(self) -> None:
        names = [s["function"]["name"] for s in ToolRegistry(MockBackend()).schemas()]
        self.assertNotIn("get_playbook", names)


if __name__ == "__main__":
    unittest.main()
