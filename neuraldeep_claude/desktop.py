"""Prepare and activate native Claude Desktop gateway configuration.

The flat inference fields are documented by Anthropic. configLibrary and the
primary 3P store were checked against installed Desktop 4.4212.0. Packaged-app
profile isolation was not reliable at runtime, so launching requires explicit
main activation. Preparation alone creates review files and is not UI validation.
"""
from __future__ import annotations

import json
import datetime
import ntpath
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import catalog
from .config import atomic_json, clean_environment, load_env, local_token
from .effort import describe as describe_effort

PROFILE_ID = "c736e048-6130-4cdf-9dcf-439c2da25d23"
DEFAULT_MODEL = "qwen3.8-27b"
EFFORT_COMPATIBILITY_MODEL = "claude-opus-4-8"

# Native Desktop 4.4212.0 flat configuration keys, also documented in the 3P
# configuration reference. Background services are controlled by native settings.
NATIVE_SETTINGS = {
    "disableEssentialTelemetry": True,
    "disableNonessentialTelemetry": True,
    # This separate switch blocks content features (MCP App widgets, hosted
    # previews, connector icons and Linux spellcheck), not usage telemetry.
    "disableNonessentialServices": False,
    "disableAutoUpdates": False,
    "installedUpdateEnforcementEnabled": False,
    # Keep native signed-catalog refresh at its default location. Arbitrary
    # NeuralDeep model metadata still belongs to gateway discovery.
    "modelCatalogEnabled": True,
    "disableDeploymentModeChooser": True,
    "skipWebFetchPreflight": True,
}

def _launch_arguments(app_args: list[str]) -> list[str]:
    """Use the requested Electron sandbox preference and ordinary app arguments."""
    return ["--no-sandbox", *app_args]


def _existing_native_processes(native_executable: str) -> list[int]:
    """Read process identity only; never stop an existing Electron instance.

    A second invocation may forward into an existing single-instance app before
    it reloads the newly installed configuration.
    """
    if sys.platform == "win32":
        # Both the CLI and Desktop can be named claude.exe. Read only these
        # properties and compare full paths; never fetch/log command lines.
        name = ntpath.basename(native_executable).replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; "
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
            "$p=@(Get-CimInstance -ClassName Win32_Process "
            "-Property Name,ProcessId,ExecutablePath | Where-Object "
            "{$_.Name -ieq '" + name + "'}); "
            "ConvertTo-Json -InputObject @($p | Select-Object ProcessId,ExecutablePath) -Compress"
        )
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]
    elif sys.platform.startswith("linux") or sys.platform == "darwin":
        command = ["ps", "-axo", "pid=,comm="]
    else:
        raise RuntimeError("Cannot verify existing Claude Desktop processes on this platform")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True,
                                **({"encoding": "utf-8-sig"} if sys.platform == "win32" else {}))
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Cannot verify that Claude Desktop is fully closed before restart") from error
    pids = []
    if sys.platform == "win32":
        try:
            rows = json.loads(result.stdout.strip() or "[]")
        except json.JSONDecodeError as error:
            raise RuntimeError("Cannot decode Claude process executable paths") from error
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise RuntimeError("Cannot decode Claude process executable paths")
        target = ntpath.normcase(ntpath.normpath(native_executable))
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("Cannot decode Claude process executable paths")
            path, pid = row.get("ExecutablePath"), row.get("ProcessId")
            if not isinstance(path, str) or not path.strip():
                raise RuntimeError("Cannot read a matching Claude process executable path before Desktop restart")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                raise RuntimeError("Cannot decode Claude process identity")
            if ntpath.normcase(ntpath.normpath(path)) == target:
                pids.append(pid)
    else:
        names = {"claude-desktop"} if sys.platform.startswith("linux") else {"Claude"}
        names.add(Path(native_executable).name)
        for line in result.stdout.splitlines():
            fields = line.strip().split(maxsplit=1)
            if len(fields) != 2 or not fields[0].isdigit():
                continue
            name = Path(fields[1]).name
            if name in names or sys.platform == "darwin" and name.startswith("Claude Helper"):
                pids.append(int(fields[0]))
    return pids


