"""Service transport contract tests. Never call live or paid APIs."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from neuraldeep_claude import services as s


class Response:
    def __init__(self, data=b'{"ok":true}', mime="application/json", status=200):
        self.io = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Type": mime}

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, *args): return self.io.read(*args)


class Opener:
    def __init__(self, response): self.response, self.calls = response, []
    def open(self, request, **kw):
        self.calls.append((request, kw))
        if isinstance(self.response, Exception): raise self.response
        return self.response


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".env").write_text("NEURALDEEP_API_KEY_SUBSCRIPTION=subscription-secret\nNEURALDEEP_API_KEY_WALLET=wallet-secret\n", encoding="utf-8")

    def tearDown(self): self.temp.cleanup()

    def invoke(self, group, name, args, response=None):
        opener = Opener(response or Response())
        with patch.object(s.urllib.request, "build_opener", return_value=opener) as build:
            result = s.call_tool(self.root, group, name, args)
        self.assertIsInstance(build.call_args.args[0], s.urllib.request.ProxyHandler)
        self.assertEqual(build.call_args.args[0].proxies, {})
        return result, opener.calls

    def test_defaults_and_explicit_wallet(self):
        _, calls = self.invoke("search", "web_search", {"query": "тест"})
        self.assertEqual(calls[0][0].headers["Authorization"], "Bearer subscription-secret")
        self.assertEqual(json.loads(calls[0][0].data), {"query": "тест"})
        _, calls = self.invoke("search", "web_search", {"query": "тест", "billing": "wallet"})
        self.assertEqual(calls[0][0].headers["Authorization"], "Bearer wallet-secret")

    def test_disabled_avatar_is_hidden_and_rejected_without_affecting_other_image_tools(self):
        (self.root / "config").mkdir()
        (self.root / "config/service-policy.json").write_text('{"disabled_tools":{"image_avatar":"provider422"}}')
        server = s.MCPServer(self.root, "images")
        listed = server.handle({"id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertNotIn("image_avatar", names)
        self.assertIn("image_generate", names)
        self.assertIn("image_edit", names)
        with patch.object(s.urllib.request, "build_opener") as network:
            result = server.handle({"id": 2, "method": "tools/call", "params": {"name": "image_avatar"}})
        network.assert_not_called()
        self.assertTrue(result["result"]["isError"])
        self.assertIn("disabled", result["result"]["content"][0]["text"])
        s.set_tools(self.root, ["image_avatar"], True)
        names = {tool["name"] for tool in server.handle({"id": 3, "method": "tools/list"})["result"]["tools"]}
        self.assertIn("image_avatar", names)
        self.assertTrue(s.service_state(self.root)["images"])

    def test_quota_error_is_not_retried_or_wallet_fallback(self):
        error = urllib.error.HTTPError("https://api.neuraldeep.ru/v1/search/web", 429, "quota", {"Retry-After": "60"}, io.BytesIO(b'{"detail":"quota exhausted"}'))
        opener = Opener(error)
        with patch.object(s.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(s.ServiceError, "429.*quota.*60"):
                s.call_tool(self.root, "search", "web_search", {"query": "x"})
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][0].headers["Authorization"], "Bearer subscription-secret")

    def test_disabled_service_hides_and_rejects(self):
        s.set_services(self.root, ["images"], False)
        server = s.MCPServer(self.root, "images")
        self.assertEqual(server.handle({"id": 1, "method": "tools/list"})["result"]["tools"], [])
        with self.assertRaisesRegex(s.ServiceError, "disabled"):
            s.call_tool(self.root, "images", "image_generate", {"prompt": "cat"})
        config = s.mcp_config(self.root)
        self.assertNotIn("neuraldeep-images", config["mcpServers"])
        s.set_services(self.root, ["images"], True)
        self.assertIn("neuraldeep-images", s.mcp_config(self.root)["mcpServers"])

    def test_binary_and_pending_are_distinguished(self):
        result, _ = self.invoke("images", "image_result", {"task_id": "safe/id"}, Response(b"PNGDATA", "image/png"))
        self.assertEqual(Path(result["path"]).read_bytes(), b"PNGDATA")
        self.assertTrue(Path(result["path"]).is_absolute())
        pending, _ = self.invoke("images", "image_result", {"task_id": "t"}, Response(b"", "image/png", 202))
        self.assertEqual(pending["status"], "pending")
        self.assertNotIn("path", pending)

    def test_speechcore_export_preserves_requested_extension(self):
        result, calls = self.invoke("speechcore", "speechcore_export", {"task_id": "task", "format": "srt"}, Response(b"1\n00:00:00,000 --> 00:00:01,000\ntest", "text/plain"))
        self.assertEqual(Path(result["path"]).suffix, ".srt")
        self.assertEqual(calls[0][0].full_url, "https://speechcore.neuraldeep.ru/api/files/srt/task")

    def test_path_parameters_are_encoded(self):
        _, calls = self.invoke("ocr", "ocr_result", {"job_id": "x/../a?z=1", "format": "markdown"})
        self.assertEqual(calls[0][0].full_url, "https://api.neuraldeep.ru/v1/ocr/jobs/x%2F..%2Fa%3Fz%3D1/result?format=markdown")

    def test_file_multipart_streaming_matches_length(self):
        p = self.root / "речь.wav"
        p.write_bytes(b"WAVDATA" * 1000)
        _, calls = self.invoke("transcription", "transcribe", {"file_path": str(p), "model": "whisper-1", "parameters": {"timestamp_granularities[]": ["word"], "response_format": "verbose_json"}})
        request = calls[0][0]
        self.assertNotIsInstance(request.data, bytes)
        blob = b"".join(request.data)
        self.assertEqual(len(blob), int(request.headers["Content-length"]))
        self.assertIn(b'name="file"', blob)
        self.assertIn(b'name="timestamp_granularities[]"', blob)
        self.assertIn(p.read_bytes(), blob)

    def test_multiple_files_and_options(self):
        p = self.root / "a.jpg"
        p.write_bytes(b"JPEG")
        _, calls = self.invoke("images", "image_edit", {"image_paths": [str(p), str(p)], "prompt": "change", "options": {"transparent": True}})
        blob = b"".join(calls[0][0].data)
        self.assertEqual(blob.count(b'name="images"'), 2)
        self.assertIn(b'{"transparent": true}', blob)

    def test_speechcore_options_go_in_query(self):
        p = self.root / "a.wav"
        p.write_bytes(b"WAV")
        _, calls = self.invoke("speechcore", "speechcore_upload", {"file_path": str(p), "diarize": True, "diarize_max_speakers": 6, "parameters": {"future_flag": True}})
        req = calls[0][0]
        self.assertIn("speechcore.neuraldeep.ru/api/upload?", req.full_url)
        self.assertIn("diarize=true", req.full_url)
        self.assertIn("diarize_max_speakers=6", req.full_url)
        self.assertIn("future_flag=true", req.full_url)
        self.assertNotIn(b'name="diarize"', b"".join(req.data))

    def test_drift_requires_own_token(self):
        with patch.dict(s.os.environ, {}, clear=True):
            with self.assertRaisesRegex(s.ServiceError, "NEURALDEEP_DRIFT_TOKEN"):
                s.call_tool(self.root, "drift", "drift_ask", {"prompt": "test"})
        with (self.root / ".env").open("a") as f: f.write("NEURALDEEP_DRIFT_TOKEN=dft-secret\n")
        _, calls = self.invoke("drift", "drift_ask", {"prompt": "Latest prompt", "conversation_id": 123})
        self.assertEqual(calls[0][0].headers["Authorization"], "Bearer dft-secret")
        body = json.loads(calls[0][0].data)
        self.assertEqual(body["messages"], [{"role": "user", "content": "Latest prompt"}])
        self.assertFalse(body["stream"])

    def test_mcp_protocol_and_errors(self):
        server = s.MCPServer(self.root, "search")
        init = server.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(server.handle({"method": "notifications/initialized"}))
        self.assertIn("tools", server.handle({"id": 2, "method": "tools/list"})["result"])
        bad = server.handle({"id": 3, "method": "tools/call", "params": {"name": "missing"}})
        self.assertTrue(bad["result"]["isError"])
        out = io.StringIO()
        server.run(io.StringIO('{bad json}\n{"id":4,"method":"ping"}\n'), out)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})

    def test_all_groups_have_unique_described_tools(self):
        self.assertEqual(len(s.TOOLS), len(s.TOOL_BY_NAME))
        self.assertEqual(set(s.GROUPS), {tool.group for tool in s.TOOLS})
        for tool in s.TOOLS:
            self.assertGreater(len(tool.description), 20)
            schema = tool.public()["inputSchema"]
            self.assertTrue(set(schema["required"]) <= schema["properties"].keys())
            self.assertNotIn("key", schema["properties"])

    def test_errors_redact_keys(self):
        error = urllib.error.HTTPError("x", 400, "bad", {}, io.BytesIO(b'{"detail":"subscription-secret"}'))
        with patch.object(s.urllib.request, "build_opener", return_value=Opener(error)):
            with self.assertRaises(s.ServiceError) as cm:
                s.call_tool(self.root, "search", "web_search", {"query": "x"})
        self.assertNotIn("subscription-secret", str(cm.exception))

    def test_smoke_requires_explicit_execution(self):
        with patch.object(s, "call_tool") as call:
            report = s.smoke_services(self.root, billing="wallet", groups=["images"])
        call.assert_not_called()
        self.assertFalse(report["plan"]["execute"])
        self.assertEqual(report["plan"]["billing"], "wallet")

    def test_smoke_records_shape_failure_and_does_not_retry(self):
        with patch.object(s, "call_tool", return_value={"data": []}) as call:
            report = s.smoke_services(self.root, groups=["embeddings"], execute=True)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(report["checks"][-1]["status"], "fail")
        self.assertTrue((self.root / ".local/service-smoke.json").exists())

    def test_probe_calls_only_get_endpoints(self):
        with patch.object(s, "call_tool", return_value={"ok": True}) as call:
            report = s.probe_services(self.root)
        self.assertEqual(call.call_count, 13)
        for invocation in call.call_args_list:
            self.assertEqual(s.TOOL_BY_NAME[invocation.args[2]].method, "GET")
        self.assertEqual(report["probes"][-1]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
