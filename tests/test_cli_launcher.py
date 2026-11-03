import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from neuraldeep_claude import integration, egress
from neuraldeep_claude.config import atomic_json


class CliLauncherTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder) / "project"
        root.mkdir()
        home = Path(folder) / "home"
        entry = home / ".local/bin/claude"
        entry.parent.mkdir(parents=True)
        binary = home / "versions/claude-real"
        binary.parent.mkdir()
        binary.write_bytes(b"\x7fELFnative fixture never executed")
        return root, home, entry, binary

    def symlink(self, entry, target):
        try:
            entry.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation requires OS permission")

    def test_install_preserves_stock_symlink_and_native_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            self.symlink(entry, binary)
            identity = entry.lstat().st_mtime_ns
            with patch.object(integration.Path, "home", return_value=home), patch.object(integration.shutil, "which", return_value=str(entry)):
                result = integration.install_main_cli(root, destination=entry)
                self.assertFalse(result["installed"])
                self.assertTrue(result["preserved"])
                self.assertTrue(result["nativeCliAutoUpdates"])
                self.assertEqual(integration.native_cli(root), str(binary))
                integration.install_main_cli(root, destination=entry)
            self.assertTrue(entry.is_symlink())
            self.assertEqual(entry.lstat().st_mtime_ns, identity)
            self.assertEqual(binary.read_bytes(), b"\x7fELFnative fixture never executed")
            self.assertFalse((root / ".local/backups").exists())

    @unittest.skipIf(os.name == "nt", "Windows removes its owned cmd shim instead of creating a POSIX symlink")
    def test_owned_wrapper_restores_original_relative_symlink_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            wrapper = "#!/bin/sh\n# NeuralDeep guarded Claude CLI launcher\nexit 99\n"
            entry.write_text(wrapper)
            atomic_json(root / ".local/native-cli.json", {"executable": str(binary), "launcher": str(entry)})
            relative = os.path.relpath(binary, entry.parent)
            atomic_json(root / ".local/backups/native-cli-launcher-original.json", {"path": str(entry), "type": "symlink", "target": relative})
            with patch.object(integration.Path, "home", return_value=home), patch.object(integration.shutil, "which", return_value=str(entry)):
                result = integration.install_main_cli(root)
                self.assertTrue(result["restored"])
                self.assertEqual(result["restoration_source"], "original-symlink-backup")
                self.assertFalse(integration.install_main_cli(root)["restored"])
            self.assertEqual(os.readlink(entry), relative)
            self.assertEqual(binary.read_bytes(), b"\x7fELFnative fixture never executed")
            self.assertEqual(json.loads(Path(result["removed_shim_backup"]).read_text())["contents"], wrapper)

    def test_owned_wrapper_uses_saved_native_when_original_backup_is_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            entry.write_text("#!/bin/sh\n# NeuralDeep guarded Claude CLI launcher\n")
            atomic_json(root / ".local/native-cli.json", {"executable": str(binary)})
            with patch.object(integration.shutil, "which", return_value=str(entry)):
                result = integration.install_main_cli(root, destination=entry)
            if os.name == "nt":
                self.assertEqual(result["restoration_source"], "removed-owned-windows-shim")
                self.assertFalse(entry.exists())
            else:
                self.assertEqual(result["restoration_source"], "saved-native-executable")
                self.assertEqual(entry.resolve(), binary)

    def test_unknown_custom_launcher_is_not_overwritten_or_executed(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            original = "#!/bin/sh\n# existing custom launcher\nexit 41\n"
            entry.write_text(original)
            atomic_json(root / ".local/native-cli.json", {"executable": str(binary)})
            with patch.object(integration.shutil, "which", return_value=str(entry)), patch.object(integration.subprocess, "call") as call:
                result = integration.install_main_cli(root, destination=entry)
                self.assertEqual(integration.native_cli(root), str(binary))
            call.assert_not_called()
            self.assertFalse(result["restored"])
            self.assertEqual(entry.read_text(), original)

    def test_resolver_follows_stock_update_instead_of_pinning_saved_version(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, old = self.fixture(td)
            current = old.with_name("claude-new")
            current.write_bytes(b"\x7fELFnew stock version")
            self.symlink(entry, current)
            atomic_json(root / ".local/native-cli.json", {"executable": str(old)})
            with patch.object(integration.shutil, "which", return_value=str(entry)):
                self.assertEqual(integration.native_cli(root), str(current))
                old.unlink()
                self.assertEqual(integration.native_cli(root), str(current))

    def test_resolver_accepts_official_npm_windows_shim(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            shim = entry.with_suffix(".cmd")
            shim.write_text('@echo off\nnode "%~dp0%\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*\n')
            with patch.object(integration.shutil, "which", return_value=str(shim)):
                self.assertEqual(integration.native_cli(root), str(shim.resolve()))

    def test_no_missing_native_replacement_or_recursive_wrapper_is_created(self):
        with tempfile.TemporaryDirectory() as td:
            root, home, entry, binary = self.fixture(td)
            with patch.object(integration.shutil, "which", return_value=str(binary)):
                self.assertFalse(integration.install_main_cli(root, destination=entry)["installed"])
            self.assertFalse(entry.exists())
            original = "#!/bin/sh\n# NeuralDeep guarded Claude CLI launcher\n"
            entry.write_text(original)
            atomic_json(root / ".local/native-cli.json", {"executable": str(entry)})
            with patch.object(integration.shutil, "which", return_value=str(entry)), self.assertRaises(RuntimeError):
                integration.install_main_cli(root, destination=entry)
            self.assertEqual(entry.read_text(), original)

    def test_native_compatibility_command_preserves_args_and_ambient_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            args = ["--settings", "user.json", "--model=custom", "--", "prompt"]
            with patch.object(integration.catalog, "refresh"), patch.object(integration, "activate"), patch.object(integration, "ensure_gateway"), patch.object(integration, "native_cli", return_value="original-cli"), patch.object(integration.subprocess, "call", return_value=7) as call, patch.object(egress, "guard_environment", side_effect=AssertionError("No guard expected")), patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:20171", "PARENT_SECRET": "ambient-only"}):
                before = dict(os.environ)
                self.assertEqual(integration.launch_native(root, args), 7)
                self.assertEqual(call.call_args.args[0], ["original-cli", *args])
                self.assertEqual(call.call_args.kwargs["env"], before)
                self.assertEqual(dict(os.environ), before)
            self.assertFalse((root / ".local/launch-settings").exists())

    def test_separate_launcher_uses_settings_flags_without_a_network_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            atomic_json(path, {"env": {**integration.OFFLINE_ENV, "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787", "ANTHROPIC_API_KEY": "local-fixture"}})
            with patch.object(integration, "prepare", return_value=path), patch.object(integration, "ensure_gateway"), patch.object(integration, "native_cli", return_value="original-cli"), patch.object(integration.subprocess, "call", return_value=0) as call, patch.object(egress, "guard_environment", side_effect=AssertionError("No guard expected")), patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:20171"}):
                self.assertEqual(integration.launch(root, ["-p", "hello"], refresh_models=False), 0)
            child = call.call_args.kwargs["env"]
            self.assertEqual(call.call_args.args[0][-2:], ["-p", "hello"])
            self.assertEqual(child["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787")
            self.assertNotIn("HTTP_PROXY", child)
            self.assertNotIn("DISABLE_AUTOUPDATER", child)
            self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", child)
            self.assertNotIn("CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", child)

    def test_granular_flags_keep_stock_updates_available(self):
        for name in ("DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "DISABLE_GROWTHBOOK", "DO_NOT_TRACK"):
            self.assertEqual(integration.OFFLINE_ENV[name], "1")
        self.assertNotIn("DISABLE_AUTOUPDATER", integration.OFFLINE_ENV)
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", integration.OFFLINE_ENV)


if __name__ == "__main__":
    unittest.main()
