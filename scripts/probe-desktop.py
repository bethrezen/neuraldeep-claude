#!/usr/bin/env python3
"""Dry-run-first, bounded native Desktop picker/UI smoke on Linux.

The installed application runs only after a new network namespace is verified.
Copies of its native profiles are bound over their original paths inside that
namespace. Only the existing local gateway and private Claude egress guard are
bridged; user Desktop instances, the shared relay, and live profiles are never
stopped or edited. Screenshots are evidence, not automatic claims of UI success.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from neuraldeep_claude import desktop, egress
from neuraldeep_claude.config import clean_environment

_spec = importlib.util.spec_from_file_location("nd_offline_probe", ROOT / "scripts/probe-offline.py")
offline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offline)


def plan(root=ROOT):
    return {"execute": False, "execution_platform": "linux only",
        "native_execution": "verified bwrap network/PID namespaces; copied native profiles",
        "bridge_ports": sorted(offline.ALLOWED_PORTS),
        "scope": "native startup, picker catalog and screenshots; no user prompt or VM start requested; native one-token subscription credential probe may run",
        "root": str(root), "message": "Dry run. Add --execute for the bounded native Desktop smoke."}


def configuration_summary(config, app, cli):
    sandbox = cli.get("sandbox", {})
    prices = config.get("inferenceModelPricing", [])
    models = config.get("inferenceModels", [])
    return {"discovery_enabled": config.get("modelDiscoveryEnabled") is True,
        "manual_model_list_absent": "inferenceModels" not in config,
        "picker_source": "inferenceModels" if models else "discovery",
        "prefer_1m": config.get("modelPrefer1mContext") is True,
        "pricing_enabled": config.get("inferenceModelPricingEnabled") is True,
        "pricing_rows": len(prices),
        "pricing_complete": all(all(key in row and isinstance(row[key], (int, float))
            and not isinstance(row[key], bool) and 0 <= row[key] <= 10000
            for key in ("inputPerMtok", "outputPerMtok", "cacheReadPerMtok", "cacheWritePerMtok")) for row in prices),
        "catalog_enabled": config.get("modelCatalogEnabled") is True,
        "catalog_no_fetch_sentinel": config.get("modelCatalogUrl") == "https://model-catalog.invalid/unreadable",
        "tool_search_enabled": config.get("toolSearchEnabled") is True,
        "browser_enabled": config.get("builtinBrowserEnabled") is True,
        "advanced_analysis_enabled": config.get("chatAdvancedFileAnalysisEnabled") is True,
        "chat_enabled": config.get("chatTabEnabled") is True,
        "analysis_vm_preference_preserved": app.get("preferences", {}).get("secureVmFeaturesEnabled") is True,
        "code_sandbox_disabled": sandbox.get("enabled") is False,
        "code_strict_sandbox_disabled": sandbox.get("allowUnsandboxedCommands") is True,
        "egress_does_not_force_sandbox": config.get("coworkEgressAllowedHosts") == ["*"],
        "folders_do_not_force_sandbox": "allowedWorkspaceFolders" not in config,
        "managed_mcp_groups": len(config.get("managedMcpServers", []))}


def discovery_summary(document):
    rows = document.get("data", [])
    return {"rows": len(rows), "supports_1m_rows": sum(row.get("supports_1m") is True for row in rows),
        "opaque_id_rows": sum(bool(re.fullmatch(r"anthropic/neuraldeep/\d+", row.get("id", ""))) for row in rows),
        "unique_ids": len({row.get("id") for row in rows}),
        "wallet_rows": sum("КОШЕЛ" in row.get("display_name", "").upper() for row in rows)}


def native_log_evidence(text, expected, source="discovery"):
    matches = re.findall(r"Model discovery: (.*?); picker = (\d+) \(([^)]+)\)", text)
    return {"discovery_runs": [{"detail": detail, "picker_count": int(count), "source": source}
            for detail, count, source in matches],
        "native_discovery_count_matches": any(int(count) == expected and source == "discovery" for _, count, source in matches),
        "native_picker_count_matches": any(int(count) == expected and actual_source == source
            for _, count, actual_source in matches),
        "third_party_gateway_logged": "3P mode active { provider: 'gateway' }" in text,
        "native_config_rejected": any(word in text for word in ("config_model_rejected", "Config validation failed", "inferenceModels rejected")),
        "bundled_catalog_logged": "model-catalog: resolved" in text and "source: 'seed'" in text,
        "catalog_no_fetch_location_logged": "location_invalid" in text,
        "native_cli_download_attempted": "[CCD] Downloading from" in text,
        "native_cli_download_failed": "[CCD] All download attempts failed" in text,
        "config_health": re.findall(r"ConfigHealth recomputed.*?state: '([^']+)'", text)}


def inference_evidence(events):
    requests = [row for row in events if row.get("event") == "request"]
    expected = [row for row in requests if row.get("max_tokens") == 1
        and row.get("billing") == "subscription" and row.get("messages") == 1
        and row.get("tools") == 0 and row.get("stream") is False]
    return {"inference_observed": bool(requests), "native_connection_probe_requests": len(expected),
        "unexpected_inference_observed": len(expected) != len(requests),
        "inference_scope": "No user prompt sent; Desktop may validate its static gateway credential with a one-token subscription request."}


def _copy_profile(source, destination):
    destination.mkdir(mode=0o700)
    config = source / "claude_desktop_config.json"
    if config.exists():
        shutil.copy2(config, destination / config.name)
    library = source / "configLibrary"
    if library.exists():
        shutil.copytree(library, destination / library.name)


def execute(root, duration=45):
    root = Path(root).resolve()
    native = desktop.executable(root)
    if desktop._existing_native_processes(native):
        raise RuntimeError("Existing native Desktop instance; refusing forwarding/interference risk")
    for binary in ("bwrap", "strace", "dbus-run-session", "import"):
        if not shutil.which(binary):
            raise RuntimeError("Missing test executable: " + binary)
    xvfb = shutil.which("Xvfb") or str(root / ".local/desktop-validation/tooling/xvfb/usr/bin/Xvfb")
    if not os.access(xvfb, os.X_OK):
        raise RuntimeError("Xvfb is missing; install test tooling explicitly")
    display_number = next((n for n in range(90, 120) if not Path(f"/tmp/.X11-unix/X{n}").exists()
        and not Path(f"/tmp/.X{n}-lock").exists()), None)
    if display_number is None:
        raise RuntimeError("No unallocated test X11 display")
    display = f":{display_number}"
    xsocket = Path(f"/tmp/.X11-unix/X{display_number}")
    guard = egress._direct_open(f"http://127.0.0.1:{egress.DEFAULT_PORT}/health")
    if guard.get("proxy_url") != f"http://127.0.0.1:{egress.DEFAULT_PORT}":
        raise RuntimeError("Unexpected private Claude egress guard endpoint")
    egress._direct_open("http://127.0.0.1:8787/health")
    regular, primary = desktop._primary_profiles()
    config_path = primary / "configLibrary" / (desktop.PROFILE_ID + ".json")
    config = json.loads(config_path.read_text())
    app = json.loads((primary / "claude_desktop_config.json").read_text())
    cli_path = Path.home() / ".claude/settings.json"
    cli = json.loads(cli_path.read_text())
    settings = configuration_summary(config, app, cli)
    picker_flags = {"discovery_enabled", "manual_model_list_absent"}
    required = [key for key, value in settings.items()
                if isinstance(value, bool) and not value and key not in picker_flags]
    if settings["picker_source"] == "discovery" and not settings["discovery_enabled"]:
        required.append("modelDiscoveryEnabled or inferenceModels")
    if required:
        raise RuntimeError("Installed settings do not meet probe contract: " + ", ".join(required))
    discovered = egress._direct_open("http://127.0.0.1:8787/v1/models", token=config["inferenceGatewayApiKey"])
    discovery = discovery_summary(discovered)
    if not discovery["rows"] or discovery["rows"] != discovery["opaque_id_rows"] or discovery["rows"] != discovery["unique_ids"]:
        raise RuntimeError("Gateway discovery returned an empty, duplicate, or non-opaque catalog")
    if settings["picker_source"] == "inferenceModels":
        names = [row["name"] if isinstance(row, dict) else row for row in config["inferenceModels"]]
        if len(names) != discovery["rows"] or set(names) != {row["id"] for row in discovered["data"]}:
            raise RuntimeError("Configured Desktop picker does not match the gateway catalog")
    if settings["pricing_rows"] != discovery["rows"]:
        raise RuntimeError("Installed native pricing does not cover every discovered route")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = root / ".local/desktop-validation" / ("features-" + stamp)
    run.mkdir(mode=0o700)
    for folder in ("runtime", "cache"):
        (run / folder).mkdir(mode=0o700)
    # Keep the exact executed sources alongside hashes before later edits.
    for source, name in ((Path(__file__), "driver.py.snapshot"),
            (root / "scripts/probe-offline.py", "probe-offline.py.snapshot"),
            (Path(desktop.__file__), "desktop.py.snapshot")):
        shutil.copyfile(source, run / name)
    _copy_profile(regular, run / "regular-profile")
    _copy_profile(primary, run / "third-party-profile")
    offline.write_json(run / "discovery.json", discovered)
    unix_path = root / ".local" / ("dt-" + stamp[-15:] + ".sock")
    env = egress.guard_environment(root, source=clean_environment())
    env.update({"DISPLAY": display, "XDG_RUNTIME_DIR": str(run / "runtime"), "XDG_CACHE_HOME": str(run / "cache"),
        "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_GROWTHBOOK": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_MODEL_CATALOG": "0", "DISABLE_FEEDBACK_COMMAND": "1"})
    for key in list(env):
        if key.startswith("NEURALDEEP_API_KEY_") or key in ("DBUS_SESSION_BUS_ADDRESS", "CLAUDE_USER_DATA_DIR", "ANTHROPIC_UNIX_SOCKET"):
            env.pop(key)
    # This optional diagnostic owns its stricter test-only network setup.
    # Ordinary Desktop launches use configuration flags and no private proxy.
    native_command = [shutil.which("dbus-run-session"), native,
        "--proxy-server=" + guard["proxy_url"],
        "--proxy-bypass-list=localhost;127.0.0.1;[::1];neuraldeep.ru;*.neuraldeep.ru;neuraldeep.tech;*.neuraldeep.tech",
        "--disable-quic", *desktop._launch_arguments(["--ozone-platform=x11"])]
    offline.write_json(run / "inside.json", {"host_netns": os.readlink("/proc/self/ns/net"),
        "ports": sorted(offline.ALLOWED_PORTS), "unix_socket": str(unix_path), "native_command": native_command})
    command = [shutil.which("bwrap"), "--unshare-net", "--unshare-pid", "--die-with-parent", "--bind", "/", "/",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/run", "--tmpfs", "/tmp", "--dir", "/tmp/.X11-unix",
        "--ro-bind", str(xsocket), str(xsocket), "--bind", str(run / "regular-profile"), str(regular),
        "--bind", str(run / "third-party-profile"), str(primary), "--ro-bind", str(cli_path.parent), str(cli_path.parent),
        "--chdir", str(run), "--", shutil.which("strace"), "-f", "-ttt", "-s", "256",
        "-e", "trace=connect,getsockopt", "-o", str(run / "strace.log"), sys.executable,
        str(root / "scripts/probe-offline.py"), "--execute", "--_inside", str(run / "inside.json")]
    receipt = {"status": "prepared", "started_at": datetime.now(timezone.utc).isoformat(), "run": str(run),
        "display": display, "runtime_limit_seconds": duration, "configuration": settings, "gateway_discovery": discovery,
        "native_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "probe_source_sha256": hashlib.sha256((root / "scripts/probe-offline.py").read_bytes()).hexdigest(),
        "native_app_outside_namespace": False, "live_profiles_modified": False, "ui_verified": False,
        "ui_review_required": "Inspect screenshots; config/logs alone do not prove visible picker contents.",
        "analysis_runtime_tested": False, "inference_requested": False, "screenshots": [], "interactive_ui_attempted": False}
    offline.write_json(run / "receipt.json", receipt)
    print(json.dumps({"status": "prepared", "run": str(run), "display": display}), flush=True)
    audit = []
    event_paths = {"guard": root / ".local/egress-events.jsonl", "gateway": root / ".local/gateway-events.jsonl"}
    offsets = {key: path.stat().st_size if path.exists() else 0 for key, path in event_paths.items()}
    process = xprocess = server = pool = thread = None
    try:
        with (run / "xvfb.log").open("w") as xlog:
            xprocess = subprocess.Popen([xvfb, display, "-screen", "0", "1280x900x24", "-nolisten", "tcp", "-ac", "-noreset"],
                stdin=subprocess.DEVNULL, stdout=xlog, stderr=xlog, start_new_session=True)
        for _ in range(50):
            if xsocket.exists():
                break
            if xprocess.poll() is not None:
                raise RuntimeError("Owned Xvfb startup failed")
            time.sleep(.1)
        if not xsocket.exists():
            raise RuntimeError("Owned Xvfb socket not created")
        server, pool, thread = offline.host_bridge(unix_path, audit)
        with (run / "stdout.log").open("w") as stdout, (run / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
            receipt.update(status="running", process_group=process.pid, xvfb_group=xprocess.pid)
            offline.write_json(run / "receipt.json", receipt)
            start = time.monotonic()
            next_capture = start + 5
            while time.monotonic() - start < duration and process.poll() is None:
                if time.monotonic() >= next_capture:
                    name = f"screen-{len(receipt['screenshots']):02d}.png"
                    capture = subprocess.run([shutil.which("import"), "-display", display, "-window", "root", str(run / name)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
                    if capture.returncode == 0:
                        receipt["screenshots"].append(name)
                    next_capture = time.monotonic() + 5
                    offline.write_json(run / "receipt.json", receipt)
                time.sleep(.2)
            receipt["natural_exit"] = process.poll()
    except BaseException as error:
        receipt.update(status="ERROR", error_type=type(error).__name__, error=str(error))
    finally:
        if process is not None:
            offline.stop_group(process.pid)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if pool is not None:
            pool.close()
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        unix_path.unlink(missing_ok=True)
        if xprocess is not None:
            offline.stop_group(xprocess.pid)
            try:
                xprocess.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    offline.write_json(run / "bridge-events.json", audit)
    for key, path in event_paths.items():
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(offsets[key])
                (run / (key + "-events.jsonl")).write_bytes(stream.read())
    logs = sorted((run / "third-party-profile/logs").glob("main*.log"))
    text = "\n".join(path.read_text(errors="replace") for path in logs)
    (run / "native-main.log").write_text(text)
    trace_path = run / "strace.log"
    trace = offline.parse_trace(trace_path.read_text(errors="replace")) if trace_path.exists() else {}
    offline.write_json(run / "connect-summary.json", trace)
    namespace_path = run / "namespace.json"
    namespace = json.loads(namespace_path.read_text()) if namespace_path.exists() else {}
    guard_events = offline.json_lines(run / "guard-events.jsonl")
    events = offline.json_lines(run / "gateway-events.jsonl")
    receipt.update(native_log_evidence(text, discovery["rows"], settings["picker_source"]))
    receipt.update(inference_evidence(events))
    receipt.update(finished_at=datetime.now(timezone.utc).isoformat(), namespace=namespace,
        bridge_removed=not unix_path.exists(), successful_nonloopback=len(trace.get("successful_nonloopback", [])),
        unresolved_nonloopback=len(trace.get("unresolved_nonloopback", [])),
        guard_external_connected=[row for row in guard_events if row.get("status") == "connected"],
        trace_connect_count=len(trace.get("connections", [])),
        gateway_bridge_used=any(row.get("event") == "bridge_connected" and row.get("port") == 8787 for row in audit))
    passed = (namespace.get("native_started_only_after_netns_verification") is True
        and receipt["native_picker_count_matches"] and receipt["third_party_gateway_logged"]
        and not receipt["native_config_rejected"] and receipt["bundled_catalog_logged"]
        and receipt["catalog_no_fetch_location_logged"] and not receipt["successful_nonloopback"]
        and not receipt["unresolved_nonloopback"] and not receipt["guard_external_connected"]
        and receipt["trace_connect_count"] > 0 and receipt["gateway_bridge_used"] and not receipt["unexpected_inference_observed"])
    if receipt["status"] != "ERROR":
        receipt["status"] = "PASS" if passed else "INCOMPLETE"
    receipt["file_hashes"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run.iterdir() if path.is_file() and path.name != "receipt.json"}
    offline.write_json(run / "receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "file_hashes"}, indent=2), flush=True)
    return 0 if receipt["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--duration", type=int, default=45, choices=range(10, 121), metavar="10..120")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(plan(args.root), indent=2))
        return 0
    if sys.platform != "linux":
        parser.error("--execute requires Linux bwrap/Xvfb; dry run is available on every platform")
    return execute(args.root, args.duration)


if __name__ == "__main__":
    raise SystemExit(main())
