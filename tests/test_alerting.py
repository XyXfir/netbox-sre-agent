"""Alert adapter regression tests."""
from __future__ import annotations

import unittest

from app.alerting import AlertAdapter

PAYLOAD = {
    "alerts": [
        {"status": "firing", "labels": {"alertname": "Dup", "ip": "10.0.0.1/24", "severity": "warning"},
         "annotations": {"summary": "duplicate"}},
        {"status": "resolved", "labels": {"alertname": "Down"}, "annotations": {}},
    ]
}


class TestAlerting(unittest.TestCase):
    def test_parse_only_firing(self) -> None:
        self.assertEqual(len(AlertAdapter().parse(PAYLOAD)), 1)

    def test_fingerprint_stable(self) -> None:
        a = AlertAdapter()
        alert = PAYLOAD["alerts"][0]
        self.assertEqual(a.fingerprint(alert), a.fingerprint(alert))

    def test_dedupe(self) -> None:
        a = AlertAdapter()
        firing = a.parse(PAYLOAD)
        first, skipped1 = a.dedupe(firing)
        self.assertEqual(len(first), 1)
        self.assertEqual(skipped1, [])
        second, skipped2 = a.dedupe(firing)
        self.assertEqual(second, [])
        self.assertEqual(len(skipped2), 1)

    def test_to_goal(self) -> None:
        goal = AlertAdapter().to_goal(AlertAdapter().parse(PAYLOAD))
        self.assertIn("Dup", goal)
        self.assertIn("duplicate", goal)


if __name__ == "__main__":
    unittest.main()
