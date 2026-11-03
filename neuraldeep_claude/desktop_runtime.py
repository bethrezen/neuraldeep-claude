"""Read-only inspection of the native Desktop's pinned Code engine cache.

No download, native/Node execution, cache import, marker creation, or repair is
performed. READY means that the installed cache's native artifact marker and
its independently hashed raw payload agree with the installed app's manifest
and payload receipt. It does not reconstruct the original compressed artifact.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import struct
import sys

from . import desktop

MAX_HEADER = 16 * 1024 * 1024
MAX_JS_MEMBER = 32 * 1024 * 1024
MAX_METADATA = 16 * 1024
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
MANIFEST_JSON = re.compile(r"JSON\.parse\('(?P<body>\{\"version\":(?:\\.|[^'\\]){0,65536})'\)")


class Unverified(ValueError):
    """The local format or evidence is insufficient to assert readiness."""


def host_platform(system=None, machine=None):
    """Match native Desktop getHostPlatform(), including its Linux glibc pin."""
    system = sys.platform if system is None else system
    machine = platform.machine() if machine is None else machine
    arch = {"x86_64": "x64", "amd64": "x64", "x64": "x64",
            "arm64": "arm64", "aarch64": "arm64"}.get(machine.lower())
    prefix = {"linux": "linux", "darwin": "darwin", "win32": "win32"}.get(system)
    return f"{prefix}-{arch}" if prefix and arch else None


def _asar_path(executable):
    path = Path(executable).expanduser().resolve()
    if path.is_dir() and path.suffix.lower() == ".app":
        info = path / "Contents/Info.plist"
        try:
            name = plistlib.loads(info.read_bytes()).get("CFBundleExecutable")
        except (OSError, ValueError, plistlib.InvalidFileException) as error:
            raise Unverified("Desktop app bundle executable is unverified") from error
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise Unverified("Desktop app bundle executable name is unverified")
        path = path / "Contents/MacOS" / name
    if not path.is_file():
        raise Unverified("Native Desktop executable is missing")
    candidates = [path.parent / "resources/app.asar"]
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
        candidates.insert(0, path.parent.parent / "Resources/app.asar")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise Unverified("Native Desktop app.asar is missing at the native resource path")


def _js_members(asar):
    """Read only packaged JS members from Electron's standard ASAR container."""
    with Path(asar).open("rb") as source:
        total = os.fstat(source.fileno()).st_size
        prefix = source.read(16)
        if len(prefix) != 16:
            raise Unverified("ASAR header is truncated")
        first, header_size, string_size, json_size = struct.unpack("<IIII", prefix)
        base = 8 + header_size
        if (first != 4 or not 0 < json_size <= MAX_HEADER or header_size > MAX_HEADER + 16
                or string_size < json_size + 4 or base < 16 + json_size or base > total):
            raise Unverified("ASAR header format is unverified")
        try:
            header = json.loads(source.read(json_size))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Unverified("ASAR header JSON is invalid") from error
        candidates = []

        def walk(node, prefix=""):
            files = node.get("files") if isinstance(node, dict) else None
            if not isinstance(files, dict):
                raise Unverified("ASAR file tree is unverified")
            for name, entry in files.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    raise Unverified("ASAR file entry is unverified")
                path = prefix + name
                if "files" in entry:
                    walk(entry, path + "/")
                elif path.startswith(".vite/build/index") and path.endswith(".js") and not entry.get("unpacked") and "link" not in entry:
                    size, offset = entry.get("size"), entry.get("offset")
                    if (not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_JS_MEMBER
                            or not isinstance(offset, str) or not offset.isdigit()):
                        raise Unverified("ASAR JS member bounds are unverified")
                    location = base + int(offset)
                    if location < base or location + size > total:
                        raise Unverified("ASAR JS member exceeds its container")
                    candidates.append((size, path, location))

        walk(header)
        for size, path, offset in sorted(candidates, reverse=True):
            source.seek(offset)
            try:
                text = source.read(size).decode("utf-8")
            except UnicodeDecodeError as error:
                raise Unverified("ASAR JavaScript member is not UTF-8") from error
            yield path, text