def _launch_environment(root: Path | None = None) -> dict:
    env = clean_environment()
    # Keep update behavior independent from the telemetry settings. Discard
    # legacy launcher bundle switches even if the parent shell retained them.
    for name in ("DISABLE_AUTOUPDATER", "DISABLE_UPDATES", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
        env.pop(name, None)
    env.update(DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DO_NOT_TRACK="1")
    for name in list(env):
        if name.startswith("NEURALDEEP_API_KEY_"):
            env.pop(name)
    env.pop("CLAUDE_USER_DATA_DIR", None)
    if root is not None:
        from .helper_models import CLASSIFIER_ENV, classifier_model
        classifier = classifier_model(Path(root), opaque=True)
        if classifier:
            # Native Desktop host mode intentionally ignores this variable in
            # settings.env. Supply it to the actual spawning parent instead.
            env[CLASSIFIER_ENV] = classifier
    return env


def _claude_identity(model_id: str) -> str | None:
    """Map genuine upstream Claude versions, never pretend Qwen is Claude."""
    match = re.fullmatch(r"claude-(fable|opus|sonnet|haiku)-(\d+)(?:[.-](\d+))?", model_id)
    if match is None:
        return None
    family, major, minor = match.groups()
    return f"claude-{family}-{major}" + (f"-{minor}" if minor else "")


def _models(data: dict) -> tuple[list[dict], list[str], list[str]]:
    result = []
    non_claude = []
    arbitrary_context = []
    rows = catalog.picker(data)
    # The user explicitly selected Qwen 3.8 via subscription as the default.
    # Desktop may reject this non-Claude ID; do not silently choose wallet.
    rows.sort(key=lambda row: (
        row["model"] != "nd/" + DEFAULT_MODEL + "@subscription",
        _claude_identity(data["models"][row["model"].split("~", 1)[0]]["upstream_id"]) is None,
        data["models"][row["model"].split("~", 1)[0]]["billing"] != "subscription",
        row["model"],
    ))
    for row in rows:
        model = data["models"][row["model"].split("~", 1)[0]]
        entry = {"name": catalog.gateway_alias(row["model"]), "labelOverride": row["label"]}
        identity = _claude_identity(model["upstream_id"])
        context = model.get("input_limit", model.get("limit", {}).get("context"))
        if context:
            entry["labelOverride"] += f" · ctx {context}"
        if describe_effort(model)["adjustable"]:
            # Desktop takes the selector options from its native model catalog.
            # The opaque name still determines the real gateway route and billing.
            entry["behavesAs"] = identity or EFFORT_COMPATIBILITY_MODEL
        if not identity:
            non_claude.append(row["model"])
        if isinstance(context, int) and context >= 1_000_000:
            entry["supports1m"] = True
            entry["prefer1m"] = True
        elif context and context != 200_000:
            arbitrary_context.append(row["model"])
        result.append(entry)
    return result, non_claude, arbitrary_context


def _managed_service_servers(root: Path) -> list[dict]:
    from .services import mcp_config
    return [
        {"name": name, "transport": "stdio", "command": server["command"],
         "args": server["args"], "toolTimeoutSec": 3600}
        for name, server in mcp_config(root)["mcpServers"].items()
    ]


def prepare(root: Path, port: int = 8787, *, profile_dir: Path | None = None) -> dict:
    """Write native 3P config and return a secret-free preparation receipt."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Desktop gateway port must be an integer from 1 to 65535")
    root = Path(root).resolve()
    data = catalog.load(root)
    models, unrecognized, contexts = _models(data)
    if not models:
        raise ValueError("NeuralDeep catalog contains no chat models")
    profile = Path(profile_dir) if profile_dir is not None else root / ".local/desktop-profile"
    library = profile / "configLibrary"
    library.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        profile.chmod(0o700)
        library.chmod(0o700)
    entry_path = library / (PROFILE_ID + ".json")
    service_servers = _managed_service_servers(root)
    from .pricing import desktop_report
    pricing = desktop_report(root, data)
    inference = {
        "inferenceProvider": "gateway",
        "inferenceCredentialKind": "static",
        "inferenceGatewayBaseUrl": f"http://127.0.0.1:{port}",
        "inferenceGatewayAuthScheme": "bearer",
        "inferenceGatewayApiKey": local_token(root),
        # Gateway discovery does not import per-model effort capabilities.
        "modelDiscoveryEnabled": False,
        "inferenceModels": models,
        "modelPrefer1mContext": True,
        "inferenceModelPricingEnabled": True,
        "inferenceModelPricing": pricing["models"],
        "deploymentDisplayName": "NeuralDeep",
        "deploymentDisplaySubtitle": "Local gateway · subscription / wallet",
        "managedMcpServers": service_servers,
        "toolSearchEnabled": True,
        "builtinBrowserEnabled": True,
        "chatAdvancedFileAnalysisEnabled": True,
        "chatTabEnabled": True,
        # Restricted Desktop egress/folders would force the Code Bash sandbox
        # on again, contrary to the user's sandbox preference.
        "coworkEgressAllowedHosts": ["*"],
        **NATIVE_SETTINGS,
    }
    # Preserve unrelated preferences that the isolated profile itself has saved.
    app_config_path = profile / "claude_desktop_config.json"
    app_config = json.loads(app_config_path.read_text()) if app_config_path.exists() else {}
    if not isinstance(app_config, dict):
        raise ValueError("Desktop app configuration must be a JSON object")
    app_config["deploymentMode"] = "3p"
    preferences = app_config.setdefault("preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("Desktop preferences must be a JSON object")
    preferences.update(secureVmFeaturesEnabled=True, coworkBrowserToolsEnabled=True,
                       coworkPreferredBrowser="built_in")
    meta_path = library / "_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"entries": []}
    if not isinstance(meta, dict) or not isinstance(meta.get("entries"), list):
        raise ValueError("Desktop configLibrary metadata must contain an entries array")
    meta["entries"] = [entry for entry in meta["entries"] if entry.get("id") != PROFILE_ID]
    meta["entries"].append({"id": PROFILE_ID, "name": "NeuralDeep"})
    meta["appliedId"] = PROFILE_ID
    atomic_json(entry_path, inference, private=True)
    atomic_json(meta_path, meta, private=True)
    atomic_json(app_config_path, app_config, private=True)
    default = catalog.resolve(data, models[0]["name"])
    from .desktop_runtime import inspect as inspect_runtime
    runtime = inspect_runtime(root)
    return {
        "profile": str(profile),
        "configuration": str(entry_path),
        "base_url": inference["inferenceGatewayBaseUrl"],
        "configured_model_options": len(models),
        "model_source": "generated-neuraldeep-catalog",
        "configured_effort_options": sum("behavesAs" in model for model in models),
        "pricing": {key: value for key, value in pricing.items() if key != "models"},
        "priced_model_options": len(pricing["models"]),
        "configured_service_groups": [server["name"] for server in service_servers],
        "default_model": models[0]["name"],
        "default_provider_model": default["id"],
        "default_model_billing": default["billing"],
        "non_claude_options_require_ui_verification": unrecognized,
        "arbitrary_context_options_require_ui_verification": contexts,
        "native_design": "not-configured; user-selected-local-nd-design-skill",
        "ui_verified": False,
        "storage_layout_verified_against": "Claude Desktop 4.4212.0 Linux",
        "background_first_party_services": "native-services-enabled; telemetry-disabled",
        "network_policy": "configuration flags; NeuralDeep direct",
        "sandbox": {"code_commands": False, "electron": False, "analysis_vm": True},
        "desktop_runtime": runtime,
        "limitations": [
            "Opaque Anthropic-format route IDs avoid the native raw-name filter; labels identify the real upstream model.",
            "Native picker startup, interactive selection, and inference need separate validation.",
            "The effort compatibility profile supplies native display limits; labels show the actual provider context.",
            "Model catalog metadata uses Anthropic's signed catalog and native cache; NeuralDeep metadata lives in gateway discovery.",
            "The built-in browser retains its native site-safety checks; public browsing can also use the separate browser MCP.",
            "Advanced file analysis requires a working host VM backend and device permissions.",
            "configLibrary profile storage is version-sensitive on every operating system.",
        ],
    }


def sync_services(root: Path) -> dict:
    """Update only our active native MCP entries, preserving model selection."""
    root = Path(root).resolve()
    marker = root / ".local/desktop-activation.json"
    if not marker.exists() or json.loads(marker.read_text()).get("primary") is not True:
        return {"updated": False, "reason": "Desktop main configuration is not activated"}
    _, profile = _primary_profiles()
    target = profile / "configLibrary" / (PROFILE_ID + ".json")
    if not target.exists():
        return {"updated": False, "reason": "Active Desktop configuration file is missing"}
    data = json.loads(target.read_text())
    previous = data.get("managedMcpServers", [])
    if not isinstance(previous, list):
        raise ValueError("Desktop managedMcpServers must be an array")
    from .services import GROUPS
    owned_names = {"neuraldeep-" + group for group in GROUPS} | {"local-browser"}
    existing = {server.get("name"): server for server in previous}
    desired = _managed_service_servers(root)
    # Keep explicitly chosen native tool policies and other optional fields on
    # retained entries; update connection paths and timeouts from this install.
    ours = [existing.get(server["name"], {}) | server for server in desired]
    merged = [server for server in previous if server.get("name") not in owned_names] + ours
    if merged == previous:
        return {"updated": False, "reason": "Service configuration already current", "configuration": str(target)}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = root / ".local/backups" / ("desktop-services-" + stamp + ".json")
    atomic_json(backup, data, private=True)
    data["managedMcpServers"] = merged
    atomic_json(target, data, private=True)
    return {"updated": True, "configuration": str(target), "backup": str(backup),
            "configured_service_groups": [server["name"] for server in desired],
            "reload_required": True}


def _primary_profiles() -> tuple[Path, Path]:
    """Return regular and native 3P profiles, following Desktop's own layout."""
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
        return base / "Claude", base / "Claude-3p"
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return roaming / "Claude", local / "Claude-3p"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if not base.is_absolute():
        base = Path.home() / ".config"
    return base / "Claude", base / "Claude-3p"


def activate(root: Path, port: int = 8787) -> dict:
    """Activate ordinary Desktop startup, preserving configs with dated backups.

    Desktop owns separate native 1P/3P stores. This selects its main 3P store;
    previous Anthropic conversation history is preserved in the regular store.
    Running app processes are not stopped or restarted by this function.
    Shared proxy relay services, scripts, independent settings and other apps'
    proxy configurations are outside this installer's write/lifecycle scope.
    """
    root = Path(root).resolve()
    regular, primary = _primary_profiles()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = root / ".local/backups" / ("desktop-" + stamp)
    targets = [
        regular / "claude_desktop_config.json",
        primary / "claude_desktop_config.json",
        primary / "configLibrary/_meta.json",
        primary / "configLibrary" / (PROFILE_ID + ".json"),
    ]
    saved = []
    for index, source in enumerate(targets):
        if source.exists():
            backup.mkdir(parents=True, exist_ok=True)
            destination = backup / f"{index}-{source.name}"
            shutil.copy2(source, destination)
            if os.name != "nt":
                backup.chmod(0o700)
                destination.chmod(0o600)
            saved.append({"source": str(source), "backup": str(destination)})
    result = prepare(root, port, profile_dir=primary)
    # The current app version reads the chooser from the 3P store before it
    # relocates. Also persist the explicit selection in the previous store so
    # releases that read that location keep the user's main-provider choice.
    regular_config = regular / "claude_desktop_config.json"
    previous = json.loads(regular_config.read_text()) if regular_config.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError("Regular Desktop configuration must be a JSON object")
    previous["deploymentMode"] = "3p"
    atomic_json(regular_config, previous, private=True)
    result.update({
        "primary": True,
        "previous_profile": str(regular),
        "backups": saved,
        "restart_required": True,
        "running_sessions_interrupted": False,
    })
    result["launcher"] = install_main_launcher(root, port)
    atomic_json(root / ".local/desktop-activation.json", result, private=True)
    return result


def install_main_launcher(root: Path, port: int = 8787) -> dict:
    """Install a gateway-aware launcher, preserving known previous wrappers."""
    if sys.platform.startswith("linux"):
        target = Path.home() / ".local/bin/claude-desktop"
    elif sys.platform == "darwin":
        target = Path.home() / "Applications/Claude NeuralDeep.command"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        target = base / "NeuralDeep/bin/Claude NeuralDeep.cmd"
    else:
        return {"updated": False, "reason": "Unsupported platform for a desktop launcher"}
    if target.is_symlink():
        return {"updated": False, "reason": "Existing launcher is a symlink; preserved", "path": str(target)}
    before = target.read_text() if target.exists() else None
    marker = "NeuralDeep main Desktop launcher"
    if before is not None and "claude-proxy-relay.service" not in before and marker not in before:
        return {"updated": False, "reason": "Unrecognized existing launcher preserved", "path": str(target)}
    import shlex
    root = Path(root).resolve()
    program = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(root)!r}); "
        "from neuraldeep_claude import catalog; "
        "from neuraldeep_claude.integration import ensure_gateway; "
        "from neuraldeep_claude.desktop import launch; "
        f"root=Path({str(root)!r}); "
        f"catalog.refresh(root); ensure_gateway(root, {port!r}); "
        f"launch(root, {port!r}, app_args=sys.argv[1:])"
    )
    if sys.platform == "win32":
        invocation = subprocess.list2cmdline([sys.executable, "-c", program]).replace("%", "%%")
        text = "@echo off\nREM " + marker + "\n" + invocation + " %*\n"
    else:
        text = "#!/bin/sh\n# " + marker + "\nexec " + shlex.join([sys.executable, "-c", program]) + ' "$@"\n'
    if before == text:
        return {"updated": False, "reason": "Already current", "path": str(target)}
    backup_path = None
    if before is not None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = root / ".local/backups" / ("desktop-launcher-" + stamp)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
        if os.name != "nt":
            backup_path.chmod(0o600)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    target.chmod(0o755)
    return {"updated": True, "path": str(target), "backup": str(backup_path) if backup_path else None,
            "network_policy": "configuration flags; NeuralDeep direct",
            "starts_gateway": True}


