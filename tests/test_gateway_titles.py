"""Loopback HTTP acceptance of explicit native Desktop title-helper routing.

The upstream provider is always mocked. These tests exercise authentication,
request translation, routing, response identity and privacy-safe metrics through
the real gateway HTTP handler, rather than calling the matcher directly.
"""
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from neuraldeep_claude import catalog, gateway, title_helpers
from neuraldeep_claude.config import atomic_json, local_token


class GatewayTitleRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = "nd/qwen3.8-27b@subscription"
        self.helper = "nd/qwen3.6-35b-a3b-noreason@subscription"
        self.helper_wallet = self.helper.replace("@subscription", "@wallet")
        (self.root / ".env").write_text(
            "NEURALDEEP_API_KEY_SUBSCRIPTION=unit-subscription-key\n"
            "NEURALDEEP_API_KEY_WALLET=unit-wallet-key\n")
        main = {"id": self.main, "upstream_id": "qwen3.8-27b", "billing": "subscription",
                "capabilities": {"reasoning": True, "tools": True},
                "efforts": ["low", "medium", "xhigh"], "default_effort": "xhigh",
                "limit": {"context": 262144, "output": 32000}}
        helper = {"id": self.helper, "upstream_id": "qwen3.6-35b-a3b-noreason", "billing": "subscription",
                  "capabilities": {"reasoning": False, "tools": True}, "efforts": [],
                  "limit": {"context": 262144, "output": 32000}}
        atomic_json(self.root / ".local/catalog.json", {
            "refreshed_at": "2026-11-03", "models": {
                self.main: main, self.helper: helper,
                self.helper_wallet: helper | {"id": self.helper_wallet, "billing": "wallet"}},
            "aliases": {}, "limits": {"subscription": {"parallel_limit": 4}, "wallet": {"parallel_limit": 4}}})
        self.token = local_token(self.root)
        self.calls = []
        self.servers = []
        ready = threading.Event()

        def make_server(address, handler):
            server = ThreadingHTTPServer(address, handler)
            server.daemon_threads = True
            self.servers.append(server)
            ready.set()
            return server

        def upstream(method, endpoint, credential, body, **kwargs):
            self.calls.append({"method": method, "endpoint": endpoint, "credential": credential,
                               "body": json.loads(json.dumps(body))})
            response = io.BytesIO(json.dumps({
                "choices": [{"message": {"content": "<title>Проверка заголовка</title>"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }).encode())
            response.headers = {"Content-Type": "application/json"}
            return response

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gateway, "ThreadingHTTPServer", side_effect=make_server))
        self.stack.enter_context(patch.object(gateway, "open_request", side_effect=upstream))
        self.stack.enter_context(patch("builtins.print"))
        self.thread = threading.Thread(target=gateway.serve, args=(self.root, 0), daemon=True)
        self.thread.start()
        self.assertTrue(ready.wait(2), "Loopback gateway did not start")
        self.base = "http://127.0.0.1:" + str(self.servers[0].server_port)
        self.addCleanup(self.stop_gateway)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def stop_gateway(self):
        if self.servers:
            self.servers[0].shutdown()
            self.servers[0].server_close()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive(), "Loopback gateway did not stop")

    def configure_helper(self, selected):
        atomic_json(self.root / "config/helper-models.json", {"schema": 1, "desktop_title_model": selected})

    def native_body(self, kind="generic", model=None):
        template = title_helpers.TITLE_TEMPLATES[kind]
        description = "PRIVATE_TITLE_DESCRIPTION_7b98c26b: исправить параллельные тесты"
        return {"model": model or self.main, "max_tokens": 200,
                "system": title_helpers.TITLE_SYSTEM,
                "messages": [{"role": "user", "content": template["prefix"] + description + template["suffix"]}]}

    def post(self, body):
        request = urllib.request.Request(
            self.base + "/v1/messages", data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"x-api-key": self.token, "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def request_metrics(self):
        path = self.root / ".local/gateway-events.jsonl"
        return [event for line in (path.read_text().splitlines() if path.exists() else [])
                if (event := json.loads(line)).get("event") == "request"]

    def test_exact_native_templates_route_to_explicit_subscription_and_report_real_identity(self):
        self.configure_helper(self.helper)
        for kind in ("generic", "coding"):
            for original in (self.main, catalog.gateway_alias(self.main)):
                with self.subTest(kind=kind, original=original):
                    body = self.native_body(kind, original)
                    status, response = self.post(body)
                    self.assertEqual(status, 200, response)
                    self.assertEqual(response["model"], self.helper)
                    sent = self.calls[-1]
                    self.assertEqual(sent["credential"], "unit-subscription-key")
                    self.assertEqual(sent["body"]["model"], "qwen3.6-35b-a3b-noreason")
                    self.assertNotIn("reasoning_effort", sent["body"])
                    metric = self.request_metrics()[-1]
                    self.assertEqual(metric["model"], self.helper)
                    self.assertEqual(metric["requested_model"], original)
                    self.assertEqual(metric["helper_rule"], "desktop_title:" + kind)
        raw_metrics = (self.root / ".local/gateway-events.jsonl").read_text()
        self.assertNotIn("PRIVATE_TITLE_DESCRIPTION_7b98c26b", raw_metrics)
        self.assertNotIn(title_helpers.TITLE_SYSTEM, raw_metrics)
        for template in title_helpers.TITLE_TEMPLATES.values():
            self.assertNotIn(template["prefix"], raw_metrics)
            self.assertNotIn(template["suffix"], raw_metrics)

    def test_missing_file_missing_field_and_null_helper_preserve_original_model(self):
        variants = ("missing-file", "missing-field", "null")
        for variant in variants:
            with self.subTest(variant=variant):
                path = self.root / "config/helper-models.json"
                if variant == "missing-file":
                    path.unlink(missing_ok=True)
                elif variant == "missing-field":
                    atomic_json(path, {"schema": 1, "auto_permission_classifier": self.helper})
                else:
                    self.configure_helper(None)
                status, response = self.post(self.native_body())
                self.assertEqual(status, 200, response)
                self.assertEqual(response["model"], self.main)
                self.assertEqual(self.calls[-1]["body"]["model"], "qwen3.8-27b")
                self.assertNotEqual(self.request_metrics()[-1].get("helper_rule"), "desktop_title:generic")

    def test_explicit_effort_stream_field_and_normal_code_body_remain_on_main_model(self):
        self.configure_helper(self.helper)
        native = self.native_body()
        bodies = [native | {"output_config": {"effort": "medium"}}, native | {"stream": False},
                  {"model": self.main, "max_tokens": 200, "system": "You are a coding agent.",
                   "messages": [{"role": "user", "content": "Run tests and fix the code"}], "tools": []}]
        for body in bodies:
            with self.subTest(body=body):
                status, response = self.post(body)
                self.assertEqual(status, 200, response)
                self.assertEqual(response["model"], self.main)
                self.assertEqual(self.calls[-1]["body"]["model"], "qwen3.8-27b")
                self.assertFalse(self.request_metrics()[-1].get("helper_rule", "").startswith("desktop_title:"))
        status, response = self.post(native | {"output_config": {"effort": "medium"}})
        self.assertEqual(status, 200, response)
        self.assertEqual(self.calls[-1]["body"]["reasoning_effort"], "medium")

    def test_invalid_wallet_or_missing_helper_fails_before_provider_without_fallback(self):
        for selected in (self.helper_wallet, "nd/missing-title-model@subscription"):
            with self.subTest(selected=selected):
                self.configure_helper(selected)
                before = len(self.calls)
                status, response = self.post(self.native_body("coding"))
                self.assertEqual(status, 400, response)
                self.assertEqual(response["type"], "error")
                self.assertEqual(response["error"]["type"], "invalid_request_error")
                self.assertEqual(len(self.calls), before)

    def test_invalid_helper_does_not_intercept_an_ordinary_code_request(self):
        self.configure_helper(self.helper_wallet)
        status, response = self.post({"model": self.main, "max_tokens": 200,
                                      "messages": [{"role": "user", "content": "Explain a unit test"}]})
        self.assertEqual(status, 200, response)
        self.assertEqual(response["model"], self.main)
        self.assertEqual(self.calls[-1]["body"]["model"], "qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
