import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts/probe-classifier.py"
SPEC = importlib.util.spec_from_file_location("probe_classifier", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ClassifierProbeTests(unittest.TestCase):
    def test_dry_run_keeps_native_criteria_and_never_executes(self):
        with patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main([]), 0)
        execute.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["candidate"], "nd/qwen3.6-35b-a3b-noreason@subscription")
        self.assertEqual(result["permission_mode"], "auto")
        self.assertFalse(result["safety_rules_modified"])
        self.assertFalse(result["classifier_timeouts_modified"])
        self.assertFalse(result["network_filter"])

    def test_classifier_metrics_distinguish_real_review_requests_from_worker_streams(self):
        row = {"event": "request", "id": "classify", "model": probe.CANDIDATE, "billing": "subscription",
               "stream": False, "max_tokens": 2112, "time": 10, "effort_requested": None, "effort_applied": None}
        events = [row, row | {"id": "worker", "stream": True, "max_tokens": 4096},
                  row | {"id": "old", "time": 1}, {"event": "upstream_headers", "id": "classify", "elapsed": 2},
                  {"event": "finished", "id": "classify", "elapsed": 3}]
        result = probe.classifier_metrics(events, 9, 20)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["under_60_seconds"])
        self.assertEqual(result[0]["finished_seconds"], 3)
        stage2 = probe.classifier_metrics([row | {"max_tokens": 10240}, {"event": "finished", "id": "classify", "elapsed": 5}], 9, 20)
        self.assertEqual(stage2[0]["max_tokens"], 10240)

    def test_success_claim_alone_does_not_prove_background_agents_or_bash(self):
        evidence = probe.flow_evidence([{"type": "result", "result": "CLASSIFIER_FLOW_OK REVIEW_A=323 REVIEW_B=323", "is_error": False}], "")
        self.assertFalse(evidence["bash_marker_received"])
        self.assertEqual(evidence["background_agents_requested"], 0)
        self.assertEqual(evidence["TaskOutput_calls"], 0)

    def test_native_safety_warning_is_retained_even_with_correct_worker_answers(self):
        events = [{"type": "user", "message": {"content": [{"type": "tool_result", "content": "REVIEW_A=323. Note: the safety classifier was unavailable when reviewing this subagent's work."}]}},
                  {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Agent", "input": {"run_in_background": True}}]}}]
        evidence = probe.flow_evidence(events, "")
        self.assertEqual(evidence["background_agents_requested"], 1)
        self.assertEqual(len(evidence["classifier_warnings"]), 1)

    def test_real_native_handback_notifications_and_primary_result_survive_cleanup_results(self):
        events = [{"type": "system", "subtype": "task_notification", "status": "completed", "handback": "send",
                   "handback_report": {"text": "REVIEW_A=323"}},
                  {"type": "system", "subtype": "task_notification", "status": "completed", "handback": "send",
                   "handback_report": {"text": "REVIEW_B=323"}},
                  {"type": "result", "result": "CLASSIFIER_FLOW_OK REVIEW_A=323 REVIEW_B=323", "is_error": False},
                  {"type": "result", "result": "All background tasks completed.", "is_error": False}]
        debug = "[auto-mode] new action being classified: tool=SubagentHandback actionChars=300 id=own-id"
        evidence = probe.flow_evidence(events, debug)
        self.assertTrue(evidence["native_review_a_delivered"])
        self.assertTrue(evidence["native_review_b_delivered"])
        self.assertIn("CLASSIFIER_FLOW_OK", evidence["final"])
        self.assertEqual(len(evidence["native_handoff_contexts"]), 1)

    def test_native_stage_outcomes_are_retained_separately_from_worker_claims(self):
        debug = ("[Stall] classifier_request_started reqId=one tool=SubagentHandback model=" + probe.CANDIDATE + " stage=xml_s1\n"
                 "[Stall] classifier_request_finished reqId=one tool=SubagentHandback stage=xml_s1 outcome=ok durationMs=778\n")
        stages = probe.native_classifier_stages(debug)
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["outcome"], "ok")
        self.assertEqual(stages[0]["model"], probe.CANDIDATE)
        self.assertEqual(stages[0]["duration_ms"], 778)


if __name__ == "__main__":
    unittest.main()
