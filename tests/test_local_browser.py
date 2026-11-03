import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from neuraldeep_claude import local_browser


class PortableBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fake_installed(self):
        paths = local_browser._paths(self.root)
        paths["package"].parent.mkdir(parents=True)
        paths["package"].write_text(json.dumps({"version": local_browser.MCP_VERSION}))
        paths["entry"].touch()
        (paths["browsers"] / "chromium-1234").mkdir(parents=True)
        paths["config"].write_text("{}")
        return paths

    def test_mcp_entry_is_absolute_and_independent_of_client_working_directory(self):
        command = local_browser.mcp_command(self.root, python="portable-python")
        self.assertEqual(command["command"], "portable-python")
        self.assertTrue(Path(command["args"][0]).is_absolute())
        self.assertEqual(command["args"][1:], ["--root", str(self.root), "launch"])
        self.assertNotIn("npx", command["args"])
        self.assertNotIn("latest", " ".join(command["args"]))

    def test_browser_does_not_inherit_profiles_extension_proxy_overrides_or_hub_credentials(self):
        ambient = {"PATH": "/usr/bin", "HTTP_PROXY": "http://shared-relay:20171", "https_proxy": "bad",
                   "PLAYWRIGHT_MCP_EXTENSION": "1", "PLAYWRIGHT_MCP_USER_DATA_DIR": "/existing-profile",
                   "PLAYWRIGHT_DOWNLOAD_HOST": "https://unwanted-mirror", "NODE_OPTIONS": "--require unwanted.js",
                   "NEURALDEEP_API_KEY_SUBSCRIPTION": "private-key", "NEURALDEEP_DRIFT_TOKEN": "private-drift"}
        with patch.dict(os.environ, ambient, clear=True):
            result = local_browser._environment(self.root)
            self.assertEqual(os.environ, ambient)
        for forbidden in ("HTTP_PROXY", "https_proxy", "PLAYWRIGHT_MCP_EXTENSION", "PLAYWRIGHT_MCP_USER_DATA_DIR",
                          "PLAYWRIGHT_DOWNLOAD_HOST", "NODE_OPTIONS", "NEURALDEEP_API_KEY_SUBSCRIPTION", "NEURALDEEP_DRIFT_TOKEN"):
            self.assertNotIn(forbidden, result)
        self.assertEqual(result["PLAYWRIGHT_BROWSERS_PATH"], str(self.root / ".local/browser-runtime/browsers"))
        self.assertEqual(result["npm_config_registry"], "https://registry.npmjs.org/")
        self.assertTrue(result["npm_config_userconfig"].startswith(str(self.root)))
        self.assertTrue(result["npm_config_globalconfig"].startswith(str(self.root)))

    def test_status_reports_missing_version_and_owned_browser_separately(self):
        self.assertFalse(local_browser.status(self.root)["installed"])
        paths = self.fake_installed()
        self.assertTrue(local_browser.status(self.root)["installed"])
        paths["package"].write_text('{"version":"0.0.1"}')
        self.assertEqual(local_browser.status(self.root)["reason"], "package-version-mismatch")
        paths["package"].write_text(json.dumps({"version": local_browser.MCP_VERSION}))
        (paths["browsers"] / "chromium-1234").rmdir()
        self.assertEqual(local_browser.status(self.root)["reason"], "owned-chromium-not-installed")

    def test_launch_removes_old_proxy_config_and_uses_clean_env_headless_isolated_no_sandbox(self):
        paths = self.fake_installed()
        paths["config"].write_text('{"browser":{"userDataDir":"existing","launchOptions":{"proxy":{"server":"bad"}}}}')
        clean_env = {"PATH": "/usr/bin"}
        with patch.object(local_browser, "_node", return_value="node"), \
             patch.object(local_browser, "_environment", return_value=clean_env) as environment, \
             patch.object(local_browser.subprocess, "Popen") as process:
            process.return_value.poll.return_value = 0
            process.return_value.returncode = 0
            self.assertEqual(local_browser.launch(self.root), 0)
        environment.assert_called_once_with(self.root)
        command = process.call_args.args[0]
        self.assertIn("--headless", command)
        self.assertIn("--isolated", command)
        self.assertIn("--no-sandbox", command)
        self.assertEqual(command[-2:], ["--idle-timeout", "0"])
        self.assertIs(process.call_args.kwargs["env"], clean_env)
        config = json.loads(paths["config"].read_text())
        browser = config["browser"]
        self.assertNotIn("userDataDir", browser)
        self.assertNotIn("extension", config)
        self.assertTrue(browser["isolated"])
        self.assertFalse(browser["launchOptions"]["chromiumSandbox"])
        self.assertTrue(browser["launchOptions"]["headless"])
        self.assertNotIn("proxy", browser["launchOptions"])
        self.assertNotIn("args", browser["launchOptions"])
        self.assertNotIn("18790", json.dumps(config))
        self.assertEqual(set(config["capabilities"]), {"network", "storage", "testing", "vision", "pdf", "devtools", "config"})
        self.assertTrue(config["allowUnrestrictedFileAccess"])

    def test_disabled_service_refuses_new_launch_and_stops_only_its_owned_child(self):
        self.fake_installed()
        with patch("neuraldeep_claude.services.service_state", return_value={"browser": False}), \
             patch.object(local_browser.subprocess, "Popen") as process:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                local_browser.launch(self.root)
            process.assert_not_called()
        with patch("neuraldeep_claude.services.service_state", side_effect=[{"browser": True}, {"browser": False}]), \
             patch.object(local_browser, "_node", return_value="node"), \
             patch.object(local_browser, "_environment", return_value={}), \
             patch.object(local_browser.subprocess, "Popen") as process:
            process.return_value.poll.side_effect = [None, 0]
            self.assertEqual(local_browser.launch(self.root), 0)
            process.return_value.terminate.assert_called_once()
            process.return_value.wait.assert_called_once_with(timeout=5)

    def test_install_pins_package_and_downloads_browser_without_system_dependency_install(self):
        commands = []
        def run(command, root, **kwargs):
            commands.append(command)
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "v24.1.0")
            if "--ignore-scripts" in command:
                self.fake_installed()
            return subprocess.CompletedProcess(command, 0, "ok")
        with patch.object(local_browser, "_node", return_value="node"), \
             patch.object(local_browser, "_npm_cli", return_value=Path("npm-cli.js")), \
             patch.object(local_browser, "_run", side_effect=run):
            receipt = local_browser.install(self.root)
        package = json.loads((self.root / ".local/browser-runtime/package.json").read_text())
        self.assertEqual(package["dependencies"], {"@playwright/mcp": local_browser.MCP_VERSION})
        self.assertFalse(receipt["system_install"])
        self.assertFalse(receipt["existing_browser_profile_used"])
        self.assertTrue(receipt["ambient_proxy_env_removed"])
        self.assertFalse(receipt["dedicated_network_filter"])
        self.assertEqual(commands[-1][-2:], ["install", "chromium"])
        self.assertFalse(any("--with-deps" in command or "install-deps" in command for command in commands))
        self.assertTrue((self.root / ".local/browser-runtime/installation.json").is_file())

    def test_windows_npm_cmd_uses_node_js_entry_without_a_shell(self):
        folder = self.root / "node distribution"
        folder.mkdir()
        node, npm = folder / "node.exe", folder / "npm.cmd"
        node.touch()
        npm.touch()
        cli = folder / "node_modules/npm/bin/npm-cli.js"
        cli.parent.mkdir(parents=True)
        cli.touch()
        with patch.object(local_browser.shutil, "which", return_value=str(npm)):
            self.assertEqual(local_browser._npm_cli(str(node)), cli)


if __name__ == "__main__":
    unittest.main()
