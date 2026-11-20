"""Rollback tool regression tests."""
from __future__ import annotations

import json
import unittest

from app.backends import MockBackend
from app.tools import ToolRegistry


class TestRollback(unittest.TestCase):
    def test_rollback_restores_before_value(self) -> None:
        b = MockBackend()
        reg = ToolRegistry(b)
        self.assertEqual(b.get_ip_address(102)["status"], "active")
        reg.execute("update_ip_status", {"ip_id": 102, "status": "reserved"})
        self.assertEqual(b.get_ip_address(102)["status"], "reserved")
        out = json.loads(reg.execute("rollback_ip_status", {"ip_id": 102}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["restored_to"], "active")
        self.assertEqual(b.get_ip_address(102)["status"], "active")

    def test_rollback_audited(self) -> None:
        b = MockBackend()
        reg = ToolRegistry(b)
        reg.execute("update_ip_status", {"ip_id": 102, "status": "reserved"})
        reg.execute("rollback_ip_status", {"ip_id": 102})
        self.assertTrue(any(r["action"] == "rollback" for r in b.audit))

    def test_rollback_no_change_is_error(self) -> None:
        b = MockBackend()
        reg = ToolRegistry(b)
        out = json.loads(reg.execute("rollback_ip_status", {"ip_id": 102}))
        self.assertFalse(out["data"]["ok"])
        self.assertIn("no status change", out["data"]["error"])

    def test_rollback_respects_dry_run(self) -> None:
        b = MockBackend()
        reg = ToolRegistry(b, dry_run=True)
        reg.execute("update_ip_status", {"ip_id": 102, "status": "reserved"})
        b.ips[1]["status"] = "reserved"  # simulate a real change slipped in
        result = json.loads(reg.execute("rollback_ip_status", {"ip_id": 102}))
        self.assertTrue(result.get("dry_run"))
        self.assertEqual(b.get_ip_address(102)["status"], "reserved")


if __name__ == "__main__":
    unittest.main()
