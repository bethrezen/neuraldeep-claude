#!/usr/bin/env python3
"""Dry-run-first Linux network-namespace smoke for the guarded native Claude CLI.

The real CLI is executed only inside bwrap --unshare-net. An ephemeral Unix
bridge exposes exactly two host loopback ports; it is removed on completion.
This validates a bounded test, not an OS sandbox for production launches.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ALLOWED_PORTS = frozenset({8787, 18790})
MAGIC = b"ND"


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def recv_exact(stream, count):
    parts = bytearray()
    while len(parts) < count:
        data = stream.recv(count - len(parts))
        if not data:
            raise EOFError("Incomplete bridge frame")
        parts.extend(data)
    return bytes(parts)


def parse_port(frame):
    if len(frame) != 4 or frame[:2] != MAGIC:
        raise ValueError("Invalid bridge frame")
    port = struct.unpack("!H", frame[2:])[0]
    if port not in ALLOWED_PORTS:
        raise ValueError("Bridge target port denied")
    return port


def relay(left, right, stop):
    readers = {left: right, right: left}
    while readers and not stop.is_set():
        ready, _, _ = select.select(list(readers), [], [], 0.25)
        for source in ready:
            data = source.recv(65536)
            target = readers[source]
            if data:
                target.sendall(data)
            else:
                del readers[source]
                try:
                    target.shutdown(socket.SHUT_WR)
                except OSError:
                    pass


class SocketPool:
    def __init__(self):
        self.lock = threading.Lock()
        self.sockets = set()
        self.stop = threading.Event()

    def add(self, *streams):
        with self.lock:
            self.sockets.update(streams)

    def drop(self, *streams):
        with self.lock:
            for stream in streams:
                self.sockets.discard(stream)
                stream.close()

    def close(self):
        self.stop.set()
        with self.lock:
            for stream in self.sockets:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                stream.close()
            self.sockets.clear()


def host_bridge(path, audit):
    pool = SocketPool()
    audit_lock = threading.Lock()

    def log(record):
        with audit_lock:
            audit.append({"time": time.time(), **record})

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            incoming = self.request
            outgoing = None
            pool.add(incoming)
            try:
                incoming.settimeout(5)
                port = parse_port(recv_exact(incoming, 4))
                outgoing = socket.create_connection(("127.0.0.1", port), timeout=5)
                pool.add(outgoing)
                incoming.sendall(b"\x00")
                incoming.settimeout(None)
                outgoing.settimeout(None)
                log({"event": "bridge_connected", "host": "127.0.0.1", "port": port})
                relay(incoming, outgoing, pool.stop)
            except (OSError, EOFError, ValueError) as exc:
                log({"event": "bridge_closed", "error_type": type(exc).__name__})
            finally:
                pool.drop(*([incoming, outgoing] if outgoing else [incoming]))

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
        block_on_close = False

    server = Server(str(path), Handler)
    os.chmod(path, 0o600)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    return server, pool, thread


def inner_shim(port, unix_path, pool):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            incoming = self.request
            outgoing = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            pool.add(incoming, outgoing)
            try:
                outgoing.settimeout(5)
                outgoing.connect(unix_path)
                outgoing.sendall(MAGIC + struct.pack("!H", port))
                if recv_exact(outgoing, 1) != b"\x00":
                    raise OSError("Host bridge did not acknowledge")
                outgoing.settimeout(None)
                relay(incoming, outgoing, pool.stop)
            except (OSError, EOFError):
                pass
            finally:
                pool.drop(incoming, outgoing)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
        block_on_close = False

    server = Server(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    return server, thread


def inside(spec_path):
    """No native subprocess can start until namespace identity is checked."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    current_ns = os.readlink("/proc/self/ns/net")
    if current_ns == spec["host_netns"]:
        raise RuntimeError("Refusing native execution outside the new network namespace")
    # /proc/net is namespace-sensitive even though the shared filesystem is bound.
    interfaces = [line.split(":", 1)[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()[2:] if ":" in line]
    if set(interfaces) != {"lo"}:
        raise RuntimeError("Unexpected network interfaces in isolated namespace")
    if set(spec["ports"]) != ALLOWED_PORTS:
        raise RuntimeError("Unexpected bridge port policy")
    pool = SocketPool()
    servers = []
    try:
        for port in sorted(ALLOWED_PORTS):
            server, thread = inner_shim(port, spec["unix_socket"], pool)
            servers.append((server, thread))
        write_json(Path(spec_path).with_name("namespace.json"), {
            "host_netns": spec["host_netns"], "inner_netns": current_ns,
            "interfaces": interfaces, "ports": sorted(ALLOWED_PORTS),
            "native_started_only_after_netns_verification": True,
        })
        return subprocess.call(spec["native_command"], stdin=subprocess.DEVNULL)
    finally:
        pool.close()
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def parse_trace(text):
    """Conservative connect metadata. EINPROGRESS is never counted as success."""
    connections = []
    for line in text.splitlines():
        if "connect(" not in line or "sa_family=AF_UNIX" in line:
            continue
        family = "IPv6" if "sa_family=AF_INET6" in line else "IPv4" if "sa_family=AF_INET" in line else "other"
        if family == "other":
            continue
        match = re.search(r'(?:inet_addr\("([^\"]+)"\)|inet_pton\(AF_INET6, "([^\"]+)")', line)
        address = next((v for v in match.groups() if v), None) if match else None
        port_match = re.search(r'sin6?_port=htons\((\d+)\)', line)
        result = line.rsplit(" = ", 1)[-1] if " = " in line else "unfinished"
        try:
            parsed = ipaddress.ip_address(address) if address else None
            parsed = getattr(parsed, "ipv4_mapped", None) or parsed
            loopback = parsed.is_loopback if parsed else None
        except ValueError:
            loopback = None
        disposition = "success" if result == "0" else "pending" if "EINPROGRESS" in result or "unfinished" in result else "failed"
        connections.append({"family": family, "address": address,
            "port": int(port_match.group(1)) if port_match else None,
            "loopback": loopback, "result": result, "disposition": disposition})
    external = [x for x in connections if x["loopback"] is not True]
    return {"connections": connections,
        "successful_nonloopback": [x for x in external if x["disposition"] == "success"],
        "unresolved_nonloopback": [x for x in external if x["disposition"] == "pending"],
        "failed_nonloopback": [x for x in external if x["disposition"] == "failed"],
        "enetwork_unreachable": sum("ENETUNREACH" in x["result"] for x in external),
        "note": "Nonblocking public connects are unresolved, not treated as failed. Kernel netns is the independent isolation boundary."}


def json_lines(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


def plan(root, model, *, design=False, tool_search=False, host_pricing=False):
    return {"execute": False, "platform": sys.platform, "model": model,
        "mode": "tool-search" if tool_search else "design" if design else "basic", "execution_platform": "linux only",
        "native_execution": "only inside bwrap --unshare-net --bind / /",
        "host_bridge": {"protocol": "ND + uint16 big-endian port", "host": "127.0.0.1", "ports": sorted(ALLOWED_PORTS)},
        "prompt": "Discover one local MCP echo through native ToolSearch, invoke it, check its marker; no service tools." if tool_search else "Invoke native nd-design; reuse an existing local PNG, write offline HTML; no image generation or service HTTP." if design else "Reply with exactly OFFLINE_OK and nothing else.",
        "tools": "ToolSearch and a single local stdio MCP echo fixture; NeuralDeep service MCP servers omitted" if tool_search else "Bash,Read,Write,Edit,Skill; NeuralDeep service tools explicitly denied" if design else "none; all enabled NeuralDeep MCP servers still initialize",
        "experimental_host_pricing": host_pricing,
        "root": str(root), "message": "Dry run: no services, namespace or Claude process started. Add --execute for the authorized bounded model call."}


def experimental_host_pricing(root):
    """Build parent-host pricing for raw CLI picker IDs; never change policy."""
    from neuraldeep_claude import catalog
    from neuraldeep_claude.pricing import desktop_report
    data = catalog.load(root)
    report = desktop_report(root, data)
    aliases = {row["name"]: row for row in report["models"]}
    overrides = {}
    for option in catalog.picker(data):
        row = aliases.get(catalog.gateway_alias(option["model"]))
        if row is None:
            continue
        overrides[option["model"]] = {target: row[source] for target, source in (
            ("input", "inputPerMtok"), ("output", "outputPerMtok"),
            ("cacheRead", "cacheReadPerMtok"), ("cacheWrite", "cacheWritePerMtok"))}
    settings = {"modelPricing": {"overrides": overrides}}
    return settings, {"rows": len(overrides), "fx": report["fx"], "omitted": report["omitted"],
                      "raw_cli_ids_only": True, "genuine_admin_policy_precedes_host": True}


def experimental_pricing_evidence(final, model):
    usage = final.get("modelUsage", {}).get(model, {})
    # SDK ModelUsage names this basis 'managed'; the internal cost calculator's
    # separate pricing enum calls the same table 'configured'.
    return {"model_pricing_configured": usage.get("costBasis") == "managed",
            "subscription_incremental_cost_zero": usage.get("costUSD") == 0 and final.get("total_cost_usd") == 0,
            "nonzero_model_usage": usage.get("inputTokens", 0) + usage.get("outputTokens", 0) > 0,
            "native_cost_basis": usage.get("costBasis"), "native_model_cost_usd": usage.get("costUSD"),
            "native_total_cost_usd": final.get("total_cost_usd")}


def local_mcp_echo(audit_path):
    """A stdio fixture; never opens a network connection or reads credentials."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            method = request.get("method")
            if "id" not in request:
                continue
            if method == "initialize":
                result = {"protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "nd-local-tool-search-probe", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo_marker", "description": "Echo a marker for the local NeuralDeep tool search diagnostic.",
                    "inputSchema": {"type": "object", "properties": {"marker": {"type": "string"}},
                                    "required": ["marker"], "additionalProperties": False}}]}
            elif method == "tools/call":
                params = request.get("params", {})
                marker = params.get("arguments", {}).get("marker")
                if params.get("name") != "echo_marker" or not isinstance(marker, str):
                    result = {"isError": True, "content": [{"type": "text", "text": "Expected echo_marker with string marker"}]}
                else:
                    with Path(audit_path).open("a", encoding="utf-8") as audit:
                        audit.write(json.dumps({"tool": "echo_marker", "marker": marker}) + "\n")
                    result = {"content": [{"type": "text", "text": "ECHO_MARKER=" + marker}]}
            elif method == "ping":
                result = {}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                continue
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
        except (ValueError, TypeError, KeyError):
            # Malformed fixture requests are not interpreted as a tool success.
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC request"}}), flush=True)
    return 0


def tool_search_evidence(messages, audit_rows, expected_tool, marker):
    """Require discovery, returned references and invocation, not a claimed reply."""
    calls, references = [], []
    for item_index, item in enumerate(messages):
        content = item.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls.append((item_index, block))
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                references.extend((item_index, block.get("tool_use_id"), ref.get("tool_name"))
                    for ref in block["content"] if isinstance(ref, dict) and ref.get("type") == "tool_reference")
    searches = [(index, call) for index, call in calls if call.get("name") == "ToolSearch"]
    search_ids = {call.get("id") for _, call in searches}
    matching_refs = [(index, ref_id) for index, ref_id, name in references if name == expected_tool and ref_id in search_ids]
    echo_calls = [(index, call) for index, call in calls if call.get("name") == expected_tool and call.get("input", {}).get("marker") == marker]
    return {"native_tool_search_invoked": bool(searches), "native_tool_reference_received": bool(matching_refs),
            "native_echo_invoked_after_discovery": any(ref_index < call_index for ref_index, _ in matching_refs for call_index, _ in echo_calls),
            "local_echo_audit_matches": any(row == {"tool": "echo_marker", "marker": marker} for row in audit_rows),
            "search_calls": len(searches), "echo_calls": len(echo_calls)}


def stop_group(group):
    for sig, wait in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    return False


def execute(root, model, timeout, *, design=False, asset=None, tool_search=False, host_pricing=False):
    if sys.platform != "linux":
        raise RuntimeError("--execute requires Linux bwrap network namespaces")
    for name in ("bwrap", "strace"):
        if not shutil.which(name):
            raise RuntimeError("Required executable unavailable: " + name)
    if not (root / ".local/native-cli.json").is_file():
        raise RuntimeError("A registered real native CLI is required; refusing launcher fallback")
    if not (root / ".local/catalog.json").is_file():
        raise RuntimeError("Cached catalog required; this test never refreshes it")
    from neuraldeep_claude.integration import build_settings, native_cli
    from neuraldeep_claude.config import clean_environment
    from neuraldeep_claude.egress import guard_environment, _direct_open
    from neuraldeep_claude.services import mcp_config, TOOLS
    settings = build_settings(root, model)
    native = str(Path(native_cli(root)).resolve())
    with Path(native).open("rb") as handle:
        if handle.read(4) != b"\x7fELF":
            raise RuntimeError("Expected the registered native Linux ELF CLI, not a wrapper")
    env = clean_environment()
    env.update(settings["env"])
    env = guard_environment(root, source=env, port=18790)
    env["PYTHONUTF8"] = "1"
    if tool_search:
        # The gateway needs the tool-search beta shape while unrelated native
        # betas remain suppressed. CLI 2.1.316 explicitly supports force for
        # this custom-base-URL/firstParty provider case.
        env["ENABLE_TOOL_SEARCH"] = "force"
    if host_pricing:
        env["CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST"] = "1"
    # A pre-existing host Unix-socket inference override would bypass this test's
    # fixed TCP endpoints. Do not inherit it into the isolated native process.
    env.pop("ANTHROPIC_UNIX_SOCKET", None)
    gateway_health = _direct_open("http://127.0.0.1:8787/health")
    guard_health = _direct_open("http://127.0.0.1:18790/health")
    if guard_health.get("proxy_url") != "http://127.0.0.1:18790":
        raise RuntimeError("Unexpected egress guard endpoint")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = root / ".local/offline-validation" / stamp
    run.mkdir(parents=True, mode=0o700)
    unix_path = run / "bridge.sock"
    if len(os.fsencode(unix_path)) >= 108:
        raise RuntimeError("Unix socket path exceeds Linux limit; use a shorter checkout path")
    echo_tool = "mcp__nd-local-probe__echo_marker"
    marker = "ND_TOOL_SEARCH_" + stamp
    servers = ({"mcpServers": {"nd-local-probe": {"command": sys.executable,
        "args": [str(Path(__file__).resolve()), "--_mcp-echo", str(run / "echo-audit.jsonl")]}}}
        if tool_search else mcp_config(root))
    write_json(run / "mcp.json", servers)
    native_command = [native, "--setting-sources", "user", "--strict-mcp-config", "--mcp-config", str(run / "mcp.json"),
        "--tools", "ToolSearch" if tool_search else "Bash,Read,Write,Edit,Skill" if design else "", "--model", settings["model"], "--no-session-persistence", "--permission-mode", "dontAsk",
        "--output-format", "stream-json", "--verbose"]
    asset_hash = None
    if tool_search:
        prompt = f'''Run this local tool-search diagnostic exactly. First invoke the native ToolSearch tool with query="select:{echo_tool}" to discover the deferred local MCP echo. After its tool reference arrives, invoke {echo_tool} with marker="{marker}". Wait for its real result ECHO_MARKER={marker}. Finally reply with exactly TOOL_SEARCH_OK {marker}. Do not answer success before both tool calls. Do not call any other tools or external services.'''
        # CLI user settings can override an inherited environment variable.
        # A command-level setting proves the adapter without mutating the user's
        # active configuration, including when testing an unactivated checkout.
        native_command += ["--settings", json.dumps({"env": {"ENABLE_TOOL_SEARCH": "force"}}),
                           "--allowedTools", "ToolSearch," + echo_tool]
    elif design:
        asset = Path(asset).resolve() if asset else root / ".local/design-validation/20261102T160051Z-controlled/site/assets/hero.png"
        if not asset.is_file() or asset.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Design smoke requires the existing local PNG; no generation is allowed")
        asset_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
        site = run / "site"
        site.mkdir()
        prompt = f'''Invoke the native Skill tool with skill="nd-design" first. Execute this /nd-design local workflow now; all decisions are fixed, do not ask questions.
Create a concise polished offline landing page for Orbital Studio, a quiet workspace for independent designers. Use midnight blue, ivory, a cyan accent, system fonts, a hero and three feature cards. Read the EXISTING image {asset} with Read before incorporating it. Reuse this exact image only: copy it to {site}/assets/hero.png and write {site}/index.html with inline CSS and an img src="assets/hero.png" plus {site}/README.txt. No new image generation or editing. No MCP operations, HTTP requests, web searches, package installs, publication, uploads, global config changes or credentials access. Everything must work from file://. The installed skill/runtime may be read locally. Keep the workflow short and use only Skill, Read, Write/Edit and Bash for local files. After checking files exist and image copy matches, finish with DESIGN_OFFLINE_OK and exact paths. Browser verification is unavailable in this bounded smoke; do not claim screenshots or clicks.'''
        native_command += ["--allowedTools", "Skill,Read,Write,Edit,Bash", "--disallowedTools",
            ",".join("mcp__neuraldeep-" + tool.group + "__" + tool.name for tool in TOOLS)]
    else:
        prompt = "Reply with exactly OFFLINE_OK and nothing else."
    native_command += ["-p", prompt]
    host_pricing_receipt = None
    if host_pricing:
        parent_settings, host_pricing_receipt = experimental_host_pricing(root)
        prices = parent_settings["modelPricing"]["overrides"]
        selected_price = prices.get(settings["model"])
        if not selected_price or any(selected_price.values()):
            raise ValueError("Experimental host-pricing smoke requires a priced zero-incremental-cost subscription model")
        parent_json = json.dumps(parent_settings, ensure_ascii=False, separators=(",", ":"))
        native_command[1:1] = ["--managed-settings", parent_json]
        windows_chars = len(subprocess.list2cmdline(native_command))
        if windows_chars > 30000:
            raise ValueError("Experimental parent pricing exceeds the portable Windows command-line budget")
        write_json(run / "host-pricing.json", parent_settings)
        host_pricing_receipt.update(compact_json_chars=len(parent_json), windows_command_chars=windows_chars,
                                    selected_model=settings["model"], selected_rate=selected_price)
    spec = {"host_netns": os.readlink("/proc/self/ns/net"), "ports": sorted(ALLOWED_PORTS),
        "unix_socket": str(unix_path), "native_command": native_command}
    write_json(run / "inside.json", spec)
    audit = []
    server = pool = thread = process = None
    guard_log = root / ".local/egress-events.jsonl"
    guard_before = len(json_lines(guard_log))
    gateway_log = root / ".local/gateway-events.jsonl"
    gateway_before = len(json_lines(gateway_log))
    receipt = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "running", "run": str(run),
        "execute": True, "mode": "tool-search" if tool_search else "design" if design else "basic", "model": settings["model"], "native": native,
        "native_sha256": hashlib.file_digest(Path(native).open("rb"), "sha256").hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "guard_health": guard_health, "gateway_health": gateway_health,
        "offline_flags": {key: env[key] for key in settings["env"] if key.startswith("DISABLE_") or key in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DO_NOT_TRACK", "CLAUDE_CODE_ENABLE_TELEMETRY", "CLAUDE_CODE_MODEL_CATALOG")},
        "bridge_policy": {"host": "127.0.0.1", "ports": sorted(ALLOWED_PORTS)},
        "mcp_servers": list(servers["mcpServers"]), "timeout_seconds": timeout,
        "filesystem_sandbox": False, "network_namespace": True,
        "production_os_sandbox": False, "credentials_recorded": False}
    if design:
        receipt["existing_image"] = {"path": str(asset), "sha256": asset_hash}
    if tool_search:
        receipt["tool_search_fixture"] = {"tool": echo_tool, "marker": marker,
                                          "service_tools_enabled": False, "ENABLE_TOOL_SEARCH": env["ENABLE_TOOL_SEARCH"]}
    if host_pricing:
        receipt["experimental_host_pricing"] = host_pricing_receipt
    write_json(run / "receipt.json", receipt)
    print("RUN " + str(run), flush=True)
    command = [shutil.which("bwrap"), "--unshare-net", "--die-with-parent", "--bind", "/", "/", "--dev", "/dev", "--chdir", str(run), "--",
        shutil.which("strace"), "-f", "-ttt", "-s", "256", "-e", "trace=connect,getsockopt", "-o", str(run / "strace.log"),
        sys.executable, str(Path(__file__).resolve()), "--execute", "--_inside", str(run / "inside.json")]
    receipt["namespace_command"] = command
    previous_term = signal.getsignal(signal.SIGTERM)
    def terminated(_signal, _frame):
        raise KeyboardInterrupt("Probe termination requested")
    signal.signal(signal.SIGTERM, terminated)
    try:
        server, pool, thread = host_bridge(unix_path, audit)
        with (run / "stdout.jsonl").open("w") as stdout, (run / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
            receipt["process_group"] = process.pid
            write_json(run / "receipt.json", receipt)
            deadline = time.monotonic() + timeout
            next_update = time.monotonic() + 20
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    receipt["status"] = "timeout"
                    os.killpg(process.pid, signal.SIGTERM)
                    break
                if time.monotonic() >= next_update:
                    next_update += 20
                    print("PROGRESS transcript_bytes=" + str((run / "stdout.jsonl").stat().st_size), flush=True)
                time.sleep(0.25)
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
            receipt["exit_code"] = code
    except BaseException as exc:
        receipt.update(status="ABORTED" if isinstance(exc, KeyboardInterrupt) else "FAIL",
                       error_type=type(exc).__name__)
        write_json(run / "receipt.json", receipt)
    finally:
        if process is not None:
            # Native helpers may outlive their parent; the group is unique to
            # this test. Never address any shared service or unrelated group.
            receipt["own_process_group_removed"] = stop_group(process.pid)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                receipt["own_process_group_removed"] = True
        if pool:
            pool.close()
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=2)
        unix_path.unlink(missing_ok=True)
        write_json(run / "bridge-events.json", audit)
        signal.signal(signal.SIGTERM, previous_term)
    trace_path = run / "strace.log"
    trace = parse_trace(trace_path.read_text(errors="replace") if trace_path.exists() else "")
    write_json(run / "connect-summary.json", trace)
    guard_events = json_lines(guard_log)[guard_before:]
    gateway_events = json_lines(gateway_log)[gateway_before:]
    write_json(run / "guard-events.json", guard_events)
    write_json(run / "gateway-events.json", gateway_events)
    messages = json_lines(run / "stdout.jsonl")
    init = next((x for x in messages if x.get("type") == "system" and x.get("subtype") == "init"), {})
    final = next((x for x in reversed(messages) if x.get("type") == "result"), {})
    ns_file = run / "namespace.json"
    namespace = json.loads(ns_file.read_text()) if ns_file.exists() else {}
    connected_guard_hosts = [x.get("host") for x in guard_events if x.get("status") == "connected"]
    actual_mcp = {row.get("name"): row.get("status") for row in init.get("mcp_servers", [])}
    expected_mcp = set(servers["mcpServers"])
    skill_events = [block for item in messages for block in item.get("message", {}).get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill" and block.get("input", {}).get("skill") == "nd-design"]
    design_files = {}
    if design:
        for relative in ("index.html", "README.txt", "assets/hero.png"):
            path = run / "site" / relative
            design_files[relative] = {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    evidence = {"namespace_verified": bool(namespace.get("native_started_only_after_netns_verification")),
        "exact_reply": ((final.get("result", "").strip() == "TOOL_SEARCH_OK " + marker) if tool_search else ("DESIGN_OFFLINE_OK" in final.get("result", "")) if design else final.get("result", "").strip() == "OFFLINE_OK") and final.get("is_error") is False,
        "exit_zero": receipt.get("exit_code") == 0,
        "successful_nonloopback_connections": len(trace["successful_nonloopback"]),
        "unresolved_nonloopback_connects": len(trace["unresolved_nonloopback"]),
        "host_guard_connected_external": connected_guard_hosts,
        "native_version": init.get("claude_code_version"), "skills": init.get("skills", []),
        "nd_design_discovered": "nd-design" in init.get("skills", []),
        "nd_workflow_discovered": "nd-workflow" in init.get("skills", []),
        "mcp_servers": init.get("mcp_servers", []),
        "all_expected_mcp_connected": bool(expected_mcp) and all(actual_mcp.get(name) == "connected" for name in expected_mcp),
        "expected_mcp_count": len(expected_mcp),
        "fourteen_mcp_expected": len(expected_mcp) == 14,
        "workflow_tool_advertised": any(x == "Workflow" for x in init.get("tools", [])),
        "trace_present_and_nonempty": trace_path.is_file() and trace_path.stat().st_size > 0,
        "parsed_connect_count": len(trace["connections"]),
        "bridge_gateway_used": any(x.get("event") == "bridge_connected" and x.get("port") == 8787 for x in audit),
        "gateway_request_count": sum(x.get("event") == "request" for x in gateway_events),
        "zero_external_gate": "This no-tools smoke requires no host-guard external connections, not only a vendor-domain check."}
    if design:
        html_path = run / "site/index.html"
        html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
        evidence.update(native_skill_invoked=bool(skill_events), design_files=design_files,
            image_copy_matches=design_files["assets/hero.png"]["sha256"] == asset_hash,
            html_local_image_reference=bool(re.search(r'''src=["']assets/hero\.png["']''', html)),
            html_no_remote_reference=not bool(re.search(r'''(?:src|href)\s*=\s*["'](?:https?:)?//''', html, re.I)),
            ui_verified=False, zero_external_gate="Design smoke uses only local files and host gateway; no MCP service calls or external guard connections allowed.")
    if tool_search:
        evidence.update(tool_search_evidence(messages, json_lines(run / "echo-audit.jsonl"), echo_tool, marker))
        evidence.update(tool_search_advertised="ToolSearch" in init.get("tools", []),
                        zero_external_gate="Tool search smoke permits one local stdio MCP fixture and host inference gateway; no service calls or external guard connections allowed.")
    if host_pricing:
        evidence.update(experimental_pricing_evidence(final, settings["model"]))
    required = ["namespace_verified", "exact_reply", "exit_zero", "trace_present_and_nonempty", "parsed_connect_count", "bridge_gateway_used", "gateway_request_count", "all_expected_mcp_connected"]
    if tool_search:
        required += ["tool_search_advertised", "native_tool_search_invoked", "native_tool_reference_received", "native_echo_invoked_after_discovery", "local_echo_audit_matches"]
    else:
        required += ["fourteen_mcp_expected", "nd_design_discovered", "nd_workflow_discovered"]
    if host_pricing:
        required += ["model_pricing_configured", "subscription_incremental_cost_zero", "nonzero_model_usage"]
    passed = all(evidence[key] for key in required) and not trace["successful_nonloopback"] and not trace["unresolved_nonloopback"] and not connected_guard_hosts
    if design:
        passed = passed and all(evidence[key] for key in ("native_skill_invoked", "image_copy_matches", "html_local_image_reference", "html_no_remote_reference")) and all(x["exists"] and x["bytes"] for x in design_files.values())
    receipt.update(status="PASS" if passed else receipt["status"] if receipt["status"] in ("timeout", "ABORTED") else "FAIL",
        finished_at=datetime.now(timezone.utc).isoformat(), evidence=evidence, socket_removed=not unix_path.exists())
    receipt["file_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file() and p.name != "receipt.json"}
    write_json(run / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "run": str(run), "evidence": evidence}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--model", default="qwen3.8-27b~xhigh")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--execute", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--design", action="store_true", help="One optional local native Skill proof; reuse PNG, no MCP service calls")
    modes.add_argument("--tool-search", action="store_true", help="Native ToolSearch discovery + one local MCP echo; no service tools")
    parser.add_argument("--host-pricing", action="store_true", help="Experimental parent-host pricing trial; no default installation changes")
    parser.add_argument("--asset", type=Path, help="Existing local PNG for --design")
    parser.add_argument("--_inside", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_mcp-echo", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._mcp_echo:
        return local_mcp_echo(args._mcp_echo)
    if not args.execute:
        print(json.dumps(plan(args.root.resolve(), args.model, design=args.design, tool_search=args.tool_search, host_pricing=args.host_pricing), ensure_ascii=False, indent=2))
        return 0
    if sys.platform != "linux":
        parser.error("--execute requires Linux bwrap network namespaces; dry run is available on every platform")
    if args._inside:
        return inside(args._inside)
    return execute(args.root.resolve(), args.model, args.timeout, design=args.design, asset=args.asset, tool_search=args.tool_search, host_pricing=args.host_pricing)


if __name__ == "__main__":
    raise SystemExit(main())
