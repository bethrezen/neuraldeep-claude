import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuraldeep_claude import catalog, desktop


def fixture():
    models = {}
    for name, billing, context in (
        ("qwen3.8-27b", "subscription", 262144),
        ("qwen3.8-27b", "wallet", 262144),
        ("claude-sonnet-5", "subscription", 1000000),
        ("claude-sonnet-5", "wallet", 1000000),
        ("qwen3.6-unlim", "subscription", 46000),
    ):
        identity = f"nd/{name}@{billing}"
        models[identity] = {
            "id": identity, "upstream_id": name, "billing": billing,
            "capabilities": {"tools": True, "reasoning": True},
            "limit": {"context": context, "output": 32768},
            "efforts": [] if name == "qwen3.6-unlim" else ["low", "high"],
            "effort_status": "documented",
        }
    return {"models": models, "aliases": {}}


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".local").mkdir()
        (self.root / ".local/catalog.json").write_text(json.dumps(fixture()))
        (self.root / ".env").write_text(
            "NEURALDEEP_API_KEY_SUBSCRIPTION=do-not-copy-subscription\n"
            "NEURALDEEP_API_KEY_WALLET=do-not-copy-wallet\n"
        )
        self.process_scan = patch.object(desktop, "_existing_native_processes", return_value=[])
        self.process_scan.start()
        self.addCleanup(self.process_scan.stop)
        preflight = patch("neuraldeep_claude.desktop_runtime.inspect",
                          return_value={"status": "UNVERIFIED", "reason": "unit-fixture"})
        preflight.start()
        self.addCleanup(preflight.stop)

    def test_profile_routes_only_local_token_and_preserves_billing(self):
        receipt = desktop.prepare(self.root, 9009)
        config = json.loads(Path(receipt["configuration"]).read_text())
        self.assertEqual(config["inferenceProvider"], "gateway")
        self.assertEqual(config["inferenceCredentialKind"], "static")
        self.assertEqual(config["inferenceGatewayBaseUrl"], "http://127.0.0.1:9009")
        self.assertEqual(config["inferenceGatewayApiKey"],
                         (self.root / ".local/gateway-token").read_text())
        serialized = json.dumps(config)
        self.assertNotIn("do-not-copy", serialized)
        self.assertNotIn(config["inferenceGatewayApiKey"], json.dumps(receipt))
        self.assertEqual(len(config["inferenceModels"]), len(catalog.picker(fixture())))
        self.assertIs(config["modelDiscoveryEnabled"], False)
        labels = [row["display_name"] for row in catalog.discovery_data(fixture())["data"]]
        self.assertTrue(any("КОШЕЛЁК" in label for label in labels))
        self.assertTrue(any("ПОДПИСКА" in label for label in labels))
        self.assertEqual(receipt["default_model_billing"], "subscription")
        self.assertEqual(receipt["default_provider_model"], "nd/qwen3.8-27b@subscription")
        self.assertFalse(receipt["ui_verified"])
        if os.name != "nt":
            self.assertEqual(Path(receipt["configuration"]).stat().st_mode & 0o777, 0o600)

    def test_effort_profiles_do_not_change_routes_or_advertise_fixed_effort(self):
        receipt = desktop.prepare(self.root)
        config = json.loads(Path(receipt["configuration"]).read_text())
        for row in config["inferenceModels"]:
            provider = catalog.resolve(fixture(), row["name"])
            if provider["upstream_id"] == "qwen3.8-27b":
                self.assertEqual(row["behavesAs"], desktop.EFFORT_COMPATIBILITY_MODEL)
                self.assertNotIn("supports1m", row)
            elif provider["upstream_id"] == "qwen3.6-unlim":
                self.assertNotIn("behavesAs", row)
                self.assertNotIn("supports1m", row)
            elif provider["upstream_id"] == "claude-sonnet-5":
                self.assertEqual(row["behavesAs"], "claude-sonnet-5")
                self.assertTrue(row["supports1m"])
        self.assertTrue(receipt["non_claude_options_require_ui_verification"])
        self.assertTrue(receipt["arbitrary_context_options_require_ui_verification"])
        self.assertNotIn("modelCatalogUrl", config)
        self.assertNotIn("disabledBuiltinTools", config)
        self.assertTrue(config["toolSearchEnabled"])
        for key in ("modelPrefer1mContext", "inferenceModelPricingEnabled", "builtinBrowserEnabled",
                    "chatAdvancedFileAnalysisEnabled", "chatTabEnabled"):
            self.assertIs(config[key], True)
        self.assertEqual(config["coworkEgressAllowedHosts"], ["*"])
        self.assertNotIn("allowedWorkspaceFolders", config)
        self.assertNotIn("strictSandboxMode", config)
        app = json.loads((Path(receipt["profile"]) / "claude_desktop_config.json").read_text())
        self.assertTrue(app["preferences"]["secureVmFeaturesEnabled"])

    def test_native_configuration_disables_telemetry_without_blocking_content_services(self):
        receipt = desktop.prepare(self.root)
        config = json.loads(Path(receipt["configuration"]).read_text())
        for setting in (
            "disableEssentialTelemetry", "disableNonessentialTelemetry",
            "disableDeploymentModeChooser", "skipWebFetchPreflight",
        ):
            with self.subTest(setting=setting):
                self.assertIs(config[setting], True)
        self.assertIs(config["disableNonessentialServices"], False)
        self.assertIs(config["disableAutoUpdates"], False)
        self.assertIs(config["modelCatalogEnabled"], True)
        self.assertNotIn("bootstrapEnabled", config)
        self.assertNotIn("bootstrapUrl", config)
        self.assertIs(config["installedUpdateEnforcementEnabled"], False)
        self.assertEqual(config["inferenceCredentialKind"], "static")
        self.assertNotIn("inferenceAnthropicApiKey", config)
        self.assertNotIn("modelCatalogUrl", config)
        # Local tools remain available alongside the native service settings.
        self.assertTrue(config["managedMcpServers"])
        self.assertNotIn("disabledBuiltinTools", config)

    def test_native_arguments_only_apply_sandbox_preference_and_forward_app_arguments(self):
        self.assertEqual(desktop._launch_arguments([]), ["--no-sandbox"])
        self.assertEqual(desktop._launch_arguments(["claude://open", "--ozone-platform=x11"]),
                         ["--no-sandbox", "claude://open", "--ozone-platform=x11"])

    def test_launch_environment_uses_config_flags_without_private_proxy_or_update_bundle(self):
        original = {"HTTP_PROXY": "http://127.0.0.1:20171", "https_proxy": "http://ambient",
                    "DISABLE_AUTOUPDATER": "1", "DISABLE_UPDATES": "1",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "NEURALDEEP_API_KEY_WALLET": "private"}
        with patch.dict(os.environ, original):
            result = desktop._launch_environment()
            self.assertEqual({key: os.environ[key] for key in original}, original)
        self.assertFalse(any("proxy" in key.lower() for key in result))
        for name in ("DISABLE_AUTOUPDATER", "DISABLE_UPDATES", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "NEURALDEEP_API_KEY_WALLET"):
            self.assertNotIn(name, result)
        self.assertEqual(result["DISABLE_TELEMETRY"], "1")
        self.assertEqual(result["DISABLE_ERROR_REPORTING"], "1")
        self.assertEqual(result["DO_NOT_TRACK"], "1")

    def test_native_process_scan_is_read_only_and_platform_specific(self):
        self.process_scan.stop()
        cases = (
            ("linux", "/usr/lib/claude-desktop/claude-desktop",
             "11 claude\n12 claude-desktop\n13 /usr/lib/claude-desktop/claude-desktop\n", [12, 13]),
            ("darwin", "/Applications/Claude.app/Contents/MacOS/Claude",
             "11 claude\n12 /Applications/Claude.app/Contents/MacOS/Claude\n"
             "13 /Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer)\n", [12, 13]),
            ("win32", r"C:\Apps\Claude\Claude.exe", json.dumps([
                {"ProcessId": 11, "ExecutablePath": r"C:\Users\Tester\.local\bin\claude.exe"},
                {"ProcessId": 12, "ExecutablePath": r"c:\apps\CLAUDE\CLAUDE.EXE"},
            ]), [12]),
        )
        for platform, native, listing, expected in cases:
            with self.subTest(platform=platform), \
                 patch.object(desktop.sys, "platform", platform), \
                 patch.object(desktop.subprocess, "run") as run:
                run.return_value.stdout = listing
                self.assertEqual(desktop._existing_native_processes(native), expected)
                command = run.call_args.args[0]
                self.assertEqual(command[0], "powershell.exe" if platform == "win32" else "ps")
                self.assertNotIn("-f", command)
                self.assertEqual(run.call_args.kwargs["timeout"], 10)
                if platform == "win32":
                    self.assertIn("Get-CimInstance", command[-1])
                    self.assertIn("-Property Name,ProcessId,ExecutablePath", command[-1])
                    self.assertNotIn("CommandLine", command[-1])
                    self.assertEqual(run.call_args.kwargs["encoding"], "utf-8-sig")

    def test_windows_cli_basename_does_not_block_desktop_and_unknown_path_fails(self):
        self.process_scan.stop()
        native = r"C:\Apps\Claude\Claude.exe"
        with patch.object(desktop.sys, "platform", "win32"), \
             patch.object(desktop.subprocess, "run") as run:
            run.return_value.stdout = json.dumps([
                {"ProcessId": 11, "ExecutablePath": r"C:\Users\Tester\.local\bin\claude.exe"},
            ])
            self.assertEqual(desktop._existing_native_processes(native), [])
            run.return_value.stdout = json.dumps([{"ProcessId": 12, "ExecutablePath": None}])
            with self.assertRaisesRegex(RuntimeError, "Cannot read.*executable path"):
                desktop._existing_native_processes(native)
            run.return_value.stdout = "not valid JSON"
            with self.assertRaisesRegex(RuntimeError, "Cannot decode.*executable paths"):
                desktop._existing_native_processes(native)

    def test_existing_instance_prevents_native_spawn_until_restart(self):
        (self.root / ".local/desktop-activation.json").write_text('{"primary":true}')
        with patch.object(desktop, "executable", return_value="/native/Claude"), \
             patch.object(desktop, "_existing_native_processes", return_value=[4321]), \
             patch.object(desktop.subprocess, "Popen") as process:
            with self.assertRaisesRegex(RuntimeError, "Close Claude Desktop.*4321"):
                desktop.launch(self.root)
            process.assert_not_called()

    def test_every_opaque_option_resolves_exact_billing_and_effort(self):
        data = fixture()
        receipt = desktop.prepare(self.root)
        configured = json.loads(Path(receipt["configuration"]).read_text())["inferenceModels"]
        rows = catalog.discovery_data(data)["data"]
        actual = {row["id"]: row for row in rows}
        self.assertEqual({row["name"] for row in configured}, set(actual))
        for row in catalog.picker(data):
            alias = catalog.gateway_alias(row["model"])
            self.assertIn(alias, actual)
            expected = catalog.resolve(data, row["model"])
            resolved = catalog.resolve(data, alias)
            self.assertEqual(resolved["id"], expected["id"])
            self.assertEqual(resolved.get("selected_effort"), expected.get("selected_effort"))
            self.assertIn(expected["upstream_id"], actual[alias]["display_name"])

    def test_native_service_configuration_follows_individual_switches(self):
        (self.root / ".local/services.json").write_text('{"enabled":{"images":false,"ocr":true}}')
        receipt = desktop.prepare(self.root)
        config = json.loads(Path(receipt["configuration"]).read_text())
        servers = {server["name"]: server for server in config["managedMcpServers"]}
        self.assertIn("neuraldeep-ocr", servers)
        self.assertNotIn("neuraldeep-images", servers)
        ocr = servers["neuraldeep-ocr"]
        self.assertEqual(ocr["transport"], "stdio")
        self.assertIn(str(self.root), ocr["args"])
        self.assertEqual(ocr["args"][-2:], ["mcp", "ocr"])
        self.assertNotIn("toolPolicy", ocr)
        self.assertNotIn("do-not-copy", json.dumps(servers))

    def test_service_sync_preserves_models_other_connectors_and_tool_policy(self):
        profile = self.root / "native/Claude-3p"
        config_path = profile / "configLibrary" / (desktop.PROFILE_ID + ".json")
        config_path.parent.mkdir(parents=True)
        models = [{"name": "selected-model", "labelOverride": "Keep my selection"}]
        original = {"inferenceModels": models, "defaultModelEffort": "medium", "managedMcpServers": [
            {"name": "unrelated", "transport": "stdio", "command": "other-app"},
            {"name": "neuraldeep-ocr", "transport": "stdio", "command": "old-path", "toolPolicy": {"ocr_extract": "ask"}},
            {"name": "neuraldeep-images", "transport": "stdio", "command": "old-path"},
        ]}
        config_path.write_text(json.dumps(original))
        (self.root / ".local/desktop-activation.json").write_text('{"primary":true}')
        (self.root / ".local/services.json").write_text('{"enabled":{"images":false}}')
        with patch.object(desktop, "_primary_profiles", return_value=(self.root / "native/Claude", profile)):
            result = desktop.sync_services(self.root)
            again = desktop.sync_services(self.root)
        actual = json.loads(config_path.read_text())
        self.assertTrue(result["updated"])
        self.assertFalse(again["updated"])
        self.assertEqual(json.loads(Path(result["backup"]).read_text()), original)
        self.assertEqual(actual["inferenceModels"], models)
        self.assertEqual(actual["defaultModelEffort"], "medium")
        servers = {server["name"]: server for server in actual["managedMcpServers"]}
        self.assertEqual(servers["unrelated"]["command"], "other-app")
        self.assertNotIn("neuraldeep-images", servers)
        self.assertEqual(servers["neuraldeep-ocr"]["toolPolicy"], {"ocr_extract": "ask"})
        self.assertNotEqual(servers["neuraldeep-ocr"]["command"], "old-path")

    def test_service_sync_does_not_activate_desktop(self):
        with patch.object(desktop, "_primary_profiles") as profiles:
            result = desktop.sync_services(self.root)
        self.assertFalse(result["updated"])
        profiles.assert_not_called()

    def test_reprepare_preserves_own_preferences_and_stable_entry(self):
        first = desktop.prepare(self.root)
        app = Path(first["profile"]) / "claude_desktop_config.json"
        app.write_text(json.dumps({"preferences": {"theme": "dark"}}))
        second = desktop.prepare(self.root, 9001)
        self.assertEqual(first["configuration"], second["configuration"])
        config = json.loads(app.read_text())
        self.assertEqual(config["preferences"]["theme"], "dark")
        self.assertEqual(config["deploymentMode"], "3p")
        meta = json.loads((Path(second["profile"]) / "configLibrary/_meta.json").read_text())
        self.assertEqual(meta["appliedId"], desktop.PROFILE_ID)

    def test_launch_bypasses_old_wrapper_without_starting_a_proxy_or_changing_parent_environment(self):
        (self.root / ".local/desktop-activation.json").write_text('{"primary":true}')
        with patch.object(desktop.sys, "platform", "linux"), \
             patch.object(desktop, "_primary_profiles", return_value=(self.root / "native/Claude", self.root / "native/Claude-3p")), \
             patch.object(desktop, "executable", return_value="/usr/lib/claude-desktop/claude-desktop"), \
             patch.dict(os.environ, {"HTTP_PROXY": "http://proxy.invalid", "all_proxy": "socks://proxy.invalid",
                                     "NEURALDEEP_API_KEY_WALLET": "must-not-pass"}), \
             patch.object(desktop.subprocess, "Popen") as process:
            process.return_value.pid = 12345
            receipt = desktop.launch(self.root)
        args, kwargs = process.call_args
        self.assertEqual(args[0][0], "/usr/lib/claude-desktop/claude-desktop")
        self.assertEqual(args[0], ["/usr/lib/claude-desktop/claude-desktop", "--no-sandbox"])
        self.assertNotIn("CLAUDE_USER_DATA_DIR", kwargs["env"])
        self.assertNotIn("HTTP_PROXY", kwargs["env"])
        self.assertNotIn("all_proxy", kwargs["env"])
        self.assertNotIn("NO_PROXY", kwargs["env"])
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", kwargs["env"])
        self.assertNotIn("DISABLE_AUTOUPDATER", kwargs["env"])
        self.assertNotIn("NEURALDEEP_API_KEY_WALLET", kwargs["env"])
        self.assertTrue(receipt["launch_requested"])
        self.assertNotIn("egress_guard", receipt)
        self.assertEqual(receipt["network_policy"], "configuration flags; NeuralDeep direct")

    def test_launch_requires_explicit_main_activation(self):
        with patch.object(desktop.subprocess, "Popen") as process:
            with self.assertRaisesRegex(ValueError, "install --activate"):
                desktop.launch(self.root)
            process.assert_not_called()
        self.assertFalse((self.root / ".local/desktop-profile").exists())

    def test_platform_executable_discovery_and_explicit_override(self):
        for platform, expected in (
            ("linux", "/usr/lib/claude-desktop/claude-desktop"),
            ("darwin", "/Applications/Claude.app/Contents/MacOS/Claude"),
            ("win32", "/windows/Programs/Claude/Claude.exe"),
        ):
            with self.subTest(platform=platform), \
                 patch.object(desktop.sys, "platform", platform), \
                 patch.dict(os.environ, {"LOCALAPPDATA": "/windows"}), \
                 patch.object(desktop.shutil, "which", return_value=None), \
                 patch.object(Path, "glob", return_value=[]), \
                 patch.object(Path, "is_file", lambda path: str(path) == expected):
                self.assertEqual(desktop.executable(self.root), expected)
        fake = self.root / "native-desktop"
        fake.write_text("native executable placeholder")
        (self.root / ".env").write_text(f"NEURALDEEP_CLAUDE_DESKTOP_EXECUTABLE={fake}\n")
        self.assertEqual(desktop.executable(self.root), str(fake))

    def test_primary_activation_preserves_history_preferences_and_other_profiles(self):
        regular = self.root / "user-config/Claude"
        primary = self.root / "user-config/Claude-3p"
        regular.mkdir(parents=True)
        (regular / "claude_desktop_config.json").write_text('{"preferences":{"theme":"dark"}}')
        (regular / "history-must-stay.json").write_text('{"preserved":true}')
        (primary / "configLibrary").mkdir(parents=True)
        (primary / "configLibrary/_meta.json").write_text(json.dumps({
            "appliedId": "other", "entries": [{"id": "other", "name": "Previous gateway"}],
        }))
        with patch.object(desktop, "_primary_profiles", return_value=(regular, primary)), \
             patch.object(desktop, "install_main_launcher", return_value={"updated": False, "reason": "test"}):
            receipt = desktop.activate(self.root)
        self.assertTrue(receipt["primary"])
        self.assertEqual(receipt["profile"], str(primary))
        self.assertEqual(len(receipt["backups"]), 2)
        self.assertTrue(all(Path(item["backup"]).is_file() for item in receipt["backups"]))
        old = json.loads((regular / "claude_desktop_config.json").read_text())
        self.assertEqual(old["preferences"]["theme"], "dark")
        self.assertEqual(old["deploymentMode"], "3p")
        self.assertEqual((regular / "history-must-stay.json").read_text(), '{"preserved":true}')
        meta = json.loads((primary / "configLibrary/_meta.json").read_text())
        self.assertEqual(len(meta["entries"]), 2)
        self.assertEqual(meta["appliedId"], desktop.PROFILE_ID)
        self.assertFalse((self.root / ".local/desktop-profile").exists())

    def test_main_desktop_changes_preserve_shared_relay_and_other_apps(self):
        fake_home = self.root / "fake-home"
        sentinels = {
            ".config/claude-proxy-relay/settings.json":
                '{"upstream":"nl.notevil.ai:8888","listen":"127.0.0.1:20171"}\n',
            ".config/systemd/user/claude-proxy-relay.service":
                "[Service]\nExecStart=/shared/claude-proxy-relay.py\n",
            ".config/systemd/user/claude-proxy-relay.service.d/override.conf":
                "[Service]\nEnvironment=CLAUDE_PROXY_RELAY_SETTINGS=/independent/settings.json\n",
            ".local/bin/claude-proxy-relay.py": "# Shared relay; owned outside this installer.\n",
            ".codex/config.toml": 'http_proxy = "http://127.0.0.1:20171"\n',
            ".config/ChatGPT/settings.json": '{"proxy":"http://127.0.0.1:20171"}\n',
        }
        for relative, content in sentinels.items():
            target = fake_home / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            target.chmod(0o600)

        def snapshot():
            result = {}
            for relative in sentinels:
                target = fake_home / relative
                info = target.stat()
                result[relative] = (
                    target.read_bytes(), info.st_mode, info.st_mtime_ns,
                    info.st_ino, info.st_uid, info.st_gid,
                )
            return result

        before = snapshot()
        # Replacing this Claude-only wrapper must not operate on the shared
        # service it previously referenced, or on another app's proxy settings.
        wrapper = fake_home / ".local/bin/claude-desktop"
        wrapper.write_text("#!/bin/sh\n# claude-proxy-relay.service\nexec old-claude\n")
        proxy_env = {"HTTP_PROXY": "http://127.0.0.1:20171",
                     "CLAUDE_PROXY_RELAY_SETTINGS": "/independent/settings.json"}
        with patch.object(desktop.sys, "platform", "linux"), \
             patch.object(Path, "home", return_value=fake_home), \
             patch.dict(os.environ, proxy_env), \
             patch.object(desktop, "_primary_profiles", return_value=(
                 fake_home / ".config/Claude", fake_home / ".config/Claude-3p")), \
             patch.object(desktop, "executable", return_value="/native/Claude"), \
             patch.object(desktop.subprocess, "run") as run, \
             patch.object(desktop.subprocess, "Popen") as process:
            process.return_value.pid = 123
            receipt = desktop.activate(self.root)
            desktop.sync_services(self.root)
            desktop.launch(self.root)
            self.assertEqual({key: os.environ[key] for key in proxy_env}, proxy_env)
        self.assertTrue(receipt["launcher"]["updated"])
        self.assertEqual(snapshot(), before)
        run.assert_not_called()
        process.assert_called_once()
        self.assertEqual(process.call_args.args[0][0], "/native/Claude")
        self.assertEqual(process.call_args.args[0], ["/native/Claude", "--no-sandbox"])

    def test_primary_launch_uses_native_profile_without_override(self):
        regular = self.root / "native/Claude"
        primary = self.root / "native/Claude-3p"
        with patch.object(desktop, "_primary_profiles", return_value=(regular, primary)), \
             patch.object(desktop, "install_main_launcher", return_value={"updated": False, "reason": "test"}), \
             patch.object(desktop, "executable", return_value="/native/Claude"), \
             patch.object(desktop.subprocess, "Popen") as process, \
             patch.dict(os.environ, {"CLAUDE_USER_DATA_DIR": "/unrelated-profile"}):
            process.return_value.pid = 123
            desktop.activate(self.root)
            result = desktop.launch(self.root)
        self.assertTrue(result["primary"])
        self.assertNotIn("CLAUDE_USER_DATA_DIR", process.call_args.kwargs["env"])
        self.assertFalse((self.root / ".local/desktop-profile").exists())

    def test_main_launcher_backs_up_only_known_wrapper_and_forwards_arguments(self):
        fake_home = self.root / "fake-home"
        wrapper = fake_home / ".local/bin/claude-desktop"
        wrapper.parent.mkdir(parents=True)
        original = "#!/bin/sh\n# claude-proxy-relay.service\nexec old-proxy-app\n"
        wrapper.write_text(original)
        with patch.object(desktop.sys, "platform", "linux"), \
             patch.object(Path, "home", return_value=fake_home):
            result = desktop.install_main_launcher(self.root)
            again = desktop.install_main_launcher(self.root)
        self.assertEqual(Path(result["backup"]).read_text(), original)
        self.assertTrue(result["updated"])
        self.assertFalse(again["updated"])
        self.assertIn('"$@"', wrapper.read_text())
        self.assertIn("app_args=sys.argv[1:]", wrapper.read_text())
        self.assertNotIn("proxy-relay", wrapper.read_text())

    def test_mac_and_windows_shortcuts_start_gateway_before_native_app(self):
        fake_home = self.root / "fake-home"
        for platform in ("darwin", "win32"):
            with self.subTest(platform=platform), \
                 patch.object(desktop.sys, "platform", platform), \
                 patch.object(Path, "home", return_value=fake_home), \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(fake_home / "Local")}):
                result = desktop.install_main_launcher(self.root)
                path = Path(result["path"])
                self.assertTrue(result["starts_gateway"])
                self.assertTrue(path.is_file())
                self.assertIn("ensure_gateway", path.read_text())
                self.assertIn("catalog.refresh", path.read_text())
                self.assertEqual(path.suffix, ".cmd" if platform == "win32" else ".command")

    def test_invalid_port_and_empty_catalog(self):
        for port in (-1, 0, 65536, True, "8787"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                desktop.prepare(self.root, port)
        (self.root / ".local/catalog.json").write_text('{"models": {}, "aliases": {}}')
        with self.assertRaisesRegex(ValueError, "no chat models"):
            desktop.prepare(self.root)


if __name__ == "__main__":
    unittest.main()
