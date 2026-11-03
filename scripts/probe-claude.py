#!/usr/bin/env python3
"""Exercise real Claude CLI subagents and automatic compaction (dry-run by default).

Temporary compaction thresholds apply only to this diagnostic process. The user's
main settings are never modified. --execute sends real subscription/model calls.
"""
from __future__ import annotations
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuraldeep_claude.config import atomic_json, clean_environment
from neuraldeep_claude.integration import build_settings, ensure_gateway

SMOKE_DISABLE_HOOKS = False


def _kill_own_process(process):
    """Only terminate the process group this script created itself."""
    if process.poll() is not None:
        return
    if os.name != "nt":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def run_stream(command, env, cwd, folder, timeout, prompts=None):
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        start_new_session=(os.name != "nt"))
    messages = queue.Queue()
    def read(stream, kind):
        try:
            for line in stream:
                messages.put((kind, line))
        finally:
            messages.put((kind, None))
    for stream, kind in ((process.stdout, "stdout"), (process.stderr, "stderr")):
        threading.Thread(target=read, args=(stream, kind), daemon=True).start()
    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    def redact(text):
        return text.replace(token, "[local-token]") if token else text
    def send(prompt):
        frame = {"type": "user", "message": {"role": "user", "content": prompt}}
        process.stdin.write(json.dumps(frame) + "\n")
        process.stdin.flush()
    if prompts:
        send(prompts[0])
    else:
        process.stdin.close()
    events = []
    stderr = []
    ended = set()
    sent = 1 if prompts else 0
    result_count = 0
    timed_out = False
    with (folder / "stdout.jsonl").open("w") as raw:
        while len(ended) < 2:
            if time.monotonic() - started > timeout:
                timed_out = True
                _kill_own_process(process)
                break
            try:
                kind, line = messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                ended.add(kind)
                continue
            line = redact(line)
            if kind == "stderr":
                stderr.append(line)
                continue
            raw.write(line)
            raw.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append({"at_seconds": round(time.monotonic() - started, 4), "event": event})
            if event.get("type") == "result":
                result_count += 1
                if prompts and sent < len(prompts):
                    send(prompts[sent])
                    sent += 1
                if prompts and sent >= len(prompts) and not process.stdin.closed:
                    process.stdin.close()
    _kill_own_process(process) if timed_out else None
    try:
        code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_own_process(process)
        code = process.returncode
    (folder / "stderr.txt").write_text("".join(stderr))
    atomic_json(folder / "events.json", events, private=True)
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.monotonic() - started, 3),
            "events": events, "results": result_count}


