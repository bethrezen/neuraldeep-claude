"""Generate Claude settings and launch with direct-network, local credentials."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import datetime
from pathlib import Path
from urllib.parse import urlparse
from . import catalog
from .config import atomic_json, clean_environment, local_token, source_revision

DEFAULT_MODEL = "qwen3.8-27b"
NATIVE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
NATIVE_CLI_POLICY = {"nativeCliLauncher": "preserve", "nativeCliAutoUpdates": True,
                     "nativeCliAnthropicServices": "allowed", "nativeCliInference": "neuraldeep"}
_LAUNCHER_MARKER = b"NeuralDeep guarded Claude CLI launcher"

OFFLINE_ENV = {
    # Granular service flags only. The original CLI keeps its stock updater;
    # no HTTP filter, process proxy or broad nonessential-traffic gate is used.
    "DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_GROWTHBOOK": "1",
    "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
    "CLAUDE_CODE_MODEL_CATALOG": "0",
}
_REMOVED_CLI_BANS = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER"}

def active_port(root: Path, default=8787) -> int:
    for filename in ("activation.json", "desktop-activation.json"):
        path = root / ".local" / filename
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("port") or urlparse(data.get("base_url", "")).port
            if value:
                return int(value)
    return default

def build_settings(root: Path, model_id=DEFAULT_MODEL, port=8787) -> dict:
    cat = catalog.load(root)
    model = catalog.resolve(cat, model_id)
    rows = catalog.picker(cat)
    context = model.get("input_limit", model.get("limit", {}).get("context"))
    if not context:
        raise ValueError("No effective context published for this model. Add an evidenced override.")
    per_model = {}
    for row in rows:
        m = catalog.resolve(cat, row["model"])
        ctx = m.get("input_limit", m.get("limit", {}).get("context"))
        if m.get("input_limit") and ctx < 100000:
            # Native settings accept 100k as the smallest window and subtract
            # their own output/compaction reserves from it.
            ctx = 100000
        if ctx and 100000 <= ctx <= 1000000:
            # Old sessions can retain their effort-specific route ID. Preserve
            # context metadata for those IDs without showing duplicate options.
            for route in [row["model"], *(row["model"] + "~" + effort for effort in m.get("efforts", []))]:
                per_model[route] = {"autoCompactWindow": ctx}
                per_model[catalog.gateway_alias(route)] = {"autoCompactWindow": ctx}
                per_model[catalog.gateway_alias(route) + "[1m]"] = {"autoCompactWindow": ctx}
    settings = {
        "env": {
            **OFFLINE_ENV,
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
            "ANTHROPIC_API_KEY": local_token(root),
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model["id"],
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model["id"],
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model["id"],
            "ANTHROPIC_DEFAULT_FABLE_MODEL": model["id"],
            "CLAUDE_CODE_SUBAGENT_MODEL": model["id"],
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(context),
            # The stock 2.1.316 client clamps this setting at 128k. The gateway
            # also respects the actual selected provider model's published cap.
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(min(int(model.get("limit", {}).get("output") or 128000), 128000)),
            "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
            "CLAUDE_CODE_WORKFLOWS": "1",
            "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS": "256",
            "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT": "1",
            "ENABLE_TOOL_SEARCH": "force",
        },
        "model": model["id"],
        "modelPicker": {"replaceBuiltInOptions": True, "options": rows},
        "modelSettings": per_model,
        "alwaysThinkingEnabled": True,
        "effortLevel": model.get("selected_effort") if model.get("selected_effort") in NATIVE_EFFORTS else "max",
        "teammateMode": "in-process",
        "enableWorkflows": True,
        "disableWorkflows": False,
        "workflowSizeGuideline": "unrestricted",
        "workflowKeywordTriggerEnabled": True,
        "sandbox": {"enabled": False, "allowUnsandboxedCommands": True},
    }
    # Normal settings route inference to NeuralDeep. They do not replace the
    # native executable or introduce a separate authentication/host mode.
    settings["env"].update({key: "" for key in (
        "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_UNIX_SOCKET")})
    settings["env"].update({key: "0" for key in (
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD", "CLAUDE_CODE_USE_GATEWAY")})
    from .helper_models import CLASSIFIER_ENV, classifier_model
    classifier = classifier_model(root)
    if classifier is not None:
        settings["env"][CLASSIFIER_ENV] = classifier
    return settings

def prepare(root: Path, model_id=DEFAULT_MODEL, port=8787, include_project=True) -> Path:
    from .services import mcp_config
    settings = build_settings(root, model_id, port)
    # Preserve user's skills, plugins, UI preferences. A sanitized snapshot also
    # removes proxy variables saved in their settings (not just parent env).
    original_path = Path.home() / ".claude/settings.json"
    original = json.loads(original_path.read_text(encoding="utf-8")) if original_path.exists() else {}
    # Include project/local preferences in the sanitized snapshot, then load no
    # unsanitized settings source. Managed policies remain enforced by Claude.
    for folder in ([*reversed(Path.cwd().parents), Path.cwd()] if include_project else []):
        for filename in ("settings.json", "settings.local.json"):
            path = folder / ".claude" / filename
            if path.exists() and path != original_path:
                source = json.loads(path.read_text(encoding="utf-8"))
                original["env"] = original.get("env", {}) | source.get("env", {})
                if "modelSettings" in source:
                    original["modelSettings"] = _merge_model_settings(
                        original.get("modelSettings", {}), source["modelSettings"])
                original.update({k: v for k, v in source.items() if k not in ("env", "modelSettings")})
    original_env = {k: v for k, v in clean_environment(original.get("env", {})).items() if k not in (
        "CLAUDE_CODE_DISABLE_AUTO_COMPACT", "DISABLE_AUTO_COMPACT", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")}
    original_env = {key: value for key, value in original_env.items() if key.upper() not in _REMOVED_CLI_BANS}
    # This explicit helper configuration owns its one variable. Setting it to
    # null must also remove a value installed by an earlier activation.
    if (root / "config/helper-models.json").exists():
        from .helper_models import CLASSIFIER_ENV
        original_env.pop(CLASSIFIER_ENV, None)
    # Keep the native /effort preference across catalog updates. A deliberately
    # selected legacy model~effort is migrated to the base model + this setting.
    selected = catalog.resolve(catalog.load(root), model_id)
    if not selected.get("selected_effort") and original.get("effortLevel") in NATIVE_EFFORTS:
        settings["effortLevel"] = original["effortLevel"]
    # Native /effort persists under modelSettings.<id>.effortLevel. Regenerate
    # only our context property; keep the user's effort and unrelated per-model
    # preferences for raw, opaque, legacy and external model IDs. We do not
    # synthesize a persisted max, which the native selector treats as session-only.
    settings["modelSettings"] = _merge_model_settings(
        original.get("modelSettings", {}), settings["modelSettings"])
    original.update({k: v for k, v in settings.items() if k != "env"})
    original["env"] = original_env | settings["env"]
    path = root / ".local/claude-settings.json"
    atomic_json(path, original, private=True)
    atomic_json(root / ".local/mcp.json", mcp_config(root), private=True)
    return path


def _merge_model_settings(existing: dict, incoming: dict) -> dict:
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        raise ValueError("Claude modelSettings must be a JSON object")
    merged = dict(existing)
    for model, values in incoming.items():
        previous = merged.get(model, {})
        merged[model] = previous | values if isinstance(previous, dict) and isinstance(values, dict) else values
    return merged

def ensure_gateway(root: Path, port=8787):
    from .transport import request
    base = f"http://127.0.0.1:{port}"
    def healthy():
        try:
            result = request("GET", "/v1/models", local_token(root), base=base, timeout=1)
            return "data" in result
        except Exception:
            return False
    if healthy():
        health = request("GET", "/health", base=base, timeout=2)
        if health.get("revision") and health["revision"] != source_revision():
            raise RuntimeError("Gateway code has changed. Run: python scripts/nd.py restart")
        return
    log_path = root / ".local/gateway.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = clean_environment()
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    with log_path.open("ab") as log:
        process = subprocess.Popen([sys.executable, str(root / "scripts/nd.py"), "--root", str(root), "gateway", "--port", str(port)], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
    for _ in range(60):
        if healthy():
            atomic_json(root / ".local/gateway-process.json", {"pid": process.pid, "port": port})
            return
        if process.poll() is not None:
            raise RuntimeError("Gateway did not start. Inspect .local/gateway.log (port may be occupied).")
        time.sleep(0.1)
    raise RuntimeError("Gateway start timed out; inspect .local/gateway.log")

def restart_gateway(root: Path, port=8787):
    from .transport import request
    base = f"http://127.0.0.1:{port}"
    request("POST", "/_neuraldeep/shutdown", local_token(root), {}, base=base, timeout=5)
    for _ in range(60):
        try:
            request("GET", "/health", base=base, timeout=0.2)
        except Exception:
            ensure_gateway(root, port)
            return
        time.sleep(0.1)
    raise RuntimeError("Gateway did not stop")

def launch(root: Path, args: list[str], model_id=DEFAULT_MODEL, port=8787, refresh_models=True) -> int:
    if refresh_models:
        # Fail closed on refresh failure instead of silently pretending a stale
        # catalog is current. Offline launching can opt in with --cached.
        catalog.refresh(root)
    settings_path = prepare(root, model_id, port)
    ensure_gateway(root, port)
    env = clean_environment()
    env.update(json.loads(settings_path.read_text())["env"])
    executable = native_cli(root)
    cmd = [executable, "--settings", str(settings_path), "--mcp-config", str(root / ".local/mcp.json")]
    # User scope is required for user skills/plugins in current Claude. The
    # explicit sanitized snapshot has higher precedence; project/local settings
    # were incorporated above without loading their original proxy entries.
    cmd += ["--setting-sources", "user"]
    cmd += args
    return subprocess.call(cmd, env=env)

def _launcher_prefix(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(8192)
    except OSError:
        return b""


def _native_executable(path: Path) -> Path | None:
    """Recognize native builds or the official npm entry without running it."""
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    prefix = _launcher_prefix(resolved)
    if _LAUNCHER_MARKER in prefix:
        return None
    magic = prefix[:4]
    if (magic == b"\x7fELF" or prefix[:2] == b"MZ" or magic in (
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca")):
        return resolved
    # npm installs a direct JS entry on POSIX and a small shim on Windows.
    # Unknown user shell wrappers are preserved but never treated as our native
    # inference executable merely because they happen to be first in PATH.
    normalized = str(resolved).replace("\\", "/").lower()
    source = prefix.replace(b"\\", b"/")
    package_path = b"@anthropic-ai/claude-code/"
    if (("/@anthropic-ai/claude-code/" in normalized and prefix.startswith(b"#!"))
            or package_path in source and (b"node" in source or resolved.suffix.lower() == ".cmd")):
        return resolved
    return None


def native_cli(root: Path) -> str:
    """Prefer the installed stock entry, so its updater can advance versions."""
    located = shutil.which("claude")
    if located:
        current = _native_executable(Path(located))
        if current is not None:
            return str(current)
    record = root / ".local/native-cli.json"
    if record.exists():
        try:
            saved = json.loads(record.read_text(encoding="utf-8"))
            value = saved.get("executable") if isinstance(saved, dict) else None
            current = _native_executable(Path(value)) if isinstance(value, str) else None
        except (OSError, ValueError):
            current = None
        if current is not None:
            return str(current)
    raise RuntimeError("Cannot locate the original Claude CLI executable. Install the official CLI; existing custom launchers were preserved.")


def _main_cli_entry(root: Path, destination: Path | None) -> Path:
    if destination is not None:
        return Path(destination)
    record = root / ".local/native-cli.json"
    try:
        value = json.loads(record.read_text(encoding="utf-8")).get("launcher")
        if isinstance(value, str) and _LAUNCHER_MARKER in _launcher_prefix(Path(value)):
            return Path(value)
    except (OSError, ValueError, AttributeError):
        pass
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NeuralDeep/bin/claude.cmd"
    return Path.home() / ".local/bin/claude"


def _original_cli_symlink(root: Path, target: Path) -> tuple[str, Path] | None:
    for path in sorted((root / ".local/backups").glob("native-cli-launcher-*.json"), reverse=True):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if (saved.get("path") != str(target) or saved.get("type") != "symlink"
                    or not isinstance(saved.get("target"), str) or not saved["target"]):
                continue
            link = saved["target"]
            candidate = Path(link) if Path(link).is_absolute() else target.parent / link
            native = _native_executable(candidate)
            if native is not None:
                return link, native
        except (OSError, ValueError, AttributeError):
            continue
    return None


def install_main_cli(root: Path, destination: Path | None = None) -> dict:
    """Preserve stock CLI identity; only undo a launcher owned by this project."""
    target = _main_cli_entry(root, destination)
    owned = target.is_file() and not target.is_symlink() and _LAUNCHER_MARKER in _launcher_prefix(target)
    try:
        real = native_cli(root)
    except RuntimeError:
        if owned:
            raise
        real = None
    receipt = {"installed": False, "preserved": True, "restored": False,
               "path": str(target), "native_executable": real, **NATIVE_CLI_POLICY}
    if not owned:
        receipt["reason"] = "Original or custom CLI entry preserved; no replacement launcher is installed"
        return receipt
    original = target.read_bytes()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / ".local/backups" / ("removed-neuraldeep-cli-shim-" + stamp + ".json")
    atomic_json(backup, {"path": str(target), "contents": original.decode("utf-8")}, private=True)
    # Recheck our exact owned file before replacing it. Never write through the
    # former symlink or alter the original executable's bytes or permissions.
    if target.is_symlink() or target.read_bytes() != original:
        receipt["reason"] = "CLI entry changed during restoration; current entry preserved"
        return receipt
    if os.name == "nt":
        # Our Windows .cmd lived in NeuralDeep/bin and shadowed the stock entry.
        # Removing only this owned shim exposes the untouched original exe/cmd.
        target.unlink()
        source = "removed-owned-windows-shim"
    else:
        restored = _original_cli_symlink(root, target)
        link, native = restored if restored is not None else (real, Path(real))
        with tempfile.TemporaryDirectory(prefix=".neuraldeep-restore-", dir=target.parent) as temporary:
            replacement = Path(temporary) / "claude"
            replacement.symlink_to(link)
            os.replace(replacement, target)
        real = str(native)
        source = "original-symlink-backup" if restored is not None else "saved-native-executable"
    atomic_json(root / ".local/native-cli.json", {"executable": real, "launcher": str(target),
                "nativeCliLauncher": "preserve"}, private=True)
    receipt.update(restored=True, native_executable=real, restoration_source=source,
                   removed_shim_backup=str(backup), reason="Owned NeuralDeep shim removed; original Claude CLI restored")
    return receipt


def launch_native(root: Path, args: list[str], port=8787) -> int:
    """Compatibility command for the original CLI with normal main settings."""
    catalog.refresh(root)
    activate(root, port)
    ensure_gateway(root, port)
    # Preserve the original command's arguments, update/service behavior and
    # ambient networking. Main settings route inference to the direct ND hub.
    return subprocess.call([native_cli(root), *args], env=dict(os.environ))

def install(root: Path, destination: Path | None = None):
    """Install a tiny launcher; data/config stays in this portable directory."""
    if destination is None:
        destination = Path.home() / ".local/bin" if os.name != "nt" else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NeuralDeep/bin"
    destination.mkdir(parents=True, exist_ok=True)
    script = root / "scripts/nd.py"
    if os.name == "nt":
        path = destination / "claude-neuraldeep.cmd"
        path.write_text(f'@echo off\n"{sys.executable}" "{script}" --root "{root}" launch %*\n', encoding="utf-8")
    else:
        import shlex
        path = destination / "claude-neuraldeep"
        path.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, str(script), "--root", str(root), "launch"]) + ' "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path

def activate(root: Path, port=8787) -> dict:
    """User-authorized main Claude configuration, with a reversible backup."""
    import shlex
    path = Path.home() / ".claude/settings.json"
    selected = DEFAULT_MODEL
    if (root / ".local/activation.json").exists() and path.exists():
        previous_model = json.loads(path.read_text(encoding="utf-8")).get("model", "")
        try:
            catalog.resolve(catalog.load(root), previous_model)
            selected = previous_model
        except catalog.RetiredModelError:
            # A user-retired ID must be replaced deliberately; silently choosing
            # Qwen here would hide a stale settings problem from the user.
            raise
        except ValueError:
            pass
    source = prepare(root, selected, port=port, include_project=False)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / ".local/backups" / ("claude-settings-" + stamp + ".json")
    if path.exists():
        atomic_json(backup, json.loads(path.read_text(encoding="utf-8")), private=True)
    settings = json.loads(source.read_text(encoding="utf-8"))
    hook_argv = [sys.executable, str(root / "scripts/nd.py"), "--root", str(root), "start", "--port", str(port)]
    hook_command = subprocess.list2cmdline(hook_argv) if os.name == "nt" else shlex.join(hook_argv)
    hooks = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    # Idempotent replacement of only our startup entry.
    hooks[:] = [entry for entry in hooks if not any(str(root / "scripts/nd.py") in h.get("command", "") for h in entry.get("hooks", []))]
    hooks.append({"hooks": [{"type": "command", "command": hook_command, "timeout": 15}]})
    atomic_json(path, settings, private=True)
    # Explicit main MCP installation, keeping other user MCP servers intact.
    global_mcp = Path.home() / ".claude.json"
    existing = json.loads(global_mcp.read_text(encoding="utf-8")) if global_mcp.exists() else {}
    if global_mcp.exists():
        atomic_json(root / ".local/backups" / ("claude-global-" + stamp + ".json"), existing, private=True)
    existing["autoUpdates"] = True
    from .services import mcp_config
    servers = existing.setdefault("mcpServers", {})
    for name in list(servers):
        if name.startswith("neuraldeep-") or name == "local-browser":
            del servers[name]
    servers.update(mcp_config(root)["mcpServers"])
    atomic_json(global_mcp, existing, private=True)
    receipt = {"settings": str(path), "settings_backup": str(backup), "mcp_config": str(global_mcp), "activated_at": stamp, "port": port, "native_cli_policy": dict(NATIVE_CLI_POLICY)}
    atomic_json(root / ".local/activation.json", receipt, private=True)
    from .skills import install_skills
    receipt["skills"] = install_skills(root)
    receipt["cli_launcher"] = install_main_cli(root)
    atomic_json(root / ".local/activation.json", receipt, private=True)
    return receipt

def sync_mcp(root: Path):
    """Update only our main MCP entries after service toggles."""
    if not (root / ".local/activation.json").exists():
        return
    from .services import mcp_config
    path = Path.home() / ".claude.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    servers = data.setdefault("mcpServers", {})
    for name in list(servers):
        if name.startswith("neuraldeep-") or name == "local-browser":
            del servers[name]
    servers.update(mcp_config(root)["mcpServers"])
    atomic_json(path, data, private=True)
