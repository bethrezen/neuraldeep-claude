import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("desktop_session_probe", Path(__file__).resolve().parents[1] / "scripts/probe-desktop-session.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class DesktopSessionProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / "native-profile"
        self.profile.mkdir()
        self.profile_patch = patch.object(probe, "native_profile", return_value=self.profile)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.runtime_patch = patch.object(probe.desktop_runtime, "inspect", return_value={"status": "READY", "version": "2.1.309"})
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.git_patch = patch.object(probe, "init_fixture_git", return_value="test-baseline")
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def prepare(self):
        receipt = probe.prepare(self.root)
        self.run = Path(receipt["run"])
        return receipt

    def test_prepare_prefills_uri_without_executing_native_or_network(self):
        with patch.object(probe.subprocess, "run") as execute:
            receipt = self.prepare()
        execute.assert_not_called()
        self.assertEqual(receipt["status"], "PREPARED")
        self.assertIn("claude://code/new?", receipt["supported_uri"])
        self.assertIn("folder=", receipt["supported_uri"])
        self.assertIn("q=", receipt["supported_uri"])
        self.assertFalse(receipt["gui_injection"])
        self.assertFalse(receipt["network_filter"])
        self.assertEqual((Path(receipt["workspace"]) / "test_calc.py").read_text(), probe.TESTS)

    def test_open_dispatches_only_supported_native_uri_and_never_claims_inference(self):
        self.prepare()
        config = self.profile / "configLibrary" / (probe.desktop.PROFILE_ID + ".json")
        config.parent.mkdir()
        config.write_text(json.dumps({"disableEssentialTelemetry": True, "disableNonessentialTelemetry": True,
                                      "modelDiscoveryEnabled": False,
                                      "inferenceModels": [{"name": "anthropic/neuraldeep/123"}]}))
        with patch.object(probe.desktop, "executable", return_value="/native/Claude"), \
             patch.object(probe, "session_environment", return_value={"DISABLE_TELEMETRY": "1"}), \
             patch.object(probe.subprocess, "run") as execute:
            execute.return_value.returncode = 0
            result = probe.open_run(self.run, self.root)
        command = execute.call_args.args[0]
        self.assertEqual(command[:2], ["/native/Claude", "--no-sandbox"])
        self.assertTrue(command[2].startswith("claude://code/new?"))
        self.assertEqual(result["status"], "WAITING_FOR_NATIVE_SEND")
        receipt = json.loads((self.run / "receipt.json").read_text())
        self.assertFalse(receipt["inference_verified"])

    def test_open_refuses_unready_native_engine_instead_of_substituting_a_cli(self):
        self.prepare()
        with patch.object(probe.desktop_runtime, "inspect", return_value={"status": "MISSING", "reason": "native-engine-absent"}), \
             patch.object(probe.subprocess, "run") as execute:
            with self.assertRaisesRegex(RuntimeError, "native-engine-absent"):
                probe.open_run(self.run, self.root)
            execute.assert_not_called()

    def test_manual_paste_opens_public_folder_uri_without_prefilling_or_submitting(self):
        self.prepare()
        config = self.profile / "configLibrary" / (probe.desktop.PROFILE_ID + ".json")
        config.parent.mkdir()
        config.write_text(json.dumps({"disableEssentialTelemetry": True, "disableNonessentialTelemetry": True}))
        with patch.object(probe.desktop, "executable", return_value="/native/Claude"), \
             patch.object(probe, "session_environment", return_value={"DISABLE_TELEMETRY": "1"}), \
             patch.object(probe.subprocess, "run") as execute:
            execute.return_value.returncode = 0
            result = probe.open_run(self.run, self.root, manual_paste=True)
        command = execute.call_args.args[0]
        self.assertIn("folder=", command[2])
        self.assertNotIn("&q=", command[2])
        self.assertTrue(result["manual_paste_required"])
        self.assertEqual(result["prompt_file"], str(self.run / "prompt.txt"))
        receipt = json.loads((self.run / "receipt.json").read_text())
        self.assertFalse(receipt["inference_verified"])

    def test_done_marker_alone_is_not_a_passing_code_session(self):
        receipt = self.prepare()
        (Path(receipt["workspace"]) / "DESKTOP_SESSION_DONE.json").write_text('{"tests_pass":true}')
        result = probe.review(self.run)
        self.assertFalse(result["artifact_check_pass"])
        self.assertFalse(result["tests_pass"])
        self.assertFalse(result["native_session_verified"])

    def test_correct_file_tests_still_require_native_transcript_binding(self):
        receipt = self.prepare()
        workspace = Path(receipt["workspace"])
        (workspace / "calc.py").write_text(probe.MODULE.replace("sum(range(n))", "n * (n + 1) // 2"))
        (workspace / "DESKTOP_SESSION_DONE.json").write_text('{}')
        result = probe.review(self.run)
        self.assertTrue(result["artifact_check_pass"])
        self.assertTrue(result["tests_pass"])
        self.assertFalse(result["native_session_verified"])

    def test_changed_tests_or_side_effect_module_are_not_executed(self):
        receipt = self.prepare()
        workspace = Path(receipt["workspace"])
        (workspace / "calc.py").write_text("import os\ndef triangular(n):\n    return n\n")
        with patch.object(probe.subprocess, "run") as execute:
            result = probe.review(self.run)
            execute.assert_not_called()
        self.assertFalse(result["safe_arithmetic_fixture"])
        (workspace / "calc.py").write_text(probe.MODULE)
        (workspace / "test_calc.py").write_text("# tests removed\n")
        with patch.object(probe.subprocess, "run") as execute:
            result = probe.review(self.run)
            execute.assert_not_called()
        self.assertFalse(result["test_unchanged"])

    def test_focused_profile_requires_unchanged_files_but_not_a_fake_done_claim(self):
        receipt = probe.prepare(self.root, focused=True)
        run = Path(receipt["run"])
        self.assertEqual(receipt["profile"], "classifier-focused")
        self.assertIn("DESKTOP_CLASSIFIER_OK 5050", (run / "prompt.txt").read_text())
        result = probe.review(run)
        self.assertTrue(result["artifact_check_pass"])
        self.assertFalse(result["native_session_verified"])
        self.assertFalse(result["done_artifact_exists"])

    def test_full_workflow_prepares_frozen_script_and_real_failing_bug(self):
        receipt = probe.prepare(self.root, workflow=True)
        run = Path(receipt["run"])
        workspace = Path(receipt["workspace"])
        self.assertEqual(receipt["profile"], "full-workflow")
        self.assertEqual((workspace / "workflow.js").read_text(), probe.WORKFLOW_SCRIPT)
        self.assertTrue(probe.WORKFLOW_SCRIPT.startswith("export const meta = {"))
        self.assertEqual(probe.WORKFLOW_SCRIPT.count("() => agent("), 2)
        self.assertIn("sum(range(n))", (workspace / "calc.py").read_text())
        result = probe.review(run)
        self.assertFalse(result["tests_pass"])
        self.assertFalse(result["artifact_check_pass"])
        self.assertFalse(result["native_session_verified"])
        self.assertTrue(result["workflow_unchanged"])

    def test_full_workflow_refuses_script_or_current_settings_tampering(self):
        settings = self.root / "settings.json"
        settings.write_text('{"model":"keep-current"}')
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps({"settings_files": [{"path": str(settings), "sha256": probe.sha(settings)}]}))
        receipt = probe.prepare(self.root, workflow=True, settings_baseline=baseline)
        self.assertTrue(receipt["settings_before"]["all_match"])
        run, workspace = Path(receipt["run"]), Path(receipt["workspace"])
        (workspace / "calc.py").write_text(probe.MODULE.replace("sum(range(n))", "n * (n + 1) // 2"))
        (workspace / "DESKTOP_SESSION_DONE.json").write_text('{}')
        result = probe.review(run)
        self.assertTrue(result["artifact_check_pass"])
        self.assertFalse(result["native_session_verified"])
        (workspace / "workflow.js").write_text("// no real workflow\n")
        self.assertFalse(probe.review(run)["artifact_check_pass"])
        (workspace / "workflow.js").write_text(probe.WORKFLOW_SCRIPT)
        settings.write_text('{"model":"silently-changed"}')
        result = probe.review(run)
        self.assertFalse(result["settings_after"]["all_match"])
        self.assertFalse(result["artifact_check_pass"])


if __name__ == "__main__":
    unittest.main()
