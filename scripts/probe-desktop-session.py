#!/usr/bin/env python3
"""Prepare a real native Desktop Code task, open its supported URI, review receipts.

No GUI injection, network filter, binary substitution or private IPC is used.
The supported claude://code/new URI prefills a native composer. When native UI
automation is unavailable the user sends that prepared prompt in Desktop.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuraldeep_claude import desktop, desktop_runtime
from neuraldeep_claude.config import atomic_json

MARKER = "DESKTOP_NEURALDEEP_SESSION_OK"
FULL_WORKFLOW_MARKER = "DESKTOP_FULL_WORKFLOW_OK"
MODULE = '''def triangular(n: int) -> int:
    """Return 1 + ... + n for nonnegative integers."""
    if n < 0:
        raise ValueError("n must be nonnegative")
    return sum(range(n))  # Deliberate off-by-one bug for the Desktop Code probe.
'''
TESTS = '''import unittest
from calc import triangular


class TriangularTests(unittest.TestCase):
    def test_values(self):
        for n, expected in ((0, 0), (1, 1), (2, 3), (5, 15), (10, 55), (100, 5050), (10000, 50005000)):
            with self.subTest(n=n):
                self.assertEqual(triangular(n), expected)

    def test_negative(self):
        with self.assertRaises(ValueError):
            triangular(-1)


if __name__ == "__main__":
    unittest.main()
'''
PROMPT = f'''This is a real Claude Desktop Code integration check through NeuralDeep.
Your exact working folder is WORKSPACE_PATH. Work only there; do not search the
home directory or filesystem to locate it. Read the two files by their exact paths.

1. Read calc.py and test_calc.py. Start two independent read-only subagents in
parallel: one diagnoses the off-by-one bug, the other reviews the existing test
cases. Give them the exact paths and different tasks. Ask them to use only Read
and mathematical reasoning, without Bash or editing. Wait for both actual results.
2. Fix calc.py. Do not modify test_calc.py. Use your normal file tools.
3. Run `python -m unittest -v` in the attached folder with the shell tool and
verify that the real tests pass.
4. Discover and call the read-only NeuralDeep search_quota MCP tool once using
the subscription route. Do not create any service jobs or use wallet billing.
5. Write DESKTOP_SESSION_DONE.json with a brief diagnosis, the names of the two
subagents, their independent findings, and whether tests and the MCP call
actually succeeded. Report limitations honestly instead of inventing results.
6. End your response with exactly {MARKER} and the value triangular(100).

Use the configured Qwen subscription model. This task does not authorize
changing global settings, proxies, account state, or files outside this folder.
'''
FOCUSED_PROMPT = '''Focused native Code safety-classifier check. Your exact working directory is
WORKSPACE_PATH. Use the existing Qwen subscription model and keep Auto permission
checks enabled. Do not change permissions, settings, models or source files.

1. Launch exactly one background read-only subagent with this exact task:
   Read WORKSPACE_PATH/calc.py. Use only Read and reasoning, no Bash or edits.
   Report to your caller the function name and triangular(100), ending HANDOFF_OK.
   Wait for its actual report and normal safety review before continuing.
2. In the parent run `python -m unittest -v` in WORKSPACE_PATH once and verify
   the real output. Tests are already correct; do not edit any files.
3. Only after the handoff and real shell test both succeed, end your answer
   exactly DESKTOP_CLASSIFIER_OK 5050. If a safety review times out or fails,
   report it honestly and do not claim this check passed. No plan, MCP or other
   operations are needed for this focused check.
'''
WORKFLOW_SCRIPT = '''export const meta = {
  name: 'desktop-code-two-review-barrier',
  description: 'Read calc.py and its tests in parallel, then combine both reports',
  phases: [
    {title: 'Review', detail: 'Two independent read-only file reviews'},
    {title: 'Integrate', detail: 'Consume both completed reviews'}
  ]
};
if (!args || typeof args.cwd !== 'string' || !args.cwd) throw new Error('Missing fixture cwd');
phase('Review');
const reports = await parallel([
  () => agent('Use Read to inspect only ' + args.cwd + '/calc.py. This task is read-only: do not edit files, run commands, spawn agents, or wait for the other reviewer. Review actual triangular behavior and edge cases. Return a concise report beginning CALC_REVIEW_OK, with a concrete code observation and recommended correction only if needed.', {label: 'Review calc.py', phase: 'Review'}),
  () => agent('Use Read to inspect only ' + args.cwd + '/test_calc.py. This task is read-only: do not edit files, run commands, spawn agents, or wait for the other reviewer. Review actual test expectations and missing boundary coverage. Return a concise report beginning TEST_REVIEW_OK, with a concrete test observation and recommended correction only if needed.', {label: 'Review test_calc.py', phase: 'Review'})
]);
if (reports.length !== 2 || reports.some(v => typeof v !== 'string' || !v.trim())) throw new Error('A review did not complete');
if (!reports[0].includes('CALC_REVIEW_OK') || !reports[1].includes('TEST_REVIEW_OK')) throw new Error('Missing completed review markers');
phase('Integrate');
const integrated = {calc: reports[0], tests: reports[1]};
log('WF_BARRIER_PASSED=' + JSON.stringify(integrated));
return {
  status: 'READY_TO_INTEGRATE',
  reviews: integrated,
  next: 'Main session must use BOTH reviews before its Edit and test run.'
};
'''
FULL_WORKFLOW_PROMPT = '''Run a full native Claude Desktop Code integration check in WORKSPACE_PATH.
I explicitly request the builtin Workflow with exactly two parallel subagents.
Keep the current model, effort and Auto permission checks unchanged. Do not
change settings, permissions, billing policy, proxies or processes.

USER ROLE CONTRACT: The numbered checklist below belongs ONLY to the MAIN
Desktop coordinator. If this request is relayed into a Workflow CHILD session,
my instruction to that REVIEWER is to perform ONLY its assigned computed
read-only file review and return its CALC_REVIEW_OK or TEST_REVIEW_OK report.
The coordinator's checklist is context for reviewers, not a checklist for them
to execute. A reviewer must not launch or search for Workflow, load Skills,
call MCP/ToolSearch, run commands, edit/write files, or spawn extra agents.
Each reviewer reads only the exact file assigned by its computed task. This
role split is my explicit instruction; it preserves the native safety checks.

1. Read calc.py, test_calc.py and workflow.js by their exact paths in this
workspace. test_calc.py and workflow.js are frozen: do not edit either.
Load the builtin workflow-authoring reference with Skill as required by
Workflow's instructions; reading that installed reference is allowed.
2. Invoke the actual builtin Workflow ONCE with script equal to the complete,
verbatim contents of workflow.js and args equal to WORKFLOW_ARGS_JSON. Do not
set name/scriptPath, rewrite the script, spawn extra agents or replace Workflow
with manual Agent/MCP/shell orchestration. The supplied script uses parallel()
for two independent read-only agents, checks both reports and executes a real
Integrate barrier. If Workflow is unavailable or fails, report failure honestly.
3. After Workflow returns its background task ID, discover the read-only
NeuralDeep search_quota MCP tool with ToolSearch and call it once with billing
subscription while the workflow runs. No service jobs or wallet calls.
4. Wait for the actual native workflow completion notification and inspect its
returned reviews. Use normal notifications, and Monitor only if available;
do not call retired TaskOutput, poll with shell sleeps, or finish with a waiting
status. Both CALC_REVIEW_OK and TEST_REVIEW_OK plus READY_TO_INTEGRATE must exist.
Only then use BOTH concrete findings to fix calc.py with your file tools.
5. In the parent run python -m unittest -v in this workspace and inspect the
real output. Tests must pass without changes to the frozen files. Do not treat
the workflow's returned text as a substitute for a real Edit or shell tests.
6. Write DESKTOP_SESSION_DONE.json here with the workflow/task identification,
both actual findings, the applied fix and actual shell/MCP outcomes. If any
safety review fails or times out, retain and report it; do not claim a clean pass.
End the final answer exactly DESKTOP_FULL_WORKFLOW_OK 5050 only after everything
really completes. Report failures instead of inventing a successful result.

Work only in this workspace, apart from the installed workflow reference and
native runtime's own automatic transcripts. Do not search the home directory.
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_profile() -> Path:
    return desktop._primary_profiles()[1]


def init_fixture_git(workspace: Path) -> str | None:
    """Give native Code a normal disposable repository, with no global edits."""
    git = shutil.which("git")
    if not git:
        return None
    files = ["calc.py", "test_calc.py"] + (["workflow.js"] if (workspace / "workflow.js").exists() else [])
    for arguments in (["init", "-q"], ["add", *files],
            ["-c", "user.name=Desktop session probe", "-c", "user.email=probe@localhost",
             "-c", "core.hooksPath=.git/hooks", "commit", "-qm", "Baseline native Desktop session probe"]):
        subprocess.run([git, *arguments], cwd=workspace, capture_output=True, text=True, check=True, timeout=20)
    result = subprocess.run([git, "rev-parse", "HEAD"], cwd=workspace, capture_output=True,
                            text=True, check=True, timeout=10)
    return result.stdout.strip()


def session_environment(root: Path = ROOT) -> dict:
    """Use ordinary GUI-session transport plus the requested telemetry flags."""
    # Use the ordinary launcher environment so a URI that starts a closed app
    # receives the same native classifier configuration as a normal launch.
    env = desktop._launch_environment(Path(root))
    if sys.platform.startswith("linux"):
        runtime = f"/run/user/{os.getuid()}"
        env.setdefault("XDG_RUNTIME_DIR", runtime)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=" + runtime + "/bus")
        # Read only normal display variables. Do not copy/serialize manager
        # credentials, proxy configuration or any other service environment.
        try:
            result = subprocess.run(["systemctl", "--user", "show-environment"], env=env,
                                    capture_output=True, text=True, timeout=10)
            display_lines = result.stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            # Non-systemd Linux desktops can provide these variables directly.
            display_lines = []
        for line in display_lines:
            key, _, value = line.partition("=")
            if key in {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE", "ELECTRON_OZONE_PLATFORM_HINT"}:
                env.setdefault(key, value)
    return env


def settings_baseline_status(path: Path) -> dict:
    """Compare only saved hashes; never return credentials or file contents."""
    baseline = json.loads(Path(path).read_text())
    files = []
    for row in baseline.get("settings_files", []):
        file = Path(row["path"])
        actual = sha(file) if file.is_file() else None
        files.append({"path": str(file), "expected_sha256": row["sha256"],
                      "actual_sha256": actual, "matches": actual == row["sha256"]})
    return {"all_match": bool(files) and all(row["matches"] for row in files), "files": files}


def prepare(root: Path = ROOT, *, focused=False, workflow=False, settings_baseline: Path | None = None) -> dict:
    if focused and workflow:
        raise ValueError("Choose either the focused or full-workflow profile")
    root = Path(root).resolve()
    pin = desktop_runtime.inspect(root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = root / ".local/desktop-session-validation" / stamp
    workspace = run / "desktop-session-probe"
    workspace.mkdir(parents=True)
    module = MODULE.replace("sum(range(n))", "sum(range(1, n + 1))") if focused else MODULE
    (workspace / "calc.py").write_text(module, encoding="utf-8")
    (workspace / "test_calc.py").write_text(TESTS, encoding="utf-8")
    if workflow:
        (workspace / "workflow.js").write_text(WORKFLOW_SCRIPT, encoding="utf-8")
    baseline = init_fixture_git(workspace)
    prompt = (FULL_WORKFLOW_PROMPT if workflow else FOCUSED_PROMPT if focused else PROMPT)
    prompt = prompt.replace("WORKSPACE_PATH", str(workspace)).replace(
        "WORKFLOW_ARGS_JSON", json.dumps({"cwd": str(workspace)}, ensure_ascii=False))
    (run / "prompt.txt").write_text(prompt, encoding="utf-8")
    uri = "claude://code/new?" + urlencode({"folder": str(workspace), "q": prompt})
    log = native_profile() / "logs/main.log"
    receipt = {
        "status": "PREPARED", "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": "full-workflow" if workflow else "classifier-focused" if focused else "full-code",
        "run": str(run), "workspace": str(workspace), "desktop_runtime": pin,
        "initial_calc_sha256": sha(workspace / "calc.py"),
        "test_sha256": sha(workspace / "test_calc.py"),
        "prompt_sha256": sha(run / "prompt.txt"),
        "fixture_git_baseline": baseline,
        "native_log": str(log), "native_log_offset": log.stat().st_size if log.exists() else 0,
        "supported_uri": uri,
        "ui_action": "Approve only this probe folder if asked, then Send the prefilled Code prompt.",
        "network_filter": False, "binary_substitution": False, "gui_injection": False,
    }
    if workflow:
        receipt["workflow_sha256"] = sha(workspace / "workflow.js")
        receipt["workflow_review_criteria"] = {
            "actual_builtin_Workflow_invocations": 1, "actual_child_agents": 2,
            "workflow_journal_both_started_before_first_result": True,
            "positive_child_model_request_interval_overlap_required": True,
            "native_workflow_complete_and_READY_TO_INTEGRATE": True,
            "parent_Edit_and_Bash_after_both_reviews": True,
            "frozen_tests_and_workflow_unchanged": True,
            "subscription_search_quota_MCP_success": True,
            "native_classifier_accepts_and_no_timeout_warning": True,
            "same_Desktop_session_and_current_model_effort_Auto": True,
            "settings_before_after_hashes_unchanged": True,
            "final_marker": FULL_WORKFLOW_MARKER + " 5050",
            "scope": "These are review gates, not claims that any native execution occurred."
        }
    if settings_baseline is not None:
        source = Path(settings_baseline).resolve()
        shutil.copyfile(source, run / "settings-baseline.json")
        (run / "settings-baseline.json").chmod(0o600)
        receipt.update(current_settings_baseline_source=str(source),
                       current_settings_baseline_sha256=sha(run / "settings-baseline.json"),
                       settings_before=settings_baseline_status(run / "settings-baseline.json"))
    atomic_json(run / "receipt.json", receipt, private=True)
    return receipt


def open_run(run: Path, root: Path = ROOT, *, manual_paste: bool = False) -> dict:
    run = Path(run).resolve()
    receipt = json.loads((run / "receipt.json").read_text())
    pin = desktop_runtime.inspect(root)
    if pin.get("status") != "READY":
        raise RuntimeError("Native Desktop engine is not ready: " + str(pin.get("reason")))
    config_path = native_profile() / "configLibrary" / (desktop.PROFILE_ID + ".json")
    config = json.loads(config_path.read_text())
    if not all(config.get(key) is True for key in ("disableEssentialTelemetry", "disableNonessentialTelemetry")):
        raise RuntimeError("Requested native telemetry settings are not disabled")
    if config.get("modelDiscoveryEnabled") is False and not config.get("inferenceModels"):
        raise RuntimeError("Desktop has neither configured model rows nor discovery")
    # The same public handler accepts a folder without q. This lets the user
    # paste the exact saved prompt through the ordinary native editor if an
    # externally prefilled draft is refused before any session is created.
    uri = ("claude://code/new?" + urlencode({"folder": receipt["workspace"]})
           if manual_paste else receipt["supported_uri"])
    command = [desktop.executable(root), "--no-sandbox", uri]
    result = subprocess.run(command, env=session_environment(root), capture_output=True,
                            text=True, timeout=30)
    # A successful URI dispatch is not a session execution or a model answer.
    receipt.update(status="WAITING_FOR_NATIVE_SEND", uri_dispatch_exit_code=result.returncode,
                   native_runtime_at_open=pin, opened_at=datetime.now(timezone.utc).isoformat(),
                   inference_verified=False, manual_paste_required=manual_paste)
    atomic_json(run / "receipt.json", receipt, private=True)
    ui_action = ("Approve only this probe folder if asked, paste the exact prompt_file text into the native editor, then Send."
                 if manual_paste else receipt["ui_action"])
    return {"status": receipt["status"], "run": str(run), "workspace": receipt["workspace"],
            "uri_dispatch_exit_code": result.returncode, "ui_action": ui_action,
            "manual_paste_required": manual_paste,
            **({"prompt_file": str(run / "prompt.txt")} if manual_paste else {})}


def safe_probe_module(source: str) -> bool:
    """Only execute the tiny arithmetic fixture, without imported side effects."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    top = [node for node in tree.body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)]
    if len(top) != 1 or not isinstance(top[0], ast.FunctionDef) or top[0].name != "triangular":
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute, ast.Global, ast.Nonlocal, ast.With,
                             ast.AsyncWith, ast.AsyncFunctionDef, ast.ClassDef)):
            return False
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name)
                or node.func.id not in {"ValueError", "TypeError", "sum", "range", "int", "isinstance"}):
            return False
    return True


