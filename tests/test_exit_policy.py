import json
import pathlib
import sys
import tempfile
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
import exit_policy


class TestExitPolicy(unittest.TestCase):
    def test_defaults_and_whole_gib_validation(self):
        p = exit_policy.default_policy()
        self.assertFalse(p["auto_switch"])
        self.assertEqual(p["quota_bytes"], {"nl": 500 * 1024 ** 3, "us": 500 * 1024 ** 3})
        self.assertEqual(exit_policy.policy_from_gib(True, "25", 750)["quota_bytes"]["nl"], 25 * 1024 ** 3)
        for value in (0, -1, 1.5, "2.5", 1_000_001, True):
            with self.assertRaises(ValueError):
                exit_policy.policy_from_gib(True, value, 500)

    def test_load_policy_fails_safe(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "policy.json"
            policy, warning = exit_policy.load_policy(str(path))
            self.assertEqual(warning, "missing_policy")
            self.assertFalse(policy["auto_switch"])
            path.write_text("{bad json")
            policy, warning = exit_policy.load_policy(str(path))
            self.assertEqual(warning, "invalid_policy")
            self.assertFalse(policy["auto_switch"])

    def test_target_guards_health_freshness_and_quota(self):
        p = exit_policy.policy_from_gib(True, 1, 1)
        usage = {"nl": 1024 ** 3, "us": 0}
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": True, "checked_age": 61}})["code"], "target_stale")
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": False, "checked_age": 1}})["code"], "target_unhealthy")
        usage["us"] = 1024 ** 3
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": True, "checked_age": 1}})["code"], "target_exhausted")

    def test_auto_action_and_no_ping_pong(self):
        p = exit_policy.policy_from_gib(True, 1, 1)
        health = {
            "nl": {"ok": True, "checked_age": 1},
            "us": {"ok": True, "checked_age": 1},
        }
        d = exit_policy.evaluate_auto(p, {"nl": 1024 ** 3, "us": 0}, {"nl": 14, "us": 0}, health)
        self.assertEqual(d["action"], {"source": "nl", "target": "us", "reason": "quota"})
        d = exit_policy.evaluate_auto(p, {"nl": 1024 ** 3, "us": 1024 ** 3}, {"nl": 0, "us": 14}, health)
        self.assertIsNone(d["action"])
        self.assertEqual(d["blocked"]["code"], "target_exhausted")


if __name__ == "__main__":
    unittest.main()
