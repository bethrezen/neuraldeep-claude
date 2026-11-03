#!/usr/bin/env python3
"""Dry-run-first acceptance of native Claude --effort through NeuralDeep.

Uses a private CLI config/cwd per level; no user settings or product limits are
changed. This exercises the native command-line effort option, not interactive
/effort UI or persistence. Execution consumes subscription inference quota.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuraldeep_claude import catalog
from neuraldeep_claude.config import atomic_json, clean_environment, source_revision
from neuraldeep_claude.effort import CLAUDE_LEVELS, describe
from neuraldeep_claude.integration import active_port, build_settings, native_cli
from neuraldeep_claude.transport import request

MODEL = "nd/qwen3.8-27b@subscription"
# Distinct test-only budgets correlate each CLI with its gateway request even
# while unrelated Desktop/GPT tests run. No production settings use these caps.
BUDGETS = {level: 4091 + index for index, level in enumerate(CLAUDE_LEVELS)}


def plan():
    return {"execute": False, "model": MODEL, "billing": "subscription",
            "efforts": list(CLAUDE_LEVELS), "workers_max": 2,
            "scope": "native --effort option; interactive /effort UI and persistence not tested",
            "private_cli_profile_per_level": True, "MCP_services": False,
            "network_filter": False, "diagnostic_output_budgets": BUDGETS,
            "message": "Dry run. Add --execute to send five subscription inference requests."}


def final_result(stdout):
    value = json.loads(stdout)
    rows = value if isinstance(value, list) else [value]
    results = [row for row in rows if isinstance(row, dict) and row.get("type") == "result"]
    if not results:
        raise ValueError("Native CLI output contains no result record")
    return results[-1]


def gateway_events(path, offset):
    if not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read().decode("utf-8", errors="replace")
    events = []
    for line in raw.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            # A concurrent writer's last line can be unfinished. It cannot
            # count as positive evidence; completed request rows are required.
            continue
    return events


def mapping_evidence(events, level, expected, budget, started, finished):
    matched = [row for row in events if row.get("event") == "request"
               and row.get("model") == MODEL and row.get("billing") == "subscription"
               and row.get("max_tokens") == budget
               and started <= row.get("time", 0) <= finished]
    return {"matched_gateway_requests": [{key: row.get(key) for key in (
                "id", "time", "model", "billing", "max_tokens", "effort_requested", "effort_applied")}
                for row in matched],
            "stock_effort_seen": bool(matched) and all(row.get("effort_requested") == level for row in matched),
            "upstream_effort_matches": bool(matched) and all(row.get("effort_applied") == expected for row in matched),
            "correlation": "base route + unique diagnostic budget + native process execution window"}


def run_level(root, run, native, level, expected, port, timeout):
    folder = run / level
    profile = folder / "profile"
    cwd = folder / "cwd"
    profile.mkdir(parents=True, mode=0o700)
    cwd.mkdir(mode=0o700)
    settings = build_settings(root, MODEL, port)
    settings["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(BUDGETS[level])
    settings_path = profile / "settings.json"
    atomic_json(settings_path, settings, private=True)
    atomic_json(profile / ".claude.json", {"hasCompletedOnboarding": True}, private=True)
    env = clean_environment()
    env.update(settings["env"])
    env["CLAUDE_CONFIG_DIR"] = str(profile)
    marker = "ND_EFFORT_" + level.upper() + "_" + run.name
    command = [native, "--setting-sources", "", "--settings", str(settings_path),
               "--model", MODEL, "--effort", level, "--no-session-persistence",
               "--permission-mode", "dontAsk", "--tools", "", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--max-turns", "1", "--output-format", "json",
               "-p", "Reply exactly " + marker + "."]
    metrics = root / ".local/gateway-events.jsonl"
    offset = metrics.stat().st_size if metrics.exists() else 0
    started = time.time()
    record = {"effort": level, "expected_upstream": expected, "diagnostic_max_tokens": BUDGETS[level],
              "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat(),
              "CLI_config_directory": str(profile), "user_config_modified_by_probe": False,
              "command_scope": "native --effort; not interactive slash persistence"}
    stdout, stderr = "", ""
    try:
        process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=timeout)
        stdout, stderr = process.stdout, process.stderr
        record["exit_code"] = process.returncode
        final = final_result(stdout)
        answer = final.get("result", "")
        record.update(marker_received=isinstance(answer, str) and answer.strip() == marker,
                      native_error=final.get("is_error"), num_turns=final.get("num_turns"),
                      native_models=list(final.get("modelUsage", {})),
                      native_result_sha256=hashlib.sha256(str(answer).encode()).hexdigest())
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode("utf-8", errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        record.update(error_type="TimeoutExpired", timeout_seconds=timeout)
    except (OSError, ValueError) as error:
        record.update(error_type=type(error).__name__, error_message=str(error)[:300])
    finished = time.time()
    record.update(mapping_evidence(gateway_events(metrics, offset), level, expected, BUDGETS[level], started, finished))
    record["seconds"] = round(finished - started, 3)
    record["status"] = "PASS" if (record.get("exit_code") == 0 and record.get("marker_received")
        and record.get("native_error") is False and record["stock_effort_seen"]
        and record["upstream_effort_matches"] and record.get("native_models") == [MODEL]) else "FAIL"
    (folder / "stdout.json").write_text(stdout, encoding="utf-8")
    (folder / "stderr.log").write_text(stderr, encoding="utf-8")
    atomic_json(folder / "receipt.json", record, private=True)
    return record


def execute(root, workers=2, timeout=240):
    root = Path(root).resolve()
    data = catalog.load(root)
    model = catalog.resolve(data, MODEL)
    expected = describe(model)["mapping"]
    native = native_cli(root)
    port = active_port(root)
    health = request("GET", "/health", base=f"http://127.0.0.1:{port}", timeout=3)
    if health.get("service") != "neuraldeep-claude" or health.get("revision") != source_revision():
        raise RuntimeError("Gateway is missing or stale; start/restart it before this probe")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = root / ".local/effort-validation" / stamp
    run.mkdir(parents=True, mode=0o700)
    receipt = plan() | {"execute": True, "run": str(run), "native": native,
                        "gateway_revision": health["revision"], "expected_mapping": expected, "checks": []}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_level, root, run, native, level, expected[level], port, timeout): level
                   for level in CLAUDE_LEVELS}
        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception as error:
                row = {"effort": futures[future], "status": "FAIL", "error_type": type(error).__name__}
            receipt["checks"].append(row)
            atomic_json(run / "receipt.json", receipt, private=True)
            print(json.dumps({key: row.get(key) for key in ("effort", "status", "seconds", "error_type")}), flush=True)
    receipt["checks"].sort(key=lambda row: CLAUDE_LEVELS.index(row["effort"]))
    receipt["status"] = "PASS" if all(row["status"] == "PASS" for row in receipt["checks"]) else "FAIL"
    receipt["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(run / "receipt.json", receipt, private=True)
    print("Receipt: " + str(run / "receipt.json"), flush=True)
    return 0 if receipt["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("timeout must be positive")
    if not args.execute:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0
    return execute(ROOT, args.workers, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
