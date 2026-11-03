import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from neuraldeep_claude import catalog, gateway, protocol
from neuraldeep_claude.config import atomic_json, local_token

class GatewayTests(unittest.TestCase):
    def test_claude_prompt_limit_is_recognizable_during_streaming_and_json_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("NEURALDEEP_API_KEY_WALLET=unit-key\n")
            route = "nd/claude-haiku-5.5@wallet"
            atomic_json(root / ".local/catalog.json", {
                "models": {route: {"id": route, "upstream_id": "claude-haiku-5.5", "billing": "wallet"}},
                "aliases": {"claude-haiku-5.5": route},
            })
            ready = threading.Event()
            servers = []

            def make_server(address, handler):
                server = ThreadingHTTPServer(address, handler)
                servers.append(server)
                ready.set()
                return server

            provider_message = "Claude 5.5 does not support prompts over ~90k tokens through this API."
            provider_error = gateway.UpstreamError(400, json.dumps({"error": {"message": provider_message}}).encode())
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with patch.object(gateway, "ThreadingHTTPServer", side_effect=make_server), patch.object(
                gateway, "open_request", side_effect=provider_error,
            ), patch("builtins.print"):
                thread = threading.Thread(target=gateway.serve, args=(root, 0), daemon=True)
                thread.start()
                self.assertTrue(ready.wait(2))
                server = servers[0]
                self.addCleanup(server.server_close)
                base = f"http://127.0.0.1:{server.server_port}"
                try:
                    for stream in (True, False):
                        with self.subTest(stream=stream):
                            request = urllib.request.Request(base + "/v1/messages", data=json.dumps({
                                "model": route, "messages": [{"role": "user", "content": "test"}],
                                "max_tokens": 64, "stream": stream,
                            }).encode(), headers={"x-api-key": local_token(root)})
                            if stream:
                                with opener.open(request, timeout=2) as response:
                                    raw = response.read().decode()
                                self.assertIn("event: error\n", raw)
                                payload = json.loads(next(line[6:] for line in raw.splitlines() if line.startswith("data: ") and '"error"' in line))
                            else:
                                with self.assertRaises(urllib.error.HTTPError) as caught:
                                    opener.open(request, timeout=2)
                                with caught.exception as response:
                                    self.assertEqual(response.code, 400)
                                    payload = json.load(response)
                            self.assertEqual(payload["error"], {
                                "type": "invalid_request_error",
                                "message": "Prompt is too long. " + provider_message,
                            })
                finally:
                    server.shutdown()
                    thread.join(2)

    def test_live_loopback_auth_ping_before_provider_and_safe_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env").write_text("NEURALDEEP_API_KEY_SUBSCRIPTION=unit-key\n")
            atomic_json(root / ".local/catalog.json", {"refreshed_at": "2026-11-02", "models": {"nd/test@subscription": {"id": "nd/test@subscription", "upstream_id": "test", "billing": "subscription", "capabilities": {}, "limit": {"context": 100000, "output": 100}}}, "aliases": {"test": "nd/test@subscription"}, "limits": {"subscription": {"parallel_limit": 2}}})
            token = local_token(root)
            ready = threading.Event()
            release_provider = threading.Event()
            provider_waiting = threading.Event()
            captured = []
            def make_server(address, handler):
                server = ThreadingHTTPServer(address, handler)
                captured.append(server)
                ready.set()
                return server
            def upstream(*args, **kwargs):
                provider_waiting.set()
                if not release_provider.wait(3):
                    raise TimeoutError("Test did not release the delayed provider")
                response = io.BytesIO(b'data: {"choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\ndata: [DONE]\n\n')
                response.headers = {"Content-Type": "text/event-stream"}
                return response
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with patch.object(gateway, "ThreadingHTTPServer", side_effect=make_server), patch.object(gateway, "open_request", side_effect=upstream), patch.object(gateway, "PING_INTERVAL_SECONDS", 0.025), patch("builtins.print"):
                thread = threading.Thread(target=gateway.serve, args=(root, 0), daemon=True)
                thread.start()
                self.assertTrue(ready.wait(2))
                base = "http://127.0.0.1:" + str(captured[0].server_port)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    opener.open(base + "/v1/models")
                self.assertEqual(caught.exception.code, 401)
                discovery = urllib.request.Request(base + "/v1/models", headers={"x-api-key": token})
                with opener.open(discovery) as response:
                    models = json.load(response)
                self.assertEqual(models["first_id"], catalog.gateway_alias("nd/test@subscription"))
                self.assertEqual(models["data"][0]["max_input_tokens"], 100000)
                self.assertFalse(models["data"][0]["supports_1m"])
                req = urllib.request.Request(base + "/v1/messages", data=json.dumps({"model": "test", "messages": [{"role": "user", "content": "OK"}], "max_tokens": 50, "stream": True}).encode(), headers={"x-api-key": token})
                with opener.open(req, timeout=2) as response:
                    first = response.readline()
                    self.assertEqual(first, b"event: ping\n")
                    self.assertTrue(provider_waiting.wait(1))
                    self.assertFalse(release_provider.is_set())
                    shutdown = urllib.request.Request(base + "/_neuraldeep/shutdown", data=b"{}", headers={"x-api-key": token})
                    with self.assertRaises(urllib.error.HTTPError) as busy:
                        opener.open(shutdown)
                    self.assertEqual(busy.exception.code, 409)
                    release_provider.set()
                    remaining = response.read()
                    self.assertIn(b"message_stop", remaining)
                    self.assertIn(b'"input_tokens": 3', remaining)
                # Handler cleanup completes after the last stream bytes.
                for _ in range(50):
                    with opener.open(base + "/health") as response:
                        if json.load(response)["active_requests"] == 0: break
                    time.sleep(0.01)
                with opener.open(shutdown) as response:
                    self.assertEqual(response.status, 200)
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_empty_final_is_failure_but_token_exhaustion_is_explicit(self):
        empty = {"choices": [{"message": {"reasoning_content": "hidden reasoning", "content": ""}, "finish_reason": "stop"}]}
        with self.assertRaises(protocol.EmptyResponseError): protocol.from_openai(empty, "test")
        with self.assertRaises(protocol.EmptyResponseError): list(protocol.stream_openai([{"choices": [{"delta": {"reasoning_content": "reason"}, "finish_reason": "stop"}]}], "test"))
        empty["choices"][0]["finish_reason"] = "length"
        self.assertEqual(protocol.from_openai(empty, "test")["stop_reason"], "max_tokens")

if __name__ == "__main__": unittest.main()
