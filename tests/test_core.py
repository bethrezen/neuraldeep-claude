import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from neuraldeep_claude import catalog, integration, transport
from neuraldeep_claude.config import clean_environment, load_env, local_token

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".env").write_text("NEURALDEEP_API_KEY_SUBSCRIPTION=sub-test\nNEURALDEEP_API_KEY_WALLET=wallet-test\n")
        self.model = {"id": "qwen3.8-27b", "type": "chat", "capabilities": {"tools": True, "reasoning": True, "vision": True}, "limit": {"context": 262144, "output": 235929}}
    def tearDown(self):
        self.temp.cleanup()
    def fetch(self, method, path, key, **kwargs):
        if path == "/v1/models":
            return {"data": [self.model]}
        return {"key": {"billing_mode": "subscription" if key == "sub-test" else "wallet"}, "parallel_limit": 16}
    def test_billing_identity_default_and_explicit_wallet(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            data = catalog.refresh(self.root)
        self.assertEqual(catalog.resolve(data, "qwen3.8-27b")["billing"], "subscription")
        self.assertEqual(catalog.resolve(data, "qwen3.8-27b@wallet~medium")["billing"], "wallet")
        self.assertEqual(catalog.resolve(data, "qwen3.8-27b~xhigh")["selected_effort"], "xhigh")
        with self.assertRaises(ValueError):
            catalog.resolve(data, "qwen3.8-27b~ultra")
        self.assertEqual(len(catalog.picker(data)), 2)
        route = catalog.gateway_alias("nd/qwen3.8-27b@wallet~medium")
        self.assertEqual(catalog.resolve(data, route + "[1m]")["selected_effort"], "medium")
        self.assertEqual(catalog.resolve(data, route)["billing"], "wallet")
        self.assertFalse(any("~" in row["model"] for row in catalog.picker(data)))

    def test_legacy_effort_selection_migrates_to_native_effort_setting(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        legacy = "nd/qwen3.8-27b@wallet~medium"
        settings = integration.build_settings(self.root, catalog.gateway_alias(legacy) + "[1m]")
        self.assertEqual(settings["model"], "nd/qwen3.8-27b@wallet")
        self.assertEqual(settings["effortLevel"], "medium")
        for key in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            self.assertEqual(settings["env"][key], "nd/qwen3.8-27b@wallet")
        self.assertIn(catalog.gateway_alias(legacy), settings["modelSettings"])

    def test_evidenced_haiku_input_limit_sets_a_native_compaction_window(self):
        self.model = {
            "id": "claude-haiku-5.5", "type": "chat", "capabilities": {"tools": True},
            "limit": {"context": 1000000, "output": 128000},
        }
        with patch.object(catalog, "request", side_effect=self.fetch):
            data = catalog.refresh(self.root)
        route = "nd/claude-haiku-5.5@wallet"
        settings = integration.build_settings(self.root, route)
        for key in (route, catalog.gateway_alias(route)):
            self.assertEqual(settings["modelSettings"][key]["autoCompactWindow"], 100000)
        self.assertEqual(catalog.resolve(data, route)["input_limit"], 90000)

    def test_preparation_preserves_native_effort_instead_of_resetting_on_model_update(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        home = self.root / "home"
        original = home / ".claude/settings.json"
        original.parent.mkdir(parents=True)
        original.write_text(json.dumps({"effortLevel": "low"}))
        from neuraldeep_claude import services
        with patch.object(integration.Path, "home", return_value=home), patch.object(services, "mcp_config", return_value={"mcpServers": {}}):
            prepared = integration.prepare(self.root, include_project=False)
            self.assertEqual(json.loads(prepared.read_text())["effortLevel"], "low")
            prepared = integration.prepare(self.root, "qwen3.8-27b~medium", include_project=False)
            self.assertEqual(json.loads(prepared.read_text())["effortLevel"], "medium")

    def test_native_per_model_effort_survives_catalog_context_update_and_activation(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        home = self.root / "home"
        original = home / ".claude/settings.json"
        original.parent.mkdir(parents=True)
        base = "nd/qwen3.8-27b@subscription"
        opaque = catalog.gateway_alias(base)
        legacy = catalog.gateway_alias(base + "~medium")
        previous = {"model": base, "effortLevel": "max", "modelSettings": {
            base: {"effortLevel": "medium", "autoCompactWindow": 120000, "customProperty": "keep"},
            opaque: {"effortLevel": "xhigh", "autoCompactWindow": 150000},
            legacy: {"effortLevel": "low", "legacyProperty": True},
            "external-custom-model": {"effortLevel": "xhigh", "customProviderPreference": {"value": 42}},
        }}
        original.write_text(json.dumps(previous))
        # The current provider metadata changes; the recorded user choice does
        # not become a request for a different effort or a session-only max.
        self.model["limit"]["context"] = 196608
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        from neuraldeep_claude import services, skills
        with patch.object(integration.Path, "home", return_value=home), patch.object(services, "mcp_config", return_value={"mcpServers": {}}), patch.object(skills, "install_skills", return_value=[]), patch.object(integration, "install_main_cli", return_value={"preserved": True}):
            prepared = integration.prepare(self.root, include_project=False)
            generated = json.loads(prepared.read_text())
            for key, effort in ((base, "medium"), (opaque, "xhigh"), (legacy, "low")):
                self.assertEqual(generated["modelSettings"][key]["effortLevel"], effort)
                self.assertEqual(generated["modelSettings"][key]["autoCompactWindow"], 196608)
            self.assertEqual(generated["modelSettings"][base]["customProperty"], "keep")
            self.assertEqual(generated["modelSettings"]["external-custom-model"], previous["modelSettings"]["external-custom-model"])
            self.assertTrue(generated["modelSettings"][legacy]["legacyProperty"])
            self.assertFalse(any(options.get("effortLevel") == "max" for options in generated["modelSettings"].values()))
            integration.activate(self.root)
            active = json.loads(original.read_text())
            self.assertEqual(active["modelSettings"], generated["modelSettings"])
            # Repeated install/update remains stable, rather than erasing the
            # preference on its second pass.
            integration.activate(self.root)
            self.assertEqual(json.loads(original.read_text())["modelSettings"], active["modelSettings"])

    def test_project_per_model_settings_merge_without_dropping_user_model_preferences(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        home = self.root / "home"
        original = home / ".claude/settings.json"
        original.parent.mkdir(parents=True)
        base = "nd/qwen3.8-27b@subscription"
        original.write_text(json.dumps({"modelSettings": {base: {"effortLevel": "medium", "userProperty": 1},
                                                         "other-provider": {"effortLevel": "xhigh"}}}))
        project = self.root / "workspace"
        project_config = project / ".claude/settings.json"
        project_config.parent.mkdir(parents=True)
        project_config.write_text(json.dumps({"modelSettings": {base: {"projectProperty": 2}}}))
        from neuraldeep_claude import services
        with patch.object(integration.Path, "home", return_value=home), patch.object(integration.Path, "cwd", return_value=project), patch.object(services, "mcp_config", return_value={"mcpServers": {}}):
            prepared = integration.prepare(self.root)
        generated = json.loads(prepared.read_text())["modelSettings"]
        self.assertEqual(generated[base], {"effortLevel": "medium", "userProperty": 1,
                                          "projectProperty": 2, "autoCompactWindow": 262144})
        self.assertEqual(generated["other-provider"], {"effortLevel": "xhigh"})

    def test_picker_policy_is_embedded_and_reload_applies_changes_without_paid_calls(self):
        config = self.root / "config/picker-policy.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"schema": 1, "hide_until_probe_passes": ["qwen3.8-27b"]}))
        with patch.object(catalog, "request", side_effect=self.fetch):
            refreshed = catalog.refresh(self.root)
        self.assertEqual(refreshed["picker_policy"]["hide_until_probe_passes"], ["qwen3.8-27b"])
        self.assertEqual(catalog.picker(refreshed), [])
        config.write_text(json.dumps({"schema": 1, "excluded_upstream_ids": ["qwen3.8-27b"]}))
        with patch.object(catalog, "request", side_effect=AssertionError("Metadata reload must not call the network")):
            loaded = catalog.load(self.root)
        self.assertEqual(catalog.picker(loaded), [])
        with self.assertRaises(catalog.RetiredModelError):
            catalog.resolve(loaded, "qwen3.8-27b")

    def test_main_activation_does_not_silently_replace_retired_selection(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        config = self.root / "config/picker-policy.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"schema": 1, "excluded_upstream_ids": ["qwen3.8-27b"]}))
        home = self.root / "home"
        settings = home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        original = {"model": "nd/qwen3.8-27b@wallet~medium"}
        settings.write_text(json.dumps(original))
        (self.root / ".local/activation.json").write_text('{"port":8787}')
        with patch.object(integration.Path, "home", return_value=home), self.assertRaises(catalog.RetiredModelError):
            integration.activate(self.root)
        self.assertEqual(json.loads(settings.read_text()), original)

    def test_partial_probe_timestamps_do_not_age_unchecked_models_as_fresh(self):
        (self.root / ".local").mkdir()
        (self.root / ".local/model-probes.json").write_text(json.dumps({
            "finished_at": "2026-11-03T03:00:00Z", "checks": [
                {"model": "nd/qwen3.8-27b@subscription", "checked_at": "2026-11-02T01:00:00Z",
                 "checks": [{"kind": "text", "status": "HTTP_ERROR", "http_status": 401}]},
                {"model": "nd/qwen3.8-27b@wallet", "checked_at": "2026-11-03T02:00:00Z",
                 "checks": [{"kind": "text", "status": "PASS"}]},
            ]}))
        with patch.object(catalog, "request", side_effect=self.fetch):
            refreshed = catalog.refresh(self.root)
        old = refreshed["models"]["nd/qwen3.8-27b@subscription"]["last_probe"]
        new = refreshed["models"]["nd/qwen3.8-27b@wallet"]["last_probe"]
        self.assertEqual(old["at"], "2026-11-02T01:00:00Z")
        self.assertEqual(old["status"], "failed")
        self.assertEqual(new["at"], "2026-11-03T02:00:00Z")
        self.assertEqual(new["status"], "passed")
    def test_misconfigured_wallet_key_fails_without_replacing_catalog(self):
        original = self.fetch
        def wrong(method, path, key, **kwargs):
            value = original(method, path, key, **kwargs)
            if path == "/v1/limits": value["key"]["billing_mode"] = "subscription"
            return value
        with patch.object(catalog, "request", side_effect=wrong), self.assertRaisesRegex(ValueError, "wallet key"):
            catalog.refresh(self.root)
        self.assertFalse((self.root / ".local/catalog.json").exists())
    def test_model_context_and_effort_do_not_use_claude_impersonation(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        settings = integration.build_settings(self.root)
        self.assertEqual(settings["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "262144")
        self.assertEqual(settings["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "128000")
        self.assertEqual(settings["model"], "nd/qwen3.8-27b@subscription")
        self.assertFalse(any("behavesAs" in row for row in settings["modelPicker"]["options"]))
        self.assertEqual(settings["modelSettings"][settings["model"]]["autoCompactWindow"], 262144)
        self.assertEqual(settings["env"]["ENABLE_TOOL_SEARCH"], "force")
        self.assertIs(settings["sandbox"]["enabled"], False)
        self.assertIs(settings["sandbox"]["allowUnsandboxedCommands"], True)
        self.assertNotIn("DISABLE_AUTOUPDATER", settings["env"])
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", settings["env"])
        self.assertFalse(any("proxy" in key.lower() for key in settings["env"]))
        self.assertEqual(settings["env"]["ANTHROPIC_AUTH_TOKEN"], "")
        self.assertEqual(settings["env"]["CLAUDE_CODE_USE_BEDROCK"], "0")

    def test_main_activation_keeps_neuraldeep_and_restores_native_updates(self):
        with patch.object(catalog, "request", side_effect=self.fetch):
            catalog.refresh(self.root)
        home = self.root / "home"
        folder = home / ".claude"
        folder.mkdir(parents=True)
        (folder / "settings.json").write_text(json.dumps({"theme": "keep", "env": {
            "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "HTTP_PROXY": "old-proxy-credentials-must-not-be-restored", "DISABLE_TELEMETRY": "1"}}))
        global_path = home / ".claude.json"
        global_path.write_text(json.dumps({"installMethod": "native", "autoUpdates": False,
            "customPreference": "keep", "mcpServers": {"other": {"command": "untouched"}}}))
        from neuraldeep_claude import services, skills
        servers = {"mcpServers": {"neuraldeep-fixture": {"command": "python", "args": ["fixture.py"]}}}
        with patch.object(integration.Path, "home", return_value=home), patch.object(services, "mcp_config", return_value=servers), patch.object(skills, "install_skills", return_value=[]), patch.object(integration, "install_main_cli", return_value={"preserved": True, "installed": False}):
            receipt = integration.activate(self.root)
        settings = json.loads((folder / "settings.json").read_text())
        self.assertEqual(settings["theme"], "keep")
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787")
        self.assertEqual(settings["env"]["ANTHROPIC_API_KEY"], local_token(self.root))
        self.assertEqual(settings["env"]["ENABLE_TOOL_SEARCH"], "force")
        self.assertEqual(settings["env"]["DISABLE_TELEMETRY"], "1")
        self.assertFalse(any("proxy" in key.lower() for key in settings["env"]))
        self.assertNotIn("DISABLE_AUTOUPDATER", settings["env"])
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", settings["env"])
        self.assertFalse(settings["sandbox"]["enabled"])
        self.assertTrue(any(" start " in row["hooks"][0]["command"] for row in settings["hooks"]["SessionStart"]))
        global_config = json.loads(global_path.read_text())
        self.assertTrue(global_config["autoUpdates"])
        self.assertEqual(global_config["installMethod"], "native")
        self.assertEqual(global_config["customPreference"], "keep")
        self.assertEqual(global_config["mcpServers"]["other"], {"command": "untouched"})
        self.assertIn("neuraldeep-fixture", global_config["mcpServers"])
        self.assertEqual(receipt["native_cli_policy"], integration.NATIVE_CLI_POLICY)
        prior = next((self.root / ".local/backups").glob("claude-global-*.json"))
        self.assertFalse(json.loads(prior.read_text())["autoUpdates"])
    def test_env_never_executes_and_proxy_variants_removed(self):
        (self.root / ".env").write_text("TOKEN='$(touch /not-executed)'\n# ignored\n")
        self.assertEqual(load_env(self.root)["TOKEN"], "$(touch /not-executed)")
        env = clean_environment({"HTTP_PROXY": "bad", "https_proxy": "bad", "X_HTTPS_PROXY": "bad", "TMPDIR": "/tmp", "ANTHROPIC_API_KEY": "old"})
        self.assertEqual(env, {"TMPDIR": "/tmp"})
        (self.root / ".env").write_text('TOKEN="a # b" # comment\nPLAIN=sk_abc#def # comment\n')
        from neuraldeep_claude.services import load_env as service_env
        self.assertEqual(load_env(self.root), {"TOKEN": "a # b", "PLAIN": "sk_abc#def"})
        self.assertEqual(service_env(self.root)["TOKEN"], load_env(self.root)["TOKEN"])
    def test_active_custom_port_is_preserved(self):
        (self.root / ".local").mkdir()
        (self.root / ".local/activation.json").write_text('{"port":9000}')
        self.assertEqual(integration.active_port(self.root), 9000)
    def test_local_credential_is_stable_and_not_upstream_key(self):
        token = local_token(self.root)
        self.assertEqual(token, local_token(self.root))
        self.assertNotIn(token, load_env(self.root).values())
        if os.name != "nt":
            self.assertEqual((self.root / ".local/gateway-token").stat().st_mode & 0o777, 0o600)
    def test_sse_multiline_final_usage_and_upstream_error(self):
        frames = [b'data: {"choices":[],\n', b'data: "usage":{"prompt_tokens":42}}\n', b'\n', b'data: [DONE]\n', b'\n']
        self.assertEqual(list(transport.sse_chunks(frames))[0]["usage"]["prompt_tokens"], 42)
        with self.assertRaises(transport.UpstreamError):
            list(transport.sse_chunks([b'data: {"error":{"message":"failure"}}\n', b'\n']))

if __name__ == "__main__": unittest.main()
