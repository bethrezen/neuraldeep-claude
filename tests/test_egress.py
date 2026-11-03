import http.client
import json
import os
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from neuraldeep_claude import egress


class Origin(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.server.received.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(int(self.headers.get("Content-Length", "0")))})
        body = b"direct-origin-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = do_POST


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(65536)
            if not data: return
            self.request.sendall(data)


class EgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proxy = egress.create_server(self.root, 0)
        self.thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server, self.proxy)

    def close_server(self, server):
        if hasattr(server, "egress_stop"): server.egress_stop.set()
        server.shutdown()
        server.server_close()

    def connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_port, timeout=3)
        self.addCleanup(conn.close)
        return conn

    def health(self):
        conn = self.connection()
        conn.request("GET", "/health")
        return json.loads(conn.getresponse().read())

    def origin(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
        server.received = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(self.close_server, server)
        return server

    def test_denied_domains_never_reach_dns(self):
        policy = egress.EgressPolicy()
        names = ["api.anthropic.com", "API.ANTHROPIC.COM.", "claude.ai", "platform.claude.com", "fonts.frame.claudeusercontent.com", "x.claudemcpcontent.com", "beacon.claude-ai.staging.ant.dev", "storage.googleapis.com", "http-intake.logs.us5.datadoghq.com", "api.statsig.com", "claude.googleapis.com", "claude.fedstart.com", "o1158394.ingest.us.sentry.io", "another.ingest.sentry.io"]
        with mock.patch.object(egress.socket, "getaddrinfo") as resolve:
            for name in names:
                with self.subTest(name=name), self.assertRaises(egress.EgressDenied):
                    policy.addresses(name, 443)
            resolve.assert_not_called()
        self.assertFalse(policy.blocked("notanthropic.com"))
        self.assertFalse(policy.blocked("api.anthropic.com.example.test"))

    def test_literal_ip_and_legacy_spelling_denied_before_dns(self):
        with mock.patch.object(egress.socket, "getaddrinfo") as resolve:
            for host in ["160.79.104.10", "[::ffff:160.79.104.10]".strip("[]"), "203.0.113.9", "0xA04F680A", "2689558538"]:
                with self.subTest(host=host), self.assertRaises(egress.EgressDenied):
                    egress.EgressPolicy().addresses(host, 443)
            resolve.assert_not_called()

    def test_resolved_network_and_canonical_alias_denied(self):
        policy = egress.EgressPolicy(blocked_ip_networks=["203.0.113.0/24"])
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 443))]
        with mock.patch.object(egress.socket, "getaddrinfo", return_value=addresses), self.assertRaises(egress.EgressDenied):
            policy.addresses("allowed.example", 443)
        addresses[0] = (socket.AF_INET, socket.SOCK_STREAM, 6, "api.anthropic.com", ("127.0.0.1", 443))
        with mock.patch.object(egress.socket, "getaddrinfo", return_value=addresses), self.assertRaises(egress.EgressDenied):
            policy.addresses("alias.example", 443)

    def test_http_denial_no_dns_no_path_or_credentials_log(self):
        client = self.connection()
        client.connect()
        with mock.patch.object(egress.socket, "getaddrinfo") as resolve:
            client.request("GET", "http://api.anthropic.com/private?secret=do-not-log", headers={"Proxy-Authorization": "Basic private-credential"})
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            resolve.assert_not_called()
        record = (self.root / ".local/egress-events.jsonl").read_text()
        self.assertNotIn("do-not-log", record)
        self.assertNotIn("private-credential", record)
        self.assertNotIn("private", record)
        self.assertEqual(json.loads(record), {"host": "api.anthropic.com", "status": "blocked"})
        self.assertEqual(self.health()["connections"], 0)

    def test_connect_denied_before_dns(self):
        client = self.connection()
        client.connect()
        with mock.patch.object(egress.socket, "getaddrinfo") as resolve:
            client.request("CONNECT", "api.anthropic.com:443")
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            resolve.assert_not_called()
        self.assertEqual(self.health()["connections"], 0)

    def test_http_relay_direct_body_and_strip_proxy_credential(self):
        origin = self.origin()
        client = self.connection()
        payload = b"x" * 180000
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:20171", "HTTPS_PROXY": "http://127.0.0.1:20171"}):
            client.request("POST", f"http://127.0.0.1:{origin.server_port}/path?q=value", body=payload,
                headers={"Proxy-Authorization": "Basic private-credential", "Content-Type": "application/octet-stream"})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"direct-origin-ok")
        self.assertEqual(origin.received[0]["body"], payload)
        self.assertNotIn("Proxy-Authorization", origin.received[0]["headers"])
        self.assertEqual(origin.received[0]["path"], "/path?q=value")

    def test_bad_host_header_denied_without_origin_connection(self):
        origin = self.origin()
        client = self.connection()
        client.request("GET", f"http://127.0.0.1:{origin.server_port}/", headers={"Host": "api.anthropic.com"})
        response = client.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        self.assertEqual(origin.received, [])
        self.assertEqual(self.health()["connections"], 0)

    def test_connect_tunnel_echo_and_busy_shutdown(self):
        origin = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
        origin.daemon_threads = True
        threading.Thread(target=origin.serve_forever, daemon=True).start()
        self.addCleanup(self.close_server, origin)
        stream = socket.create_connection(("127.0.0.1", self.proxy.server_port), timeout=3)
        self.addCleanup(stream.close)
        port = origin.server_address[1]
        stream.sendall(f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        headers = b""
        while not headers.endswith(b"\r\n\r\n"): headers += stream.recv(1)
        self.assertIn(b"200 Connection Established", headers)
        stream.sendall(b"direct-tunnel-ok")
        self.assertEqual(stream.recv(100), b"direct-tunnel-ok")
        client = self.connection()
        token = (self.root / ".local/egress-control-token").read_text()
        client.request("POST", "/shutdown", headers={"Authorization": "Bearer " + token})
        response = client.getresponse()
        self.assertEqual(response.status, 409)
        response.read()
        stream.close()

    def test_protected_shared_relay_and_proxy_loop_never_connected(self):
        for port in [20171, self.proxy.server_port]:
            client = self.connection()
            client.request("CONNECT", f"127.0.0.1:{port}")
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        self.assertEqual(self.health()["connections"], 0)

    def test_guard_env_is_child_only_and_nd_bypass(self):
        original = {"HTTP_PROXY": "http://127.0.0.1:20171", "https_proxy": "old", "NO_PROXY": "anthropic.com", "KEEP": "yes"}
        with mock.patch.object(egress, "ensure", return_value={"proxy_url": "http://127.0.0.1:18790"}):
            env = egress.guard_environment(self.root, original)
        self.assertEqual(original["HTTP_PROXY"], "http://127.0.0.1:20171")
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            self.assertEqual(env[key], "http://127.0.0.1:18790")
        self.assertNotIn("anthropic.com", env["NO_PROXY"])
        self.assertIn(".neuraldeep.ru", env["NO_PROXY"])
        self.assertEqual(env["KEEP"], "yes")

    def test_health_and_shutdown_auth_are_loopback_only(self):
        health = self.health()
        self.assertEqual(self.proxy.server_address[0], "127.0.0.1")
        self.assertTrue(health["proxy_aware_only"])
        self.assertFalse(health["os_network_sandbox"])
        client = self.connection()
        client.request("POST", "/shutdown")
        response = client.getresponse()
        self.assertEqual(response.status, 401)
        response.read()

    def test_ensure_foreign_service_never_spawns_or_takes_over(self):
        with mock.patch.object(egress, "_direct_open", return_value={"service": "unrelated"}), mock.patch.object(egress.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "different service"):
                egress.ensure(self.root)
            spawn.assert_not_called()

    def test_health_never_follows_redirect_to_external_host(self):
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "https://api.anthropic.com/forbidden")
                self.send_header("Content-Length", "0")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(self.close_server, server)
        real_resolve = socket.getaddrinfo
        seen = []
        def resolve(host, *args, **kwargs):
            seen.append(host)
            if host != "127.0.0.1":
                raise AssertionError("No external DNS permitted in health probe")
            return real_resolve(host, *args, **kwargs)
        with mock.patch.object(egress.socket, "getaddrinfo", side_effect=resolve):
            with self.assertRaises(egress.urllib.error.HTTPError) as caught:
                egress._direct_open(f"http://127.0.0.1:{server.server_port}/health")
            self.assertEqual(caught.exception.code, 302)
        self.assertNotIn("api.anthropic.com", seen)

    def test_authority_validates_credentials_and_ports(self):
        for value in ["user:pass@api.anthropic.com:443", "host:0", "host:99999", "host/path", "host:443?query", "host\t:443"]:
            with self.subTest(value=value), self.assertRaises(egress.EgressDenied):
                egress.authority(value, 443)


if __name__ == "__main__": unittest.main()
