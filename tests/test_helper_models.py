import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuraldeep_claude import catalog, helper_models, integration


TARGET = "nd/qwen3.8-27b-noreason@subscription"


class HelperModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config/helper-models.json"
        self.config.parent.mkdir()
        self.data = {"models": {TARGET: {"id": TARGET, "upstream_id": "qwen3.8-27b-noreason",
                         "billing": "subscription", "capabilities": {"tools": True, "reasoning": False},
                         "limit": {"context": 262144, "output": 235929}}}, "aliases": {}}
        self.catalog_patch = patch.object(catalog, "load", return_value=self.data)
        self.load = self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)

    def write(self, target=TARGET):
        self.config.write_text(json.dumps({"schema": 1, "auto_permission_classifier": target}))

    def test_missing_and_null_configuration_do_not_override_native_selection(self):
        self.assertIsNone(helper_models.classifier_model(self.root))
        self.write(None)
        self.assertIsNone(helper_models.classifier_model(self.root, opaque=True))
        self.load.assert_not_called()

    def test_raw_and_opaque_routes_resolve_the_same_exact_subscription_without_mutation(self):
        self.write()
        previous = copy.deepcopy(self.data)
        self.assertEqual(helper_models.classifier_model(self.root), TARGET)
        opaque = helper_models.classifier_model(self.root, opaque=True)
        self.assertEqual(opaque, catalog.gateway_alias(TARGET))
        self.assertEqual(catalog.resolve(self.data, opaque)["id"], TARGET)
        self.assertEqual(self.data, previous)

    def test_configuration_rejects_wallet_implicit_alias_and_legacy_effort(self):
        for value in (TARGET.replace("@subscription", "@wallet"), "qwen3.8-27b-noreason",
                      TARGET + "~low", catalog.gateway_alias(TARGET), "", True):
            self.write(value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "exact base"):
                helper_models.classifier_model(self.root)
        self.load.assert_not_called()

    def test_missing_subscription_does_not_fall_back_to_an_available_wallet(self):
        self.write()
        wallet = TARGET.replace("@subscription", "@wallet")
        model = self.data["models"].pop(TARGET)
        self.data["models"][wallet] = model | {"id": wallet, "billing": "wallet"}
        with self.assertRaisesRegex(ValueError, "classifier is unavailable"):
            helper_models.classifier_model(self.root)

    def test_retired_and_hidden_models_are_not_selected(self):
        self.write()
        upstream = self.data["models"][TARGET]["upstream_id"]
        for field, message in (("excluded_upstream_ids", "classifier is unavailable"),
                               ("hide_until_probe_passes", "hidden until")):
            self.data["picker_policy"] = {field: [upstream]}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                helper_models.classifier_model(self.root)

    def test_validated_helper_keeps_main_model_max_effort_and_updater_policy(self):
        self.write()
        primary = "nd/qwen3.8-27b@subscription"
        self.data["models"][primary] = {"id": primary, "upstream_id": "qwen3.8-27b",
            "billing": "subscription", "limit": {"context": 262144, "output": 235929},
            "efforts": ["low", "medium", "xhigh"]}
        self.data["aliases"]["qwen3.8-27b"] = primary
        settings = integration.build_settings(self.root)
        self.assertEqual(settings["model"], primary)
        self.assertEqual(settings["effortLevel"], "max")
        self.assertEqual(settings["env"][helper_models.CLASSIFIER_ENV], TARGET)
        self.assertEqual(settings["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], primary)
        self.assertEqual(settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], primary)
        self.assertNotIn("DISABLE_AUTOUPDATER", settings["env"])
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", settings["env"])

    def test_null_configuration_removes_previously_installed_override_on_prepare(self):
        self.write(None)
        home = self.root / "home"
        original = home / ".claude/settings.json"
        original.parent.mkdir(parents=True)
        original.write_text(json.dumps({"theme": "keep", "env": {
            helper_models.CLASSIFIER_ENV: "old-classifier", "UNRELATED": "keep"}}))
        from neuraldeep_claude import services
        with patch.object(integration.Path, "home", return_value=home), patch.object(services, "mcp_config", return_value={"mcpServers": {}}):
            path = integration.prepare(self.root, TARGET, include_project=False)
        result = json.loads(path.read_text())
        self.assertNotIn(helper_models.CLASSIFIER_ENV, result["env"])
        self.assertEqual(result["env"]["UNRELATED"], "keep")
        self.assertEqual(result["theme"], "keep")


if __name__ == "__main__":
    unittest.main()
