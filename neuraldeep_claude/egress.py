"""Loopback HTTP(S) egress policy for proxy-aware Claude processes.

This is a destination guard, not an OS network sandbox. Clients which bypass
HTTP proxies, UDP/QUIC, native helpers and arbitrary tools require independent
OS enforcement for a hard no-egress guarantee. NeuralDeep bypasses this proxy
and its backend uses ProxyHandler({}); this module never uses ambient proxies.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import urllib.request
import urllib.error

DEFAULT_PORT = 18790
BLOCKED_SUFFIXES = (
    "anthropic.com", "anthropic.ai", "claude.ai", "claude.com", "claudeusercontent.com",
    "claudemcpcontent.com", "ant.dev", "statsig.com", "statsigapi.net",
    "statsigapi.com", "statsigcdn.com", "statsigcdn.net", "statsiglog.net", "sentry.io",
)
BLOCKED_HOSTS = (
    "claude.googleapis.com", "claude.fedstart.com", "claude-staging.fedstart.com",
    "storage.googleapis.com", "api.datadoghq.com", "o1158394.ingest.us.sentry.io",
    "http-intake.logs.us5.datadoghq.com", "browser-intake-datadoghq.com",
    "browser-intake-us3-datadoghq.com", "browser-intake-us5-datadoghq.com",
    "browser-intake-ap1-datadoghq.com", "browser-intake-ap2-datadoghq.com",
    "browser-intake-datadoghq.eu", "browser-intake-ddog-gov.com",
)
# No guessed vendor IP ranges. Additional verified ranges belong in the local
# policy's blocked_ip_networks. Non-loopback literal IP requests are denied.
DENIED_SUFFIXES = BLOCKED_SUFFIXES
DENIED_HOSTS = BLOCKED_HOSTS
NO_PROXY_HOSTS = "localhost,127.0.0.1,::1,neuraldeep.ru,.neuraldeep.ru,neuraldeep.tech,.neuraldeep.tech"
HOP_HEADERS = {"proxy-authorization", "proxy-authenticate", "proxy-connection", "connection", "keep-alive", "upgrade"}


class EgressDenied(ValueError):
    pass


def _literal(host):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Reject legacy numeric IPv4 spellings too; inet_aton does no DNS.
        if re.fullmatch(r"[0-9a-fA-FxX.]+", host) and any(c.isdigit() for c in host):
            try:
                address = ipaddress.ip_address(socket.inet_aton(host))
            except OSError:
                return None
        else:
            return None
    return address.ipv4_mapped if getattr(address, "ipv4_mapped", None) else address


def normalize_host(host):
    if not isinstance(host, str) or not host or any(ord(c) <= 32 or ord(c) == 127 for c in host):
        raise EgressDenied("Invalid destination hostname")
    host = host.rstrip(".").lower()
    address = _literal(host)
    if address is not None:
        return str(address)
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise EgressDenied("Invalid destination hostname") from exc
    if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")):
        raise EgressDenied("Invalid destination hostname")
    return host


def authority(value, default_port=None):
    if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value) or any(c in value for c in "/?#@\\"):
        raise EgressDenied("Invalid proxy authority")
    try:
        parsed = urlsplit("//" + value)
        host = normalize_host(parsed.hostname or "")
        port = parsed.port if parsed.port is not None else default_port
    except ValueError as exc:
        raise EgressDenied("Invalid proxy authority") from exc
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise EgressDenied("Invalid destination port")
    return host, port


class EgressPolicy:
    def __init__(self, *, blocked_suffixes=(), blocked_hosts=(), blocked_ip_networks=(), deny_literal_ips=True):
        self.suffixes = tuple(sorted(set(BLOCKED_SUFFIXES) | {normalize_host(x) for x in blocked_suffixes}))
        self.hosts = frozenset(BLOCKED_HOSTS) | frozenset(normalize_host(x) for x in blocked_hosts)
        self.networks = tuple(ipaddress.ip_network(x, strict=False) for x in blocked_ip_networks)
        self.deny_literal_ips = deny_literal_ips

    def blocked(self, host):
        host = normalize_host(host)
        return host in self.hosts or any(host == suffix or host.endswith("." + suffix) for suffix in self.suffixes) or host.startswith("aws-external-anthropic.")

    def addresses(self, host, port, *, own_port=None):
        host = normalize_host(host)
        # The primary domain decision happens before even DNS resolution.
        if self.blocked(host):
            raise EgressDenied("Destination denied")
        literal = _literal(host)
        if literal is not None and self.deny_literal_ips and not literal.is_loopback:
            raise EgressDenied("Literal IP destination denied")
        if literal is not None and literal.is_loopback and port in {20171, own_port}:
            raise EgressDenied("Proxy chaining destination denied")
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_CANONNAME)
        if not addresses:
            raise OSError("No destination addresses")
        for family, kind, proto, canonical, address in addresses:
            if canonical and self.blocked(canonical):
                raise EgressDenied("Canonical destination denied")
            resolved = _literal(address[0])
            if resolved is None or any(resolved in network for network in self.networks if resolved.version == network.version):
                raise EgressDenied("Resolved destination denied")
            if resolved.is_loopback and port in {20171, own_port}:
                raise EgressDenied("Proxy chaining destination denied")
        return addresses

    def digest(self):
        raw = json.dumps({"suffixes": self.suffixes, "hosts": sorted(self.hosts), "networks": [str(x) for x in self.networks], "deny_literal_ips": self.deny_literal_ips}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


def load_policy(root):
    path = Path(root) / ".local/egress-policy.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return EgressPolicy(**{key: data[key] for key in ("blocked_suffixes", "blocked_hosts", "blocked_ip_networks", "deny_literal_ips") if key in data})


def _control_token(root):
    path = Path(root) / ".local/egress-control-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    return token


def _root_id(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _direct_open(url, method="GET", token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(urllib.request.Request(url, method=method, headers=headers), timeout=3) as response:
        return json.load(response)


def create_server(root, port=DEFAULT_PORT, *, policy=None):
    root = Path(root).resolve()
    policy = policy or load_policy(root)
    token = _control_token(root)
    log_lock = threading.Lock()
    counter_lock = threading.Lock()
    counters = {"blocked": 0, "connections": 0, "active": 0}
    stop = threading.Event()

    def audit(host, status):
        # Never log request paths, queries, bodies, credentials or headers.
        record = json.dumps({"host": host, "status": status}, ensure_ascii=True) + "\n"
        path = root / ".local/egress-events.jsonl"
        with log_lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(record)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *_):
            pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def health(self):
            with counter_lock:
                counts = dict(counters)
            return {"service": "neuraldeep-claude-egress", "root_id": _root_id(root), "policy_sha256": policy.digest(),
                "proxy_url": f"http://127.0.0.1:{self.server.server_port}", "direct_upstream": True,
                "proxy_aware_only": True, "os_network_sandbox": False, "literal_nonloopback_ips_denied": policy.deny_literal_ips,
                "blocked_suffixes": list(policy.suffixes), "blocked_hosts": sorted(policy.hosts), **counts}

        def connect_target(self, host, port):
            resolved = policy.addresses(host, port, own_port=self.server.server_port)
            failure = None
            # Connect the validated numeric sockaddr directly: no second DNS lookup.
            for family, kind, proto, canonical, address in resolved:
                stream = socket.socket(family, kind, proto)
                try:
                    stream.settimeout(30)
                    stream.connect(address)
                    stream.settimeout(None)
                    return stream
                except OSError as exc:
                    failure = exc
                    stream.close()
            raise failure or OSError("Cannot connect destination")

        def blocked(self, host):
            with counter_lock:
                counters["blocked"] += 1
            audit(host, "blocked")
            self.reply(403, {"error": "Destination denied by Claude egress policy"})

        def target_host_header(self):
            value = self.headers.get("Host")
            if value:
                host, _ = authority(value, 443 if self.command == "CONNECT" else 80)
                if policy.blocked(host):
                    raise EgressDenied("Host header destination denied")

        def do_CONNECT(self):
            host = "invalid"
            upstream = None
            active = False
            try:
                host, port = authority(self.path, 443)
                self.target_host_header()
                upstream = self.connect_target(host, port)
                with counter_lock:
                    counters["connections"] += 1
                    counters["active"] += 1
                active = True
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.wfile.flush()
                self.close_connection = True
                self.connection.settimeout(None)
                audit(host, "connected")
                while not stop.is_set():
                    ready, _, _ = select.select([self.connection, upstream], [], [], 1)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)
            except EgressDenied:
                self.blocked(host)
            except (OSError, ValueError):
                if not active:
                    self.reply(502, {"error": "Direct destination connection failed"})
            finally:
                if upstream:
                    upstream.close()
                if active:
                    with counter_lock:
                        counters["active"] -= 1

        def forward(self):
            if self.path == "/health" and self.command == "GET":
                return self.reply(200, self.health())
            if self.path == "/shutdown" and self.command == "POST":
                if self.headers.get("Authorization") != "Bearer " + token:
                    return self.reply(401, {"error": "Invalid control credential"})
                with counter_lock:
                    if counters["active"]:
                        return self.reply(409, {"error": "Egress connections still active"})
                self.reply(200, {"status": "stopping"})
                stop.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            host = "invalid"
            upstream = None
            active = False
            try:
                parsed = urlsplit(self.path)
                if parsed.scheme not in ("http", "https") or parsed.username is not None or parsed.password is not None or parsed.fragment:
                    raise EgressDenied("Invalid absolute proxy URL")
                host = normalize_host(parsed.hostname or "")
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                self.target_host_header()
                transfer = self.headers.get("Transfer-Encoding", "").lower().strip()
                lengths = self.headers.get_all("Content-Length", [])
                if (transfer and lengths) or len(lengths) > 1:
                    raise EgressDenied("Ambiguous HTTP body framing")
                if transfer and transfer != "chunked":
                    raise EgressDenied("Unsupported request transfer encoding")
                length = int(lengths[0]) if lengths else 0
                if length < 0:
                    raise EgressDenied("Invalid content length")
                if not 1 <= port <= 65535:
                    raise EgressDenied("Invalid destination port")
                upstream = self.connect_target(host, port)
                if parsed.scheme == "https":
                    upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=host)
                with counter_lock:
                    counters["connections"] += 1
                    counters["active"] += 1
                active = True
                target = parsed.path or "/"
                if parsed.query:
                    target += "?" + parsed.query
                connection_headers = {x.strip().lower() for x in self.headers.get("Connection", "").split(",")}
                lines = [f"{self.command} {target} HTTP/1.1"]
                for key, value in self.headers.items():
                    if key.lower() not in HOP_HEADERS | connection_headers | {"host"}:
                        lines.append(key + ": " + value)
                authority_host = "[" + host + "]" if ":" in host else host
                lines.extend([f"Host: {authority_host}:{port}", "Connection: close", "", ""])
                upstream.sendall("\r\n".join(lines).encode("latin-1"))
                if transfer:
                    while True:
                        line = self.rfile.readline(65537)
                        if not line.endswith(b"\r\n"):
                            raise OSError("Invalid chunk")
                        size = int(line.split(b";", 1)[0].strip(), 16)
                        upstream.sendall(line)
                        if size == 0:
                            while True:
                                trailer = self.rfile.readline(65537)
                                upstream.sendall(trailer)
                                if trailer == b"\r\n":
                                    break
                            break
                        remaining = size + 2
                        while remaining:
                            data = self.rfile.read(min(65536, remaining))
                            if not data:
                                raise OSError("Truncated chunk")
                            upstream.sendall(data)
                            remaining -= len(data)
                else:
                    remaining = length
                    while remaining:
                        data = self.rfile.read(min(65536, remaining))
                        if not data:
                            raise OSError("Truncated request")
                        upstream.sendall(data)
                        remaining -= len(data)
                audit(host, "connected")
                self.close_connection = True
                while not stop.is_set():
                    data = upstream.recv(65536)
                    if not data:
                        break
                    self.connection.sendall(data)
            except EgressDenied:
                self.blocked(host)
            except (OSError, ValueError):
                if not active:
                    self.reply(502, {"error": "Direct destination connection failed"})
            finally:
                if upstream:
                    upstream.close()
                if active:
                    with counter_lock:
                        counters["active"] -= 1

        do_GET = forward
        do_POST = forward
        do_PUT = forward
        do_PATCH = forward
        do_DELETE = forward
        do_HEAD = forward
        do_OPTIONS = forward

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.egress_policy = policy
    server.egress_stop = stop
    return server


def serve(root, port=DEFAULT_PORT):
    server = create_server(root, port)
    print(f"Claude egress guard: http://127.0.0.1:{server.server_port} (direct sockets, proxy-aware clients only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.egress_stop.set()
        server.server_close()


def ensure(root, port=DEFAULT_PORT):
    root = Path(root).resolve()
    url = f"http://127.0.0.1:{port}"
    policy = load_policy(root)
    def health():
        result = _direct_open(url + "/health")
        if not isinstance(result, dict) or result.get("service") != "neuraldeep-claude-egress" or result.get("root_id") != _root_id(root):
            raise RuntimeError("Egress port is occupied by a different service")
        if result.get("policy_sha256") != policy.digest():
            raise RuntimeError("Running egress policy changed; stop the owned guard before restarting")
        return result
    try:
        return health()
    except urllib.error.HTTPError:
        raise RuntimeError("Egress port is occupied by a different HTTP service") from None
    except ValueError:
        raise RuntimeError("Egress port did not return a valid guard health response") from None
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ConnectionRefusedError):
            raise RuntimeError("Cannot verify the configured egress port") from None
    except ConnectionRefusedError:
        pass
    folder = root / ".local"
    folder.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    log_path = folder / "egress.log"
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    with log_path.open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "neuraldeep_claude.egress", "--root", str(root), "--port", str(port)], cwd=root, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
    for _ in range(100):
        try:
            result = health()
            path = folder / "egress-process.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump({"pid": process.pid, "port": port, "proxy_url": url}, handle)
            return result
        except (OSError, ValueError):
            if process.poll() is not None:
                raise RuntimeError("Egress guard failed to start; inspect .local/egress.log")
            time.sleep(0.05)
    raise RuntimeError("Egress guard startup timed out")


def guard_environment(root, source=None, port=DEFAULT_PORT):
    health = ensure(root, port)
    env = {k: v for k, v in (os.environ if source is None else source).items() if "proxy" not in k.lower()}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = health["proxy_url"]
    env["NO_PROXY"] = env["no_proxy"] = NO_PROXY_HOSTS
    env["NODE_USE_ENV_PROXY"] = "1"
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    serve(args.root, args.port)


if __name__ == "__main__":
    main()
