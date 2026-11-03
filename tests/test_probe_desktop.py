import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "scripts/probe-desktop.py"
SPEC = importlib.util.spec_from_file_location("probe_desktop", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class DesktopProbeTests(unittest.TestCase):
    def test_dry_run_never_starts_native_or_network(self):
        with patch.object(probe, "execute") as execute, patch.object(probe.egress, "_direct_open") as network, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main([]), 0)
        execute.assert_not_called()
        network.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["execute"])

    def test_execute_other_platform_fails_before_any_native_process(self):
        with patch.object(probe.sys, "platform", "win32"), patch.object(probe, "execute") as execute, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                probe.main(["--execute"])
        self.assertEqual(error.exception.code, 2)
        execute.assert_not_called()

    def test_manual_list_is_detected_even_when_discovery_is_enabled(self):
        summary = probe.configuration_summary({"modelDiscoveryEnabled": True, "inferenceModels": ["opaque"]}, {}, {})
        self.assertTrue(summary["discovery_enabled"])
        self.assertFalse(summary["manual_model_list_absent"])

    def test_native_log_manual_allowlist_does_not_count_as_discovery(self):
        configured = "[custom-3p] Model discovery: skipped; picker = 117 (inferenceModels)"
        actual = "[custom-3p] Model discovery: 117 found in 4ms; picker = 117 (discovery)"
        self.assertFalse(probe.native_log_evidence(configured, 117)["native_discovery_count_matches"])
        self.assertTrue(probe.native_log_evidence(actual, 117)["native_discovery_count_matches"])
        self.assertFalse(probe.native_log_evidence(actual, 118)["native_discovery_count_matches"])
        self.assertTrue(probe.native_log_evidence(configured, 117, "inferenceModels")["native_picker_count_matches"])
        self.assertFalse(probe.native_log_evidence(actual, 117, "inferenceModels")["native_picker_count_matches"])

    def test_native_config_rejection_is_not_hidden_by_correct_count(self):
        text = "Model discovery: 117 found in 4ms; picker = 117 (discovery)\nConfigHealth recomputed { state: 'config_model_rejected' }"
        evidence = probe.native_log_evidence(text, 117)
        self.assertTrue(evidence["native_discovery_count_matches"])
        self.assertTrue(evidence["native_config_rejected"])

    def test_one_token_native_subscription_probe_is_explicit_not_inference_free(self):
        expected = {"event": "request", "max_tokens": 1, "billing": "subscription", "messages": 1, "tools": 0, "stream": False}
        evidence = probe.inference_evidence([expected])
        self.assertTrue(evidence["inference_observed"])
        self.assertEqual(evidence["native_connection_probe_requests"], 1)
        self.assertFalse(evidence["unexpected_inference_observed"])
        other = probe.inference_evidence([expected, dict(expected, max_tokens=16)])
        self.assertTrue(other["unexpected_inference_observed"])

    def test_existing_native_instance_blocks_before_health_requests(self):
        with patch.object(probe.desktop, "executable", return_value="native"), patch.object(probe.desktop, "_existing_native_processes", return_value=[42]), patch.object(probe.egress, "_direct_open") as network:
            with self.assertRaisesRegex(RuntimeError, "Existing native"):
                probe.execute(probe.ROOT)
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
