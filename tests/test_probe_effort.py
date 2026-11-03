import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "scripts/probe-effort.py"
SPEC = importlib.util.spec_from_file_location("probe_effort", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class EffortProbeTests(unittest.TestCase):
    def test_dry_run_never_launches_native_or_reads_keys(self):
        with patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(probe.main([]), 0)
        execute.assert_not_called()
        plan = json.loads(out.getvalue())
        self.assertEqual(plan["efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(plan["billing"], "subscription")
        self.assertFalse(plan["network_filter"])

    def test_native_result_parses_object_and_event_array(self):
        result = {"type": "result", "result": "marker", "is_error": False}
        for value in (result, [{"type": "system"}, result]):
            self.assertEqual(probe.final_result(json.dumps(value)), result)
        with self.assertRaisesRegex(ValueError, "no result"):
            probe.final_result('{"type":"system"}')

    def test_gateway_mapping_evidence_excludes_concurrent_unrelated_requests(self):
        match = {"event": "request", "model": probe.MODEL, "billing": "subscription", "max_tokens": 4093,
                 "time": 15, "effort_requested": "high", "effort_applied": "xhigh", "id": "own"}
        rows = [match, match | {"max_tokens": 128000, "id": "desktop"},
                match | {"time": 5, "id": "previous"}, match | {"model": "other", "id": "other"}]
        evidence = probe.mapping_evidence(rows, "high", "xhigh", 4093, 10, 20)
        self.assertEqual([row["id"] for row in evidence["matched_gateway_requests"]], ["own"])
        self.assertTrue(evidence["stock_effort_seen"])
        self.assertTrue(evidence["upstream_effort_matches"])
        wrong = probe.mapping_evidence([match | {"effort_requested": "max"}], "high", "xhigh", 4093, 10, 20)
        self.assertFalse(wrong["stock_effort_seen"])
        self.assertFalse(probe.mapping_evidence([], "high", "xhigh", 4093, 10, 20)["upstream_effort_matches"])


if __name__ == "__main__":
    unittest.main()
