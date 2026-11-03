import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "scripts/probe-models.py"
SPEC = importlib.util.spec_from_file_location("probe_models", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def fixture():
    models = {}
    for name, billing in (("gpt-oss-120b", "subscription"), ("gpt-oss-120b", "wallet"), ("other", "wallet")):
        identity = f"nd/{name}@{billing}"
        models[identity] = {"id": identity, "upstream_id": name, "billing": billing,
                            "efforts": ["low", "medium", "high"] if name.startswith("gpt") else [],
                            "capabilities": {"vision": False}}
    return {"refreshed_at": "2026-11-02T12:00:00+00:00", "models": models,
            "aliases": {"gpt-oss-120b": "nd/gpt-oss-120b@subscription", "other": "nd/other@wallet"}, "limits": {}}


class ProbeModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nd-model-probe-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".local").mkdir()
        self.data = fixture()
        (self.root / ".local/catalog.json").write_text(json.dumps(self.data))
        self.latest = self.root / ".local/model-probes.json"
        root = patch.object(probe, "ROOT", self.root)
        root.start()
        self.addCleanup(root.stop)

    def test_dry_run_resolves_and_deduplicates_target_aliases_without_io_or_calls(self):
        with patch.object(probe, "key_for") as key, patch.object(probe.protocol, "configure") as configure, \
             patch.object(probe, "test") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            code = probe.main(["--billing", "subscription", "--model", "gpt-oss-120b",
                               "--model", "gpt-oss-120b@subscription~medium"])
        self.assertEqual(code, 0)
        plan = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(plan["routes"], 1)
        self.assertEqual(plan["selected_models"], ["nd/gpt-oss-120b@subscription"])
        self.assertEqual(plan["planned_requests_up_to"], 6)
        self.assertFalse(self.latest.exists())
        self.assertFalse((self.root / ".local/model-probes").exists())
        for mock in (key, configure, execute):
            mock.assert_not_called()

    def test_unknown_target_or_conflicting_billing_fails_before_credentials_or_archive(self):
        for argv in (["--model", "missing", "--execute"],
                     ["--model", "gpt-oss-120b@subscription", "--billing", "wallet", "--execute"]):
            with self.subTest(argv=argv), patch.object(probe, "key_for") as key, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    probe.main(argv)
                self.assertEqual(caught.exception.code, 2)
                key.assert_not_called()
                self.assertFalse((self.root / ".local/model-probes").exists())

    def test_repeated_filter_supports_separate_billing_routes_without_effort_copies(self):
        models = probe.selected_models(self.data, "all", ["gpt-oss-120b", "gpt-oss-120b@wallet"])
        self.assertEqual([model["billing"] for model in models], ["subscription", "wallet"])
        self.assertTrue(all("selected_effort" not in model for model in models))

    def test_retired_routes_are_excluded_and_explicit_retired_request_is_not_redirected(self):
        data = fixture()
        data["picker_policy"] = {"excluded_upstream_ids": ["other"],
                                 "hide_until_probe_passes": ["gpt-oss-120b"]}
        models = probe.selected_models(data, "all", [])
        # Hidden access failures remain diagnostically probeable; retired IDs do not.
        self.assertEqual(len(models), 2)
        self.assertTrue(all(model["upstream_id"] == "gpt-oss-120b" for model in models))
        self.assertEqual(len(probe.selected_models(data, "subscription", ["gpt-oss-120b"])), 1)
        with self.assertRaises(probe.catalog.RetiredModelError):
            probe.selected_models(data, "all", ["other"])

    def test_partial_execution_preserves_old_raw_evidence_and_aggregate_other_models(self):
        old = {"finished_at": "2026-11-01T09:00:00+00:00", "checks": [
            {"model": "nd/gpt-oss-120b@subscription", "checks": [{"kind": "text", "status": "FAIL_EMPTY_FINAL"}]},
            {"model": "nd/other@wallet", "checks": [{"kind": "text", "status": "HTTP_ERROR", "http_status": 401}]}]}
        raw = json.dumps(old, separators=(",", ":")).encode()
        self.latest.write_bytes(raw)
        outcome = {"model": "nd/gpt-oss-120b@subscription", "checks": [{"kind": "text", "status": "PASS"}]}
        with patch.object(probe, "key_for", return_value="fixture-key"), patch.object(probe.protocol, "configure"), \
             patch.object(probe, "test", return_value=outcome) as execute, contextlib.redirect_stdout(io.StringIO()):
            code = probe.main(["--model", "gpt-oss-120b", "--billing", "subscription", "--workers", "1", "--execute"])
        self.assertEqual(code, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("selected_effort", execute.call_args.args[0])
        history = self.root / ".local/model-probes"
        prior = history / ("prior-" + hashlib.sha256(raw).hexdigest()[:16] + ".json")
        self.assertEqual(prior.read_bytes(), raw)
        aggregate = json.loads(self.latest.read_text())
        self.assertEqual(aggregate["receipt_kind"], "aggregate")
        self.assertEqual(aggregate["model_count"], 2)
        rows = {row["model"]: row for row in aggregate["checks"]}
        kept = rows["nd/other@wallet"]
        self.assertEqual(kept["checks"], old["checks"][1]["checks"])
        self.assertEqual(kept["checked_at"], old["finished_at"])
        self.assertEqual(kept["run_receipt"], str(prior))
        updated = rows["nd/gpt-oss-120b@subscription"]
        self.assertEqual(updated["checks"][0]["status"], "PASS")
        self.assertNotEqual(updated["checked_at"], old["finished_at"])
        run = json.loads(Path(updated["run_receipt"]).read_text())
        self.assertEqual(run["receipt_kind"], "run")
        self.assertEqual([row["model"] for row in run["checks"]], [updated["model"]])
        self.assertEqual(run["checks"][0]["checked_at"], updated["checked_at"])
        self.assertEqual(json.loads(prior.read_text())["checks"][0]["checks"][0]["status"], "FAIL_EMPTY_FINAL")
        self.assertEqual(outcome, {"model": "nd/gpt-oss-120b@subscription", "checks": [{"kind": "text", "status": "PASS"}]})

    def test_merge_preserves_existing_per_model_provenance_and_outcomes_exactly(self):
        untouched = {"model": "old", "checked_at": "earlier", "run_receipt": "original.json",
                     "checks": [{"status": "FAIL", "raw_hash": "abc"}]}
        previous = {"finished_at": "old-finished", "checks": [untouched]}
        current = {"finished_at": "new-finished", "checks": [
            {"model": "new", "checked_at": "now", "run_receipt": "new.json", "checks": [{"status": "PASS"}]}]}
        before = copy.deepcopy(previous)
        aggregate = probe.aggregate_results(previous, current, Path("new.json"), Path("archive.json"))
        self.assertEqual(aggregate["checks"][0], untouched)
        self.assertEqual(previous, before)
        self.assertEqual(aggregate["finished_at"], "new-finished")
        self.assertEqual(aggregate["latest_run_models"], ["new"])

    def test_worker_exception_is_a_failed_run_and_retained_result(self):
        with patch.object(probe, "key_for", return_value="fixture-key"), patch.object(probe.protocol, "configure"), \
             patch.object(probe, "test", side_effect=RuntimeError("fixture failure")), contextlib.redirect_stdout(io.StringIO()):
            code = probe.main(["--model", "gpt-oss-120b", "--workers", "1", "--execute"])
        self.assertEqual(code, 1)
        row = json.loads(self.latest.read_text())["checks"][0]
        self.assertEqual(row["fatal_error_type"], "RuntimeError")
        self.assertIsNotNone(row["checked_at"])
        self.assertTrue(Path(row["run_receipt"]).is_file())


if __name__ == "__main__":
    unittest.main()