def embedded_pin(asar, target):
    """Find the manifest JSON shape used by native Cv(), without evaluating JS."""
    pins = []
    for member, text in _js_members(asar):
        for match in MANIFEST_JSON.finditer(text):
            try:
                document = json.loads(match["body"])
            except json.JSONDecodeError:
                continue
            manifest = document.get("manifest")
            if not isinstance(manifest, dict) or "sdkWrapperVersion" not in document:
                continue
            version = document.get("version")
            platforms = manifest.get("platforms")
            if (not isinstance(version, str) or not VERSION.fullmatch(version)
                    or manifest.get("version") != version or not isinstance(platforms, dict)
                    or document.get("baseUrl") != "https://downloads.claude.ai/claude-code-releases"):
                raise Unverified("Embedded Code manifest schema is unverified")
            record = platforms.get(target)
            if not isinstance(record, dict):
                raise Unverified("Host platform is absent from the embedded Code manifest")
            expected_binary = "claude.exe.zst" if target.startswith("win32-") else "claude.zst"
            if record.get("binary") != expected_binary:
                raise Unverified("Embedded Code artifact format is unverified")
            bundled = target.startswith("darwin-") and "bundle" in record
            artifact = record.get("bundle") if bundled else record
            if not isinstance(artifact, dict) or not isinstance(artifact.get("checksum"), str) or not SHA256.fullmatch(artifact["checksum"]):
                raise Unverified("Embedded Code artifact checksum is unverified")
            pins.append({"version": version, "platform": target,
                "compressed_sha256": artifact["checksum"].lower(), "bundle": bundled,
                "binary_relative_path": "claude.app/Contents/MacOS/claude" if bundled else
                    "claude.exe" if target.startswith("win32-") else "claude",
                "asar_member": member, "manifest_parser": "native-Cv-JSON-shape-v1"})
    if not pins:
        raise Unverified("Embedded native Code manifest was not recognized")
    unique = {(row["version"], row["platform"], row["compressed_sha256"], row["bundle"]) for row in pins}
    if len(unique) != 1:
        raise Unverified("Multiple different native Code pins were found")
    return pins[0]


def _metadata(path):
    with Path(path).open("rb") as source:
        value = source.read(MAX_METADATA + 1)
    if len(value) > MAX_METADATA:
        raise Unverified("Native cache metadata exceeds the supported size")
    return value.decode("utf-8")


def inspect(root, executable=None):
    """Inspect the installed native Desktop cache; never execute or repair it."""
    result = {"status": "UNVERIFIED", "network_used": False, "native_executed": False,
        "cache_modified": False, "raw_payload_hashed": False,
        "verification_scope": "Installed native artifact marker plus raw binary SHA-256/size consistency; original compressed archive is not reconstructed."}
    try:
        target = host_platform()
        if target is None:
            raise Unverified("Current OS/architecture mapping is unverified")
        native = desktop.executable(Path(root)) if executable is None else executable
        asar = _asar_path(native)
        pin = embedded_pin(asar, target)
        result.update(pin, asar_path=str(asar))
        _, profile = desktop._primary_profiles()
        folder = profile / "claude-code" / pin["version"] / pin["compressed_sha256"][:12]
        binary = folder / pin["binary_relative_path"]
        result.update(cache_directory=str(folder), binary_path=str(binary))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            result.update(status="MISSING", reason="pinned_cache_executable_missing_or_not_executable")
            return result
        try:
            marker = _metadata(folder / ".verified").strip()
        except FileNotFoundError:
            result.update(reason="compressed_artifact_marker_missing")
            return result
        result["compressed_artifact_marker_matches"] = marker == pin["compressed_sha256"]
        if not result["compressed_artifact_marker_matches"]:
            result.update(reason="compressed_artifact_marker_mismatch")
            return result
        try:
            payload = json.loads(_metadata(folder / ".payload"))
        except FileNotFoundError:
            result.update(reason="payload_receipt_missing",
                note="Native macOS bundle installs may omit .payload; this strict preflight cannot assert raw-payload verification without it." if pin["bundle"] else "Native raw-payload receipt is absent.")
            return result
        if (not isinstance(payload, dict) or not isinstance(payload.get("sha256"), str)
                or not SHA256.fullmatch(payload["sha256"]) or not isinstance(payload.get("size"), int)
                or isinstance(payload["size"], bool) or payload["size"] < 1):
            result.update(reason="payload_receipt_invalid")
            return result
        before = binary.stat()
        result["payload_size_matches"] = before.st_size == payload["size"]
        if not result["payload_size_matches"]:
            result.update(reason="payload_size_mismatch")
            return result
        digest = hashlib.sha256()
        with binary.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        after = binary.stat()
        result["raw_payload_hashed"] = True
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            result.update(reason="payload_changed_during_inspection")
            return result
        result["payload_hash_matches"] = digest.hexdigest() == payload["sha256"].lower()
        result["payload_bytes"] = after.st_size
        if not result["payload_hash_matches"]:
            result.update(reason="payload_hash_mismatch")
            return result
        result.update(status="READY", reason="pinned_native_cache_and_raw_payload_verified")
        return result
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        result.update(status="UNVERIFIED", reason=str(error) if isinstance(error, Unverified) else type(error).__name__)
        return result
