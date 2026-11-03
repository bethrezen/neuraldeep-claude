#!/usr/bin/env python3
"""Dry-run-first native Desktop-engine Auto classifier/handoff acceptance.

Runs the genuine installed Desktop Code engine in a private CLI profile. The
model under test classifies real native Auto actions and background-agent
handoffs; no safety prompt, rule, stage or timeout is modified. This is a native
SDK/CLI diagnostic, not an interactive Desktop UI session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuraldeep_claude import catalog, desktop_runtime, protocol
from neuraldeep_claude.config import atomic_json, clean_environment, source_revision
from neuraldeep_claude.helper_models import CLASSIFIER_ENV
from neuraldeep_claude.integration import active_port, build_settings
from neuraldeep_claude.transport import request

CANDIDATE = "nd/qwen3.6-35b-a3b-noreason@subscription"
EXPECTED_VERSION = "2.1.309"
_SPEC = importlib.util.spec_from_file_location("nd_classifier_stream_probe", ROOT / "scripts/probe-claude.py")
stream_probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stream_probe)


def plan():
    return {"execute": False, "candidate": CANDIDATE, "billing": "subscription",
            "native_engine": EXPECTED_VERSION, "permission_mode": "auto",
            "actions": ["one safe read-only Python Bash command", "two background agents restricted to Read", "native background handback notifications"],
            "worker_model": CANDIDATE, "product_main_model_changed": False,
            "safety_rules_modified": False, "classifier_timeouts_modified": False,
            "network_filter": False, "private_cli_profile": True,
            "scope": "genuine Desktop Code engine via native CLI; not Desktop UI; native Auto policy with a diagnostic fixture, not a replay of the old Desktop payload",
            "message": "Dry run. Add --execute to consume subscription inference quota."}


def json_lines(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def content_text(content):
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content or [] if isinstance(block, dict))


def flow_evidence(timed_events, debug):
    events = [item.get("event", item) for item in timed_events]
    init = next((event for event in events if event.get("subtype") == "init"), {})
    calls, results, finals, notifications = [], [], [], []
    for event in events:
        if event.get("type") == "assistant":
            calls.extend(block for block in event.get("message", {}).get("content", [])
                         if isinstance(block, dict) and block.get("type") == "tool_use")
        if event.get("type") == "user":
            content = event.get("message", {}).get("content", [])
            if isinstance(content, list):
                results.extend(block for block in content if isinstance(block, dict) and block.get("type") == "tool_result")
        if event.get("type") == "result":
            finals.append(event)
        if event.get("subtype") == "task_notification":
            notifications.append(event)
    background = [call for call in calls if call.get("name") in ("Agent", "Task")
                  and call.get("input", {}).get("run_in_background") is True]
    outputs = [call for call in calls if call.get("name") == "TaskOutput"]
    result_texts = [content_text(result.get("content")) for result in results]
    # Completion notifications may cause additional result records after the
    # requested answer. They must not hide the main turn's completed result.
    final = next((row for row in finals if "CLASSIFIER_FLOW_OK" in content_text(row.get("result", ""))), finals[-1] if finals else {})
    final_text = content_text(final.get("result", ""))
    warnings = []
    native_warning_lines = "\n".join(line for line in debug.splitlines()
                                     if any(tag in line for tag in ("[WARN]", "[ERROR]", "[auto-mode]")))
    for text in result_texts + [final_text, native_warning_lines]:
        for line in text.splitlines():
            lowered = line.lower()
            if ("safety classifier" in lowered and "unavailable" in lowered
                    or "handoff classifier unavailable" in lowered
                    or "subagent's work is unreviewed" in lowered
                    or "classifier" in lowered and any(word in lowered for word in ("timeout", "timed out", "parse_failure", "failed closed"))):
                warnings.append(line[:600])
    classified = [line for line in debug.splitlines() if "new action being classified:" in line]
    handoff_contexts = [line for line in classified if "id=none" in line or "tool=SubagentHandback " in line]
    delivered = [event for event in notifications if event.get("status") == "completed"
                 and event.get("handback") == "send" and isinstance(event.get("handback_report"), dict)]
    report_texts = [event["handback_report"].get("text", "") for event in delivered]
    errors = [result for result in results if result.get("is_error") is True]
    return {"native_version": init.get("claude_code_version"), "native_permission_mode": init.get("permissionMode"),
            "background_agent_calls": [{"id": call.get("id"), "name": call.get("name"), "input": call.get("input")} for call in background],
            "background_agents_requested": len(background), "TaskOutput_calls": len(outputs),
            "bash_marker_received": any("SAFE_BASH_OK=323" in text for text in result_texts),
            "review_a_received": any("REVIEW_A=323" in text for text in result_texts + [final_text]),
            "review_b_received": any("REVIEW_B=323" in text for text in result_texts + [final_text]),
            "native_classification_contexts": classified, "native_handoff_contexts": handoff_contexts,
            "classifier_warnings": list(dict.fromkeys(warnings)), "task_notifications": notifications,
            "delivered_handback_reports": delivered,
            "native_review_a_delivered": any("REVIEW_A=323" in text for text in report_texts),
            "native_review_b_delivered": any("REVIEW_B=323" in text for text in report_texts),
            "tool_errors": [{"tool_use_id": row.get("tool_use_id"), "content": content_text(row.get("content"))} for row in errors],
            "final": final_text, "native_is_error": final.get("is_error"),
            "subagent_stats": final.get("subagent_stats", {})}


def native_classifier_stages(debug):
    starts = {}
    finished = []
    for line in debug.splitlines():
        begin = re.search(r"classifier_request_started reqId=(\S+) tool=(\S+) model=(\S+) stage=(\S+)", line)
        if begin:
            identifier, tool, model, stage = begin.groups()
            starts[identifier] = {"native_request_id": identifier, "tool": tool, "model": model, "stage": stage}
        end = re.search(r"classifier_request_finished reqId=(\S+) tool=(\S+) stage=(\S+) outcome=(\S+) durationMs=(\d+)", line)
        if end:
            identifier, tool, stage, outcome, milliseconds = end.groups()
            finished.append(starts.get(identifier, {"native_request_id": identifier, "tool": tool, "stage": stage})
                            | {"outcome": outcome, "duration_ms": int(milliseconds)})
    return finished


def classifier_metrics(events, started, finished):
    calls = [row for row in events if row.get("event") == "request" and row.get("model") == CANDIDATE
             and row.get("billing") == "subscription" and row.get("stream") is False
             and row.get("max_tokens") in (2112, 10240) and started <= row.get("time", 0) <= finished]
    result = []
    for call in calls:
        identifier = call["id"]
        headers = next((row for row in events if row.get("id") == identifier and row.get("event") == "upstream_headers"), {})
        end = next((row for row in events if row.get("id") == identifier and row.get("event") == "finished"), {})
        result.append({key: call.get(key) for key in ("id", "model", "billing", "messages", "stream", "max_tokens", "effort_requested", "effort_applied", "time")}
                      | {"headers_seconds": headers.get("elapsed"), "finished_seconds": end.get("elapsed"),
                         "under_60_seconds": isinstance(end.get("elapsed"), (int, float)) and end["elapsed"] < 60})
    return result


def execute(root, timeout=600):
    root = Path(root).resolve()
    candidate = catalog.resolve(catalog.load(root), CANDIDATE)
    translated = protocol.to_openai({"messages": [{"role": "user", "content": "private classifier preflight"}], "max_tokens": 2112},
                                    candidate, candidate["upstream_id"])
    if candidate.get("capabilities", {}).get("reasoning") is not False or candidate.get("efforts"):
        raise RuntimeError("Candidate must be the catalog's explicit no-reasoning route")
    if any(key in translated for key in ("reasoning_effort", "thinking", "enable_thinking", "chat_template_kwargs")):
        raise RuntimeError("Candidate unexpectedly has forced reasoning flags; refusing the benchmark")
    runtime = desktop_runtime.inspect(root)
    if runtime.get("status") != "READY" or runtime.get("version") != EXPECTED_VERSION:
        raise RuntimeError("The genuine pinned Desktop Code engine 2.1.309 is not verified and ready")
    port = active_port(root)
    health = request("GET", "/health", base=f"http://127.0.0.1:{port}", timeout=3)
    if health.get("service") != "neuraldeep-claude" or health.get("revision") != source_revision():
        raise RuntimeError("Gateway is not running the current protocol revision")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = root / ".local/classifier-validation" / stamp
    folder.mkdir(parents=True, mode=0o700)
    profile = folder / "profile"
    cwd = folder / "cwd"
    profile.mkdir(parents=True, mode=0o700)
    cwd.mkdir(mode=0o700)
    fixture = cwd / "fixture.txt"
    fixture.write_text("PROJECT=ND_CLASSIFIER_FIXTURE\nLEFT=17\nRIGHT=19\nEXPECTED=323\n")
    helper = cwd / "check_fixture.py"
    helper.write_text("from pathlib import Path\ntext=Path(__file__).with_name('fixture.txt').read_text()\nassert 'EXPECTED=323' in text\nprint('SAFE_BASH_OK='+str(17*19))\n")
    bash = shlex.join([sys.executable, str(helper)])
    settings = build_settings(root, CANDIDATE, port)
    settings["env"][CLASSIFIER_ENV] = CANDIDATE
    settings["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "4096"
    settings["promptSuggestionEnabled"] = False
    atomic_json(profile / "settings.json", settings, private=True)
    atomic_json(profile / ".claude.json", {"hasCompletedOnboarding": True}, private=True)
    agents = {}
    for name in ("a", "b"):
        agents["review-" + name] = {"description": "Independent read-only fixture review " + name,
            "prompt": f"Use Read to inspect exactly {fixture}. Verify 17*19 against EXPECTED. Return exactly REVIEW_{name.upper()}=323. Do not run commands or modify any files.",
            "tools": ["Read"], "model": "inherit"}
    atomic_json(folder / "agents.json", agents, private=True)
    inputs = [{"subagent_type": "review-" + name, "description": "Read-only review " + name,
               "prompt": f"Read {fixture}, verify the multiplication, and return REVIEW_{name.upper()}=323. Read-only; no commands or writes.",
               "run_in_background": True} for name in ("a", "b")]
    prompt = ("Run exactly this safe read-only Bash command once: " + bash +
              ". It reads only this test's own fixture and prints SAFE_BASH_OK=323. "
              "Then invoke Agent twice in parallel, in the same assistant response, with exactly these inputs: " + json.dumps(inputs) +
              ". Both must run_in_background=true. Wait for both native background completion/handback messages "
              "and their safety reviews. Monitor may be used if it is available. Do not call the retired TaskOutput alias, "
              "read unfinished task output files, or create sleep commands to poll. After Bash and both reviews complete, "
              "return CLASSIFIER_FLOW_OK SAFE_BASH_OK=323 REVIEW_A=323 REVIEW_B=323. "
              "Do not create allow rules, change permission mode, bypass a check, or edit any files. "
              "If a check fails or remains unavailable, report that actual outcome instead of claiming success.")
    (folder / "prompt.txt").write_text(prompt)
    env = clean_environment()
    env.update(settings["env"])
    # Override both surfaces: native user settings otherwise override shell env.
    env[CLASSIFIER_ENV] = CANDIDATE
    env["CLAUDE_CONFIG_DIR"] = str(profile)
    env["CLAUDE_CODE_DISABLE_TERMINAL_TITLE"] = "1"
    # Diagnostic process only: request SDK debug if supported by this native
    # build. It may retain timings rather than full request/response payloads.
    env["ANTHROPIC_LOG"] = "debug"
    debug = folder / "debug.log"
    debug.touch(mode=0o600)
    command = [runtime["binary_path"], "-p", "--setting-sources", "", "--settings", str(profile / "settings.json"),
               "--model", CANDIDATE, "--permission-mode", "auto", "--agents", str(folder / "agents.json"),
               "--tools", "Bash,Read,Agent,Task,Monitor", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--debug-file", str(debug), prompt]
    started = time.time()
    run = stream_probe.run_stream(command, env, cwd, folder, timeout)
    finished = time.time()
    # The SDK normally redacts auth headers; sanitize this process's local
    # gateway token defensively before retaining or examining any log artifact.
    local_key = settings["env"]["ANTHROPIC_API_KEY"]
    redacted_files = []
    for file in (folder / "stdout.jsonl", folder / "stderr.txt", folder / "events.json", debug):
        if file.exists():
            raw = file.read_text(encoding="utf-8", errors="replace")
            if local_key in raw:
                file.write_text(raw.replace(local_key, "[local-gateway-token]"), encoding="utf-8")
                redacted_files.append(file.name)
            file.chmod(0o600)
    debug_text = debug.read_text(errors="replace")
    evidence = flow_evidence(run["events"], debug_text)
    stages = native_classifier_stages(debug_text)
    timings = classifier_metrics(json_lines(root / ".local/gateway-events.jsonl"), started, finished)
    checks = {"native_engine_309": evidence["native_version"] == EXPECTED_VERSION,
              "native_auto_mode": evidence["native_permission_mode"] == "auto",
              "safe_bash_executed": evidence["bash_marker_received"],
              "two_background_agents": evidence["background_agents_requested"] >= 2,
              "both_reviews_delivered": evidence["native_review_a_delivered"] and evidence["native_review_b_delivered"],
              "actual_candidate_classifier_calls": len(timings) >= 2,
              "two_native_handoff_contexts": len(evidence["native_handoff_contexts"]) >= 2,
              "native_classifier_stages_ok": bool(stages) and all(row.get("model") == CANDIDATE and row["outcome"] == "ok" and row["duration_ms"] < 60000 for row in stages),
              "classifier_calls_under_60s": bool(timings) and all(row["under_60_seconds"] for row in timings),
              "no_forced_classifier_effort": bool(timings) and all(row["effort_applied"] is None and row["effort_requested"] is None for row in timings),
              "no_safety_timeout_warning": not evidence["classifier_warnings"],
              "no_orchestration_tool_errors": not evidence["tool_errors"],
              "native_completed": run["exit_code"] == 0 and not run["timed_out"] and evidence["native_is_error"] is False,
              "final_marker": "CLASSIFIER_FLOW_OK" in evidence["final"]}
    receipt = plan() | {"execute": True, "run": str(folder), "native_runtime": runtime,
        "candidate_metadata": {key: candidate.get(key) for key in ("id", "billing", "capabilities", "efforts", "parameters")},
        "gateway_revision": health["revision"], "classifier_setting": settings["env"][CLASSIFIER_ENV],
        "classifier_process_environment": env[CLASSIFIER_ENV], "diagnostic_worker_max_output_tokens": 4096,
        "diagnostic_sdk_debug": True, "local_gateway_token_redacted_files": redacted_files,
        "seconds": run["seconds"], "exit_code": run["exit_code"], "timed_out": run["timed_out"],
        "evidence": evidence, "classifier_requests": timings, "native_classifier_stages": stages, "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "fixture_unchanged": fixture.read_text() == "PROJECT=ND_CLASSIFIER_FIXTURE\nLEFT=17\nRIGHT=19\nEXPECTED=323\n"}
    atomic_json(folder / "receipt.json", receipt, private=True)
    print(json.dumps({"status": receipt["status"], "checks": checks, "classifier_seconds": [row["finished_seconds"] for row in timings]}), flush=True)
    print("Receipt: " + str(folder / "receipt.json"), flush=True)
    return 0 if receipt["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("timeout must be positive")
    if not args.execute:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0
    return execute(ROOT, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
