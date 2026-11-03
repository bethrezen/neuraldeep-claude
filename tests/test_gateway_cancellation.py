"""Real loopback sockets: client abort must stop the provider, not just a counter."""
import contextlib
import functools
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from neuraldeep_claude import gateway, transport
from neuraldeep_claude.config import atomic_json, local_token


class _Provider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.accepted.set()
        if self.server.mode != "headers":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            self.server.headers_sent.set()
        self.connection.settimeout(0.025)
        try:
            while not self.server.release.is_set():
                try:
                    if self.connection.recv(1) == b"":
                        self.server.peer_closed.set()
                        return
                except socket.timeout:
                    continue
            if self.server.mode == "slow":
                self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"content":"SLOW_OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\ndata: [DONE]\n\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.server.peer_closed.set()
        finally:
            self.close_connection = True
            self.server.worker_done.set()


@contextlib.contextmanager
def _running_gateway(mode):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".env").write_text("NEURALDEEP_API_KEY_SUBSCRIPTION=unit-key\n")
        atomic_json(root / ".local/catalog.json", {
            "models": {"nd/test@subscription": {"id": "nd/test@subscription", "upstream_id": "test",
                "billing": "subscription", "capabilities": {}, "limit": {"output": 100}}},
            "aliases": {"test": "nd/test@subscription"},
            "limits": {"subscription": {"parallel_limit": 1}}})
        token = local_token(root)
        provider = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
        provider.daemon_threads = True
        provider.mode = mode
        for name in ("accepted", "headers_sent", "peer_closed", "release", "worker_done"):
            setattr(provider, name, threading.Event())
        provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
        provider_thread.start()
        ready = threading.Event()
        captured = []

        def make_server(address, handler):
            server = ThreadingHTTPServer(address, handler)
            captured.append(server)
            ready.set()
            return server

        direct = functools.partial(transport.open_request,
            base="http://127.0.0.1:" + str(provider.server_port))
        with patch.object(gateway, "ThreadingHTTPServer", side_effect=make_server), \
                patch.object(gateway, "open_request", side_effect=direct), \
                patch.object(gateway, "PING_INTERVAL_SECONDS", 0.025), patch("builtins.print"):
            thread = threading.Thread(target=gateway.serve, args=(root, 0), daemon=True)
            thread.start()
            if not ready.wait(2):
                raise RuntimeError("Local gateway did not start")
            try:
                yield root, token, captured[0], provider
            finally:
                provider.release.set()
                captured[0].shutdown()
                thread.join(2)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(2)


def _client(server, token):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request("POST", "/v1/messages", json.dumps({"model": "test", "messages": [
        {"role": "user", "content": "own cancellation fixture"}], "max_tokens": 50, "stream": True}),
        {"x-api-key": token, "Content-Type": "application/json"})
    response = connection.getresponse()
    if response.status != 200:
        raise AssertionError("Unexpected local response " + str(response.status))
    return connection, response


def _abort(connection, response):
    # response owns the socket once HTTPConnection observes Connection: close.
    # Explicit shutdown avoids depending on CPython object's finalization timing.
    response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    response.close()
    connection.close()


def _health(server):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:" + str(server.server_port) + "/health", timeout=2) as response:
        return json.load(response)


def _wait_idle(server):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if _health(server)["active_requests"] == 0:
            return True
        time.sleep(0.01)
    return False


class GatewayCancellationTests(unittest.TestCase):
    def _disconnect_case(self, mode, expected_phase):
        with _running_gateway(mode) as (root, token, server, provider):
            connection, response = _client(server, token)
            self.assertTrue(provider.accepted.wait(2))
            if mode != "headers":
                self.assertTrue(provider.headers_sent.wait(2))
            self.assertEqual(_health(server)["active_requests"], 1)
            _abort(connection, response)
            self.assertTrue(provider.peer_closed.wait(2), "Gateway left the actual provider socket open")
            self.assertTrue(provider.worker_done.wait(2), "Provider read worker did not terminate")
            self.assertTrue(_wait_idle(server), "Gateway request thread/semaphore did not unwind")
            events = [json.loads(line) for line in (root / ".local/gateway-events.jsonl").read_text().splitlines()]
            cancelled = [e for e in events if e["event"] == "cancelled"]
            self.assertEqual(len(cancelled), 1)
            self.assertEqual(cancelled[0]["reason"], "client_disconnect")
            self.assertEqual(cancelled[0]["phase"], expected_phase)
            finished = [e for e in events if e["event"] == "finished"]
            self.assertEqual(len(finished), 1)
            self.assertTrue(finished[0]["cancelled"])
            # With the provider-advertised limit of ONE, the next real request
            # must be accepted and complete, proving release beyond a counter.
            provider.mode = "slow"
            provider.release.set()
            again, result = _client(server, token)
            try:
                self.assertIn(b"SLOW_OK", result.read())
            finally:
                result.close()
                again.close()
            self.assertTrue(_wait_idle(server))

    def test_disconnect_cancels_blocked_sse_body_and_releases_slot(self):
        self._disconnect_case("body", "body")

    def test_disconnect_cancels_wait_for_provider_headers(self):
        self._disconnect_case("headers", "connect_or_headers")

    def test_connected_slow_stream_survives_multiple_keepalives(self):
        with _running_gateway("slow") as (root, token, server, provider):
            connection, response = _client(server, token)
            try:
                self.assertTrue(provider.headers_sent.wait(2))
                # More than five ping periods without ANY provider body data.
                time.sleep(0.16)
                self.assertEqual(_health(server)["active_requests"], 1)
                self.assertFalse(provider.peer_closed.is_set())
                self.assertFalse(provider.worker_done.is_set())
                provider.release.set()
                output = response.read()
                self.assertGreaterEqual(output.count(b"event: ping"), 3)
                self.assertIn(b"SLOW_OK", output)
                self.assertIn(b"message_stop", output)
            finally:
                response.close()
                connection.close()
            self.assertTrue(_wait_idle(server))
            events = [json.loads(line) for line in (root / ".local/gateway-events.jsonl").read_text().splitlines()]
            self.assertFalse(any(e["event"] == "cancelled" for e in events))


if __name__ == "__main__":
    unittest.main()
