import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch

from neuraldeep_claude import desktop_runtime as runtime


ARTIFACT = "a" * 64
BUNDLE = "b" * 64


def manifest(target="linux-x64", *, bundle=False):
    row = {"binary": "claude.exe.zst" if target.startswith("win32-") else "claude.zst", "checksum": ARTIFACT, "size": 100}
    if bundle:
        row["bundle"] = {"checksum": BUNDLE, "size": 120}
    return {"version": "2.1.309", "manifest": {"version": "2.1.309", "platforms": {target: row}},
        "baseUrl": "https://downloads.claude.ai/claude-code-releases", "sdkWrapperVersion": "0.3.309"}


def asar(path, document):
    source = ("function Cv(){return JSON.parse('" + json.dumps(document, separators=(",", ":")) + "')}").encode()
    tree = {"files": {".vite": {"files": {"build": {"files": {"index.chunk-test.js": {"size": len(source), "offset": "0"}}}}}}}
    header = json.dumps(tree, separators=(",", ":")).encode()
    padded = header + b" " * (-len(header) % 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<IIII", 4, len(padded) + 8, len(padded) + 4, len(header)) + padded + source)


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.executable = self.root / "app/claude-desktop"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"desktop fixture")
        self.executable.chmod(0o755)
        self.asar = self.executable.parent / "resources/app.asar"
        asar(self.asar, manifest())
        self.profiles = patch.object(runtime.desktop, "_primary_profiles", return_value=(self.root / "regular", self.profile))
        self.platform = patch.object(runtime, "host_platform", return_value="linux-x64")
        self.profiles.start()
        self.platform.start()
        self.addCleanup(self.profiles.stop)
        self.addCleanup(self.platform.stop)

    def cache(self, *, bundle=False, windows=False, payload=True):
        checksum = BUNDLE if bundle else ARTIFACT
        folder = self.profile / "claude-code/2.1.309" / checksum[:12]
        binary = folder / ("claude.app/Contents/MacOS/claude" if bundle else "claude.exe" if windows else "claude")
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"genuine-test-payload")
        binary.chmod(0o755)
        (folder / ".verified").write_text(checksum)
        if payload:
            (folder / ".payload").write_text(json.dumps({"sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "size": binary.stat().st_size}))
        return folder, binary

    def inspect(self):
        return runtime.inspect(self.root, self.executable)

    def test_missing_cache_is_distinct_from_unknown_schema(self):
        result = self.inspect()
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["version"], "2.1.309")
        self.assertFalse(result["cache_modified"])
        self.assertFalse(result["network_used"])

    def test_ready_requires_marker_and_actual_raw_hash_and_size(self):
        self.cache()
        with patch("subprocess.run") as execute, patch("socket.create_connection") as network:
            result = self.inspect()
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["compressed_artifact_marker_matches"])
        self.assertTrue(result["payload_hash_matches"])
        self.assertTrue(result["raw_payload_hashed"])
        execute.assert_not_called()
        network.assert_not_called()

    def test_other_build_marker_is_unverified_without_hashing_or_repair(self):
        folder, _ = self.cache()
        (folder / ".verified").write_text("c" * 64)
        before = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
        result = self.inspect()
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["reason"], "compressed_artifact_marker_mismatch")
        self.assertFalse(result["raw_payload_hashed"])
        self.assertEqual(before, {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()})

    def test_changed_payload_with_matching_length_does_not_pass(self):
        _, binary = self.cache()
        binary.write_bytes(b"x" * binary.stat().st_size)
        result = self.inspect()
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["reason"], "payload_hash_mismatch")

    def test_size_mismatch_is_detected_before_expensive_hash(self):
        _, binary = self.cache()
        binary.write_bytes(b"short")
        result = self.inspect()
        self.assertEqual(result["reason"], "payload_size_mismatch")
        self.assertFalse(result["raw_payload_hashed"])

    def test_missing_payload_is_not_ready(self):
        self.cache(payload=False)
        result = self.inspect()
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["reason"], "payload_receipt_missing")

    @unittest.skipIf(os.name == "nt", "POSIX executable mode check")
    def test_non_executable_cache_is_missing(self):
        _, binary = self.cache()
        binary.chmod(0o644)
        self.assertEqual(self.inspect()["status"], "MISSING")

    def test_unknown_manifest_shape_is_unverified(self):
        document = manifest()
        document["manifest"]["version"] = "2.1.310"
        asar(self.asar, document)
        self.assertEqual(self.inspect()["status"], "UNVERIFIED")

    def test_truncated_asar_is_unverified(self):
        self.asar.write_bytes(b"bad")
        self.assertEqual(self.inspect()["status"], "UNVERIFIED")

    def test_native_windows_exe_name_is_used(self):
        self.platform.stop()
        with patch.object(runtime, "host_platform", return_value="win32-arm64"):
            asar(self.asar, manifest("win32-arm64"))
            self.cache(windows=True)
            result = self.inspect()
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["binary_path"].endswith("claude.exe"))

    def test_native_mac_bundle_uses_bundle_digest_and_inner_executable(self):
        self.platform.stop()
        with patch.object(runtime, "host_platform", return_value="darwin-arm64"):
            asar(self.asar, manifest("darwin-arm64", bundle=True))
            self.cache(bundle=True)
            result = self.inspect()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["compressed_sha256"], BUNDLE)
        self.assertTrue(result["binary_path"].endswith("claude.app/Contents/MacOS/claude"))

    def test_mac_native_payload_absence_is_unverified_not_missing(self):
        self.platform.stop()
        with patch.object(runtime, "host_platform", return_value="darwin-arm64"):
            asar(self.asar, manifest("darwin-arm64", bundle=True))
            self.cache(bundle=True, payload=False)
            result = self.inspect()
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIn("macOS bundle", result["note"])

    def test_mac_desktop_app_bundle_resource_path_is_read_without_execution(self):
        app = self.root / "Claude.app"
        native = app / "Contents/MacOS/Claude"
        native.parent.mkdir(parents=True)
        native.write_bytes(b"desktop fixture")
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Claude"}))
        asar(app / "Contents/Resources/app.asar", manifest())
        result = runtime.inspect(self.root, app)
        self.assertEqual(result["status"], "MISSING")
        self.assertTrue(result["asar_path"].endswith("Contents/Resources/app.asar"))


class HostPlatformTests(unittest.TestCase):
    def test_native_architecture_mapping(self):
        self.assertEqual(runtime.host_platform("linux", "x86_64"), "linux-x64")
        self.assertEqual(runtime.host_platform("win32", "AMD64"), "win32-x64")
        self.assertEqual(runtime.host_platform("win32", "ARM64"), "win32-arm64")
        self.assertEqual(runtime.host_platform("darwin", "arm64"), "darwin-arm64")
        self.assertIsNone(runtime.host_platform("linux", "riscv64"))
        self.assertIsNone(runtime.host_platform("freebsd", "amd64"))


if __name__ == "__main__":
    unittest.main()