def executable(root: Path) -> str:
    """Find the actual application executable, bypassing shell proxy wrappers."""
    custom = load_env(root).get("NEURALDEEP_CLAUDE_DESKTOP_EXECUTABLE")
    if custom:
        path = Path(custom).expanduser()
        if not path.is_file():
            raise FileNotFoundError("NEURALDEEP_CLAUDE_DESKTOP_EXECUTABLE does not exist")
        return str(path.resolve())
    if sys.platform.startswith("linux"):
        candidates = [
            Path("/usr/lib/claude-desktop/claude-desktop"),
            Path("/opt/Claude/claude-desktop"),
            Path("/opt/claude-desktop/claude-desktop"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/Applications/Claude.app/Contents/MacOS/Claude"),
            Path.home() / "Applications/Claude.app/Contents/MacOS/Claude",
        ]
    elif sys.platform == "win32":
        candidates = []
        for folder in (os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES")):
            if folder:
                base = Path(folder)
                candidates.extend(base / suffix for suffix in (
                    "AnthropicClaude/Claude.exe", "Programs/Claude/Claude.exe", "Claude/Claude.exe"))
                for pattern in ("AnthropicClaude/app-*/Claude.exe", "Claude/app-*/Claude.exe",
                                "WindowsApps/AnthropicPBC.Claude_*/app/Claude.exe"):
                    candidates.extend(sorted(base.glob(pattern), reverse=True))
        located = shutil.which("Claude.exe")
        if located:
            candidates.append(Path(located))
    else:
        candidates = []
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    raise FileNotFoundError(
        "Claude Desktop executable not found. Install the native app or set "
        "NEURALDEEP_CLAUDE_DESKTOP_EXECUTABLE in .env to its real executable."
    )


def launch(root: Path, port: int = 8787, *, app_args: list[str] | None = None) -> dict:
    """Launch the prepared profile; caller owns gateway startup/authorization."""
    marker = Path(root) / ".local/desktop-activation.json"
    primary = marker.exists() and json.loads(marker.read_text()).get("primary") is True
    if not primary:
        raise ValueError(
            "Desktop main configuration is not activated. Run scripts/nd.py "
            "install --activate first. Desktop prepare writes review files only; "
            "isolated-profile launching is not verified for the packaged app."
        )
    native = executable(Path(root))
    existing = _existing_native_processes(native)
    if existing:
        raise RuntimeError(
            "Close Claude Desktop and restart it to load the new configuration. PIDs: "
            + ", ".join(map(str, existing))
        )
    env = _launch_environment(Path(root))
    command = [native, *_launch_arguments(list(app_args or []))]
    _, profile = _primary_profiles()
    result = prepare(root, port, profile_dir=profile) | {"primary": True}
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
    return result | {"launch_requested": True, "pid": process.pid, "executable": command[0],
                     "network_policy": "configuration flags; NeuralDeep direct"}
