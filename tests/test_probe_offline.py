import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts/probe-offline.py"
SPEC = importlib.util.spec_from_file_location("probe_offline", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_dry_run_never_executes(self):
        with patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main([]), 0)
        execute.assert_not_called()
        self.assertIn('"execute": false', output.getvalue())

    def test_fixed_port_frame_rejects_other_destinations(self):
        for port in (8787, 18790):
            self.assertEqual(probe.parse_port(b"ND" + struct.pack("!H", port)), port)
        for frame in (b"", b"ND", b"NO" + struct.pack("!H", 8787), b"ND" + struct.pack("!H", 20171), b"ND" + struct.pack("!H", 8790), b"ND" + struct.pack("!H", 443)):
            with self.assertRaises(ValueError):
                probe.parse_port(frame)

    @unittest.skipUnless(hasattr(probe.socketserver, "ThreadingUnixStreamServer"), "Unix-domain server unavailable on this platform")
    def test_invalid_bridge_never_connects_host_port(self):
        with tempfile.TemporaryDirectory(prefix="nd-probe-") as temp:
            path = Path(temp) / "bridge.sock"
            with patch.object(probe.socket, "create_connection") as connect:
                server, pool, thread = probe.host_bridge(path, [])
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.connect(str(path))
                        client.sendall(b"ND" + struct.pack("!H", 20171))
                        client.settimeout(2)
                        self.assertEqual(client.recv(1), b"")
                    connect.assert_not_called()
                finally:
                    pool.close(); server.shutdown(); server.server_close(); thread.join(2)

    def test_unsupported_platform_execute_fails_before_native_or_bridge(self):
        with patch.object(probe.sys, "platform", "win32"), patch.object(probe, "execute") as execute, contextlib.redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as result:
                probe.main(["--execute"])
        self.assertEqual(result.exception.code, 2)
        self.assertIn("requires Linux bwrap", error.getvalue())
        execute.assert_not_called()

    def test_design_dry_run_reports_its_actual_scope_on_any_platform(self):
        with patch.object(probe.sys, "platform", "darwin"), patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(["--design"]), 0)
        self.assertIn('"mode": "design"', output.getvalue())
        self.assertIn('"execution_platform": "linux only"', output.getvalue())
        execute.assert_not_called()

    def test_tool_search_dry_run_omits_service_tools_and_never_executes(self):
        with patch.object(probe.sys, "platform", "win32"), patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(["--tool-search"]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["mode"], "tool-search")
        self.assertIn("stdio MCP echo", plan["tools"])
        execute.assert_not_called()

    def test_host_pricing_dry_run_is_explicit_and_never_executes(self):
        with patch.object(probe, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(["--tool-search", "--host-pricing"]), 0)
        self.assertTrue(json.loads(output.getvalue())["experimental_host_pricing"])
        execute.assert_not_called()

    def test_experimental_host_pricing_uses_only_raw_cli_ids_with_real_four_rate_mapping(self):
        from neuraldeep_claude import catalog, pricing
        raw = "nd/model@wallet~high"
        alias = catalog.gateway_alias(raw)
        report = {"models": [{"name": alias, "inputPerMtok": 1.2, "outputPerMtok": 3.4,
                  "cacheReadPerMtok": 0.12, "cacheWritePerMtok": 0}], "fx": {"source": "fixture"}, "omitted": []}
        with patch.object(catalog, "load", return_value={}), patch.object(catalog, "picker", return_value=[{"model": raw}]), patch.object(pricing, "desktop_report", return_value=report):
            parent, receipt = probe.experimental_host_pricing(Path("unused"))
        self.assertEqual(parent, {"modelPricing": {"overrides": {raw: {"input": 1.2, "output": 3.4, "cacheRead": 0.12, "cacheWrite": 0}}}})
        self.assertTrue(receipt["genuine_admin_policy_precedes_host"])
        self.assertNotIn(alias, json.dumps(parent))

    def test_experimental_pricing_requires_configured_basis_and_nonzero_usage(self):
        final = {"total_cost_usd": 0, "modelUsage": {"model": {
            "costBasis": "managed", "costUSD": 0, "inputTokens": 100, "outputTokens": 1}}}
        good = probe.experimental_pricing_evidence(final, "model")
        self.assertTrue(good["model_pricing_configured"])
        self.assertTrue(good["subscription_incremental_cost_zero"])
        self.assertTrue(good["nonzero_model_usage"])
        final["modelUsage"]["model"]["costBasis"] = "unknown"
        self.assertFalse(probe.experimental_pricing_evidence(final, "model")["model_pricing_configured"])
        self.assertFalse(probe.experimental_pricing_evidence(final, "missing")["model_pricing_configured"])

    def test_echo_fixture_executes_only_local_declared_tool(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "other", "arguments": {"marker": "bad"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "echo_marker", "arguments": {"marker": "wanted"}}}]
        with tempfile.TemporaryDirectory(prefix="nd-probe-") as temp:
            path = Path(temp) / "echo-audit.jsonl"
            with patch.object(probe.sys, "stdin", io.StringIO("\n".join(json.dumps(row) for row in requests))), contextlib.redirect_stdout(io.StringIO()) as output, patch.object(probe.socket, "create_connection") as network:
                self.assertEqual(probe.local_mcp_echo(path), 0)
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(rows[0]["result"]["protocolVersion"], "2025-03-26")
            self.assertEqual(rows[1]["result"]["tools"][0]["name"], "echo_marker")
            self.assertTrue(rows[2]["result"]["isError"])
            self.assertEqual(rows[3]["result"]["content"][0]["text"], "ECHO_MARKER=wanted")
            self.assertEqual(probe.json_lines(path), [{"tool": "echo_marker", "marker": "wanted"}])
            network.assert_not_called()

    def test_tool_search_evidence_requires_reference_before_actual_invocation(self):
        tool = "mcp__nd-local-probe__echo_marker"
        search = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "search-1", "name": "ToolSearch", "input": {"query": "echo"}}]}}
        reference = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "search-1", "content": [{"type": "tool_reference", "tool_name": tool}]}]}}
        call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "call-1", "name": tool, "input": {"marker": "wanted"}}]}}
        audit = [{"tool": "echo_marker", "marker": "wanted"}]
        good = probe.tool_search_evidence([search, reference, call], audit, tool, "wanted")
        self.assertTrue(all(good[key] for key in ("native_tool_search_invoked", "native_tool_reference_received", "native_echo_invoked_after_discovery", "local_echo_audit_matches")))
        bad = probe.tool_search_evidence([search, call, reference], [], tool, "wanted")
        self.assertFalse(bad["native_echo_invoked_after_discovery"])
        self.assertFalse(bad["local_echo_audit_matches"])
        claimed = probe.tool_search_evidence([{"type": "result", "result": "TOOL_SEARCH_OK wanted"}], audit, tool, "wanted")
        self.assertFalse(claimed["native_tool_search_invoked"])
        self.assertFalse(claimed["native_tool_reference_received"])

    def test_nonblocking_public_connection_is_not_a_safe_failure(self):
        trace = '1 1.0 connect(9, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("203.0.113.1")}, 16) = -1 EINPROGRESS (Operation now in progress)\n'
        summary = probe.parse_trace(trace)
        self.assertEqual(len(summary["unresolved_nonloopback"]), 1)
        self.assertEqual(summary["failed_nonloopback"], [])

    def test_trace_separates_public_success_loopback_and_unreachable(self):
        trace = '\n'.join([
            '1 1.0 connect(9, {sa_family=AF_INET, sin_port=htons(8787), sin_addr=inet_addr("127.0.0.1")}, 16) = 0',
            '1 1.0 connect(9, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("203.0.113.1")}, 16) = -1 ENETUNREACH (Network is unreachable)',
            '1 1.0 connect(9, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("198.51.100.1")}, 16) = 0',
        ])
        summary = probe.parse_trace(trace)
        self.assertEqual(len(summary["successful_nonloopback"]), 1)
        self.assertEqual(summary["enetwork_unreachable"], 1)

    def test_inner_refuses_host_namespace_before_any_cli(self):
        with tempfile.TemporaryDirectory(prefix="nd-probe-") as temp:
            path = Path(temp) / "inside.json"
            probe.write_json(path, {"host_netns": "same", "ports": [8787, 18790]})
            with patch.object(probe.os, "readlink", return_value="same"), patch.object(probe.subprocess, "call") as native:
                with self.assertRaisesRegex(RuntimeError, "outside the new"):
                    probe.inside(path)
            native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