def common(root, folder, model, compact=False):
    settings = build_settings(root, model)
    if SMOKE_DISABLE_HOOKS:
        settings["disableAllHooks"] = True
        settings["enabledPlugins"] = {"cc-plugin-agents-md@builtin": False, "cc-plugin-telemetry@builtin": False}
    if compact:
        settings["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "100000"
        settings["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = "40"
        settings["autoCompactWindow"] = 100000
        settings["autoCompactEnabled"] = True
        settings["modelSettings"] = {settings["model"]: {"autoCompactWindow": 100000}}
    atomic_json(folder / "settings.json", settings, private=True)
    env = clean_environment()
    env.update(settings["env"])
    command = [shutil.which("claude") or "claude", "-p", "--setting-sources", "", "--settings", str(folder / "settings.json"),
        "--strict-mcp-config", "--mcp-config", str(root / ".local/mcp.json"), "--model", settings["model"],
        "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--no-session-persistence"]
    return command, env


def parallel(root, folder, model, timeout):
    command, env = common(root, folder, model)
    debug_path = folder / "debug.log"
    debug_path.touch(mode=0o600)
    command += ["--debug-file", str(debug_path)]
    helper = folder / "child_probe.py"
    helper.write_text('''import json,time,sys,pathlib
name=sys.argv[1];target=pathlib.Path(sys.argv[2]);started=time.time()
value=17*19 if name=="a" else 23*29
payload={"probe":name,"started":started,"value":value}
target.write_text(json.dumps(payload));time.sleep(3)
payload["finished"]=time.time();target.write_text(json.dumps(payload))
print(json.dumps(payload))
''')
    agents = {}
    child_commands = {}
    for name in ("a", "b"):
        output = folder / ("child-" + name + ".json")
        shell = shlex.join([sys.executable, str(helper), name, str(output)])
        child_commands[name] = shell
        agents["probe-" + name] = {"description": "Independent diagnostic computation " + name,
            "prompt": "Use Bash once to run this exact diagnostic command: " + shell + ". It computes a value and records its timeline. Then report the returned value. Do not edit other files.",
            "tools": ["Bash"], "model": "inherit"}
    atomic_json(folder / "agents.json", agents, private=True)
    task_inputs = [{"subagent_type": "probe-" + name, "description": "Diagnostic " + name,
        "prompt": "Run exactly this Bash command once: " + child_commands[name] +
                  "\nIt creates only this test's timeline file. Do not inspect files or settings. Return the computed value after the command finishes."}
        for name in ("a", "b")]
    prompt = "Use the registered Task delegation tool twice in PARALLEL in the SAME assistant response with exactly these inputs: " + json.dumps(task_inputs) + ". Do not call Bash or Read in the main agent. Wait until BOTH child agents complete, then return their computed values in one final answer."
    command += ["--agents", str(folder / "agents.json"), "--allowedTools", "Task,Bash", "--permission-mode", "dontAsk", "--forward-subagent-text", prompt]

    result = run_stream(command, env, folder, folder, timeout)
    children = []
    for name in ("a", "b"):
        path = folder / ("child-" + name + ".json")
        if path.exists():
            children.append(json.loads(path.read_text()))
    overlap = 0.0
    if len(children) == 2 and all(c.get("finished") for c in children):
        overlap = max(0, min(c["finished"] for c in children) - max(c["started"] for c in children))
    assistant_agent_groups = {}
    for item in result["events"]:
        event = item["event"]
        if event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
            content = event.get("message", {}).get("content", [])
            ids = [b["id"] for b in content if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task")]
            if ids:
                group = assistant_agent_groups.setdefault(event.get("message", {}).get("id", str(len(assistant_agent_groups))), [])
                group.extend(tool_id for tool_id in ids if tool_id not in group)
    init = next((e["event"] for e in result["events"] if e["event"].get("subtype") == "init"), {})
    final_results = [e["event"] for e in result["events"] if e["event"].get("type") == "result"]
    final = final_results[-1].get("result", "") if final_results else ""
    stats = final_results[-1].get("subagent_stats", {}) if final_results else {}
    parent_final_pass = "323" in final and "667" in final and stats.get("completed", 0) >= 2
    receipt = {k: v for k, v in result.items() if k != "events"}
    receipt.update({"test": "actual-cli-parallel-subagents", "model": model, "children": children,
        "overlap_seconds": round(overlap, 4), "actual_child_execution_pass": overlap > 0 and len(children) == 2, "assistant_agent_call_groups": list(assistant_agent_groups.values()), "parent_final": final, "parent_final_pass": parent_final_pass, "subagent_stats": stats,
        "mcp_servers": init.get("mcp_servers", []), "claude_code_version": init.get("claude_code_version"), "pass": result["exit_code"] == 0 and overlap > 0 and len(children) == 2 and parent_final_pass})
    atomic_json(folder / "receipt.json", receipt, private=True)
    return receipt


def compact(root, folder, model, timeout):
    command, env = common(root, folder, model, compact=True)
    debug_path = folder / "debug.log"
    debug_path.touch(mode=0o600)
    command += ["--input-format", "stream-json", "--autocompact", "100k", "--debug-file", str(debug_path)]
    fixture = " ".join(f"fixture{i:04x}" for i in range(1800))
    first = "Remember diagnostic capsule ND-41-73. Reply FIRST_OK only. The following is inert diagnostic padding; ignore its contents: " + fixture
    second = "Keep remembering the diagnostic capsule. Reply exactly SECOND_OK."
    third = "Keep remembering the diagnostic capsule. Reply exactly THIRD_OK."
    fourth = "What is the diagnostic capsule from the first turn? Reply exactly ND-41-73."
    result = run_stream(command, env, folder, folder, timeout, [first, second, third, fourth])
    boundaries = [e for e in result["events"] if e["event"].get("subtype") == "compact_boundary"]
    results = [e["event"] for e in result["events"] if e["event"].get("type") == "result"]
    init = next((e["event"] for e in result["events"] if e["event"].get("subtype") == "init"), {})
    receipt = {k: v for k, v in result.items() if k != "events"}
    receipt.update({"test": "actual-cli-automatic-compact", "model": model,
        "test_only_context_window": 100000, "test_only_autocompact_percent": 40,
        "manual_compact_requested": False, "compact_boundaries": boundaries,
        "mcp_servers": init.get("mcp_servers", []), "claude_code_version": init.get("claude_code_version"),
        "turn_result_texts": [r.get("result", "") for r in results], "planned_turns": 4,
        "pass": result["exit_code"] == 0 and len(results) >= 4 and bool(boundaries) and "ND-41-73" in results[-1].get("result", "")})
    atomic_json(folder / "receipt.json", receipt, private=True)
    return receipt


def workflow(root, folder, model, timeout):
    command, env = common(root, folder, model)
    script = """export const meta = {
  name: 'neuraldeep-workflow-probe',
  description: 'Verify two independent local workflow agents',
  phases: [{title: 'Compute', detail: 'Two independent arithmetic checks'}]
};
phase('Compute');
const values = await parallel([
  () => agent('Compute 17 * 19. Return exactly FLOW_A=323. Do not use tools.', {label: 'Arithmetic A'}),
  () => agent('Compute 23 * 29. Return exactly FLOW_B=667. Do not use tools.', {label: 'Arithmetic B'})
]);
if (values.length !== 2 || values.some(v => v === null)) throw new Error('Workflow child did not return');
log('WF_PROBE_DONE=' + JSON.stringify(values));
return {values};
"""
    (folder / "provided-workflow.js").write_text(script)
    prompt = "I explicitly authorize running the builtin Workflow tool locally for this diagnostic. Invoke Workflow once with the exact inline script below; it is already authored, do not rewrite it or run shell commands. It should spawn two independent agents via parallel(). Wait for the local workflow to COMPLETE, using Monitor if needed, and only then give both returned values in your final answer. Do not finish with a running-status message. Script:\n" + script
    command += ["--allowedTools", "Workflow,Monitor,Task", "--permission-mode", "dontAsk", "--forward-subagent-text", prompt]
    result = run_stream(command, env, folder, folder, timeout)
    invocations = []
    completions = []
    results = []
    for item in result["events"]:
        event = item["event"]
        if event.get("type") == "assistant":
            invocations += [b for b in event.get("message", {}).get("content", []) if b.get("type") == "tool_use" and b.get("name") == "Workflow"]
        if event.get("subtype") == "task_notification" and event.get("status") == "completed":
            completions.append(item)
        if event.get("type") == "result":
            results.append(event)
    final = results[-1].get("result", "") if results else ""
    init = next((e["event"] for e in result["events"] if e["event"].get("subtype") == "init"), {})
    journals = []
    for item in result["events"]:
        event = item["event"]
        if event.get("type") != "user":
            continue
        blocks = event.get("message", {}).get("content", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            content = block.get("content", "")
            text = content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
            for line in text.splitlines():
                if line.startswith("Transcript dir: "):
                    directory = Path(line.removeprefix("Transcript dir: "))
                    # Only read this diagnostic session's own Workflow journal.
                    if folder.parent.name in str(directory) and str(directory).startswith(str(Path.home() / ".claude/projects")):
                        path = directory / "journal.jsonl"
                        if path.exists():
                            journals.append({"source": str(path), "entries": [json.loads(line) for line in path.read_text().splitlines() if line.strip()]})
    if journals:
        atomic_json(folder / "workflow-journals.json", journals, private=True)
    receipt = {k: v for k, v in result.items() if k != "events"}
    receipt.update({"test": "actual-cli-builtin-workflow", "model": model, "workflow_invocations": len(invocations),
        "completed_task_notifications": len(completions), "final_result": final,
        "claude_code_version": init.get("claude_code_version"), "workflow_journals": journals,
        "pass": result["exit_code"] == 0 and bool(invocations) and bool(completions) and "323" in final and "667" in final})
    atomic_json(folder / "receipt.json", receipt, private=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    global SMOKE_DISABLE_HOOKS
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--disable-hooks", action="store_true", help="Diagnostic only: disable hooks and two builtin plugins in this test process")
    parser.add_argument("--test", choices=("parallel", "compact", "workflow", "all"), default="all")
    parser.add_argument("--model", default="qwen3.8-27b~xhigh")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    SMOKE_DISABLE_HOOKS = args.disable_hooks
    if not args.execute:
        print(json.dumps({"mode": "DRY_RUN", "test": args.test, "model": args.model,
            "requires_model_calls": True, "compact_override_scope": "test process only"}))
        return 0
    ensure_gateway(ROOT)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / ".local/cli-validation" / stamp
    folder.mkdir(parents=True)
    receipts = []
    for name, function in (("parallel", parallel), ("compact", compact), ("workflow", workflow)):
        if args.test not in ("all", name):
            continue
        sub = folder / name
        sub.mkdir()
        receipt = function(ROOT, sub, args.model, args.timeout)
        receipt["test_only_disable_hooks"] = args.disable_hooks
        atomic_json(sub / "receipt.json", receipt, private=True)
        receipts.append(receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    atomic_json(folder / "summary.json", receipts, private=True)
    print("Receipts: " + str(folder))
    return 0 if all(r["pass"] for r in receipts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