def review(run: Path) -> dict:
    run = Path(run).resolve()
    receipt = json.loads((run / "receipt.json").read_text())
    workspace = Path(receipt["workspace"])
    module = workspace / "calc.py"
    source = module.read_text()
    report = {"run": str(run), "reviewed_at": datetime.now(timezone.utc).isoformat(),
              "calc_changed": sha(module) != receipt["initial_calc_sha256"],
              "test_unchanged": sha(workspace / "test_calc.py") == receipt["test_sha256"],
              "safe_arithmetic_fixture": safe_probe_module(source),
              "done_artifact_exists": (workspace / "DESKTOP_SESSION_DONE.json").exists(),
              "native_session_verified": False}
    if report["safe_arithmetic_fixture"] and report["test_unchanged"]:
        result = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=workspace,
                                capture_output=True, text=True, timeout=20)
        report.update(tests_exit_code=result.returncode, tests_pass=result.returncode == 0,
                      test_output=result.stdout + result.stderr)
    if receipt.get("profile") == "classifier-focused":
        report["artifact_check_pass"] = (not report["calc_changed"] and all(report.get(key)
            for key in ("test_unchanged", "safe_arithmetic_fixture", "tests_pass")))
        report["scope"] = "Frozen files and shell tests only; actual native handoff, safety verdict and final marker need native transcript binding."
    else:
        report["artifact_check_pass"] = all(report.get(key) for key in
            ("calc_changed", "test_unchanged", "safe_arithmetic_fixture", "done_artifact_exists", "tests_pass"))
    if receipt.get("profile") == "full-workflow":
        report["workflow_unchanged"] = sha(workspace / "workflow.js") == receipt["workflow_sha256"]
        report["artifact_check_pass"] &= report["workflow_unchanged"]
        if (run / "settings-baseline.json").exists():
            report["settings_after"] = settings_baseline_status(run / "settings-baseline.json")
            report["artifact_check_pass"] &= report["settings_after"]["all_match"]
        report["scope"] = "File checks alone do not prove Workflow, parallel inference, MCP or classifier success. Bind one actual native session, workflow journal, both child transcripts/overlapping model requests and current-settings before/after hashes."
    report["status"] = "ARTIFACTS_PASS_REVIEW_NATIVE_TRANSCRIPT" if report["artifact_check_pass"] else "WAITING_OR_FAILED"
    report.setdefault("scope", "File tests alone do not prove native Desktop origin, MCP or parallel subagents; bind the actual native transcript and gateway receipts separately.")
    atomic_json(run / "artifact-review.json", report, private=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare")
    sub.add_parser("prepare-focused")
    full = sub.add_parser("prepare-full")
    full.add_argument("--settings-baseline", type=Path)
    for action in ("open", "open-manual", "review"):
        sub.add_parser(action).add_argument("run", type=Path)
    args = parser.parse_args()
    result = (prepare(focused=args.action == "prepare-focused", workflow=args.action == "prepare-full",
                      settings_baseline=getattr(args, "settings_baseline", None))
              if args.action in {"prepare", "prepare-focused", "prepare-full"}
              else open_run(args.run, manual_paste=args.action == "open-manual")
              if args.action in {"open", "open-manual"} else review(args.run))
    # A URI includes the entire prompt but no credential. Keep it in the private
    # receipt rather than producing a long user-facing command line.
    print(json.dumps({key: value for key, value in result.items() if key != "supported_uri"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
