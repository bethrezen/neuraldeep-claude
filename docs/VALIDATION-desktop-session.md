# Native Desktop Code session — 2026-11-02

This check uses the actual installed Claude Desktop 4.4212.0, its own native
Code engine, and NeuralDeep through the configured local gateway. No network
filter, binary patch, fake `.verified`, standalone CLI substitution or private
GUI/IPC injection is used.

## Native engine preparation

The original Desktop log records its normal download on 2026-11-02 at
21:38:55–21:38:56 Europe/Moscow:

- Downloaded **103,411,745 bytes**.
- Decompressed to **293,469,552 bytes**.
- Raw payload SHA-256:
  `4d704a8aecbe038affa3000f498ae17c1b4f753add8facb8764120affc99b658`.
- Installed engine **2.1.309** at its own native profile cache.

Read-only `desktop_runtime.inspect` now returns `READY`. The `.verified`
compressed digest matches the app's embedded manifest:
`e52289b95def16148c8d0a48b1ccc0d357429e73473a9a20ac0638fb7460a59b`.
The raw payload's actual size and hash match its native `.payload` receipt.
This is genuine Desktop preparation; the integration did not write those markers.

The existing user Desktop instance performed this download and the first
session. It was restarted later only after the user explicitly authorized the
classifier retest; no unrelated GUI instance or shared service was stopped.

## Repeatable session task

`scripts/probe-desktop-session.py prepare` creates an isolated task directory
with a deliberate off-by-one bug, frozen unit tests, a detailed prompt and a
private receipt. The prepared native Code prompt asks the model to:

1. Read the files and run two independent read-only subagents in parallel.
2. Fix the implementation without altering the tests.
3. Run real shell unit tests and inspect their output.
4. Discover and call the read-only NeuralDeep search quota MCP tool once.
5. Write a local completion artifact and report actual results.

`open <run>` dispatches the officially supported
`claude://code/new?folder=...&q=...` URI through the original native executable.
The native source's `kU`/`Efr` handlers admit folder and prompt arguments and
route them into the Code composer. The command does not use CDP, xdotool,
scripted clicks, undocumented IPC, or a remote-debugging bypass.

The available computer-use surface has no native-app controls. The user must
approve only this task folder if asked and press Send in the native composer.
URI dispatch is explicitly **not** recorded as session execution or inference.

`review <run>` checks real code changes, an unchanged test file, real test
execution and the completion artifact. Those artifacts alone do not establish
native Desktop origin, actual MCP use or actual parallel subagents: the native
session transcript and gateway receipts must also be bound to this run.

Ten local tests verify the probe's preparation, official URI dispatch, refusal
to substitute an unready native engine, and its refusal to accept a completion
claim or edited tests as proof. They do not prove a Code session has run.

## Current execution record

Prepared run:
`.local/desktop-session-validation/20261102T184552607655Z/`.
The task folder is `desktop-session-probe/` inside that run. Native bootstrap
proof is stored as `native-bootstrap.json` beside the preparation receipt.

The user sent the prepared prompt in the native Code UI. The first complete
session finished at 22:02:58 Europe/Moscow and is classified
**PASS_WITH_AUTO_CLASSIFIER_TIMEOUTS**, rather than a clean reliability pass.

`native-session-review.json` in that run binds:

- Actual Desktop main process → its disclaimer supervisor → the exact native
  2.1.309 executable, with the task folder as cwd.
- Actual engine environment `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`,
  `DISABLE_TELEMETRY=1` and `DISABLE_ERROR_REPORTING=1`.
- The native Desktop session metadata and its CLI transcript, with SHA-256
  bindings. The model resolves to Qwen 3.8 27B subscription.
- Real Read/Edit/Write, native shell `python -m unittest -v` returning both
  tests OK, unchanged frozen tests, and an independently repeated artifact
  verification.
- One actual ToolSearch, the quota tool reference, and one successful
  `mcp__neuraldeep-search__search_quota` call on the subscription route.
- Two real subagent transcripts. Their actual model-request intervals overlap
  by **9.27 seconds** at the largest observed overlap.
- The final native assistant answer ending
  `DESKTOP_NEURALDEEP_SESSION_OK 5050`.

Some Bash attempts were delayed or rejected because the native auto-mode
permission classifier timed out. Those failures remain in the original
transcripts and are not treated as successes. The gateway showed omitted
classifier effort mapping to the reasoning model's maximum, with long upstream
latencies; the main file/model/MCP paths nevertheless completed successfully.
The user approved a dedicated fast NeuralDeep classifier and a native Desktop
restart followed by a clean retest.

Fresh retest run:
`.local/desktop-session-validation/20261102T190235657558Z/`.
Its prompt includes the exact working directory and asks diagnostic subagents
to use Read and reasoning only; the parent still performs actual Bash tests.
The disposable fixture is a normal local Git repository. No global Git policy
or private Desktop Git cache was altered.

After the user approved restart, the old completed session's sole Desktop
instance was terminated gracefully. The updated ordinary Desktop launch sets
the dedicated classifier and telemetry flags, without a proxy or filter. The
tool process initially lacked the graphical session's XAUTHORITY variable;
two startup attempts failed before opening a window. Copying the existing
XAUTHORITY path from the user manager (without reading or altering its cookie)
resolved that tool-environment problem. The new Desktop started normally and
reported **44 discovered picker rows**. A standard URI handoff then returned 0.
The user sent this second prompt. The actual native engine's environment and
gateway metrics prove classifier routing to **Qwen 3.8 27B noreason subscription**,
with no effort parameter applied to that model. The main model stayed Qwen 3.8
27B at the selected effort. Its permission mode stayed `auto`.

This second run is **FAIL_AUTO_CLASSIFIER_TIMEOUT_AND_INCOMPLETE_MAIN_TASK**.
Its `native-session-review.json` records both separate failures:

- A subagent hand-back safety review took **64.23 seconds** upstream. Native Code
  queued its timeout warning after approximately **60 seconds**, before that
  response arrived. The user's screenshot and original transcript retain the
  warning. A returned report acknowledgement does not turn this into a passed
  safety review.
- Both child agents finished and their hand-back/completion messages were
  absorbed into the parent. The last native API request snapshot retains both
  reports, including the timeout warning, as dynamic system messages. The main
  model nevertheless answered that both were still running and stopped its
  turn without the implementation fix or shell tests. The gateway had zero
  active requests at review. Waiting longer would not complete an idle turn.

All 15 messages of that last native request were reconstructed from its replay
blobs and transcript message hashes, together with its original system/tool
shape, parameters and cache controls. The reconstructed request matches the
native `requestDigest` exactly:
`8b99bfd8dfd09b0c89d840dc39172ffd355c470a21f73bf8cc8b8dbfea3d67a1`.
The private payload and reconstruction receipt are stored alongside the failed
run. They contain only this disposable session, without API credentials or
account metadata.

The gateway at that failed cutoff forwarded dynamic system messages. The
matching native digest proves request construction; it is not a provider-side
receipt. Provider handling of late system messages required a separate
translated-payload comparison before assigning the stale answer solely to the
model. The later canonical handoff correction and actual fresh-session result
are recorded below. Default request logging deliberately contains no prompt
bodies. No safety check, permission mode or deadline was bypassed.

The user selected **Qwen 3.6 35B A3B noreason subscription** as the next classifier
candidate. The private standalone diagnostic
`.local/classifier-validation/20261102T194726678463Z/classifier-acceptance-review.json`
accepts that candidate using the actual native 2.1.309 Auto-mode code. All eight
classifier stages for Bash, two Agent launches and two `SubagentHandback`
reviews have `outcome=ok`, at **0.71–5.97 seconds**. Both real background reports
arrived and no classifier timeout warning appeared. Criteria, native deadlines
and permission mode were unchanged.

That evidence is a standalone native diagnostic, not an interactive Desktop
session or a replay of the exact old classifier payload. Its original broader
receipt remains `FAIL` because the initial harness requested retired
`TaskOutput`; the worker recovered, and the separate review accepts only the
classifier candidate. At that cutoff the actual Desktop follow-up had not run;
its later fresh-session result is recorded below.

`prepare-focused` provides a shorter follow-up:
one background read-only report, its normal safety review, and a real parent
shell test over already-correct, frozen fixture files. A focused artifact check
alone never counts as native handoff or classifier evidence.

The focused fixture at
`.local/desktop-session-validation/20261102T195222787515Z/` was opened after the
authorized restart at 23:11 Europe/Moscow. Its already-correct source and
unchanged tests passed both real unit tests before Send. The user reported that
Send animated without starting the session, and that manually cutting and
pasting the prefilled text did not help. A folder-only manual draft was then
opened, without another restart or configuration change. The user asked for
computer-use operation instead of further manual clicking.

Native logs show the correct workspace trust saved, but no
`LocalSessions.start:` call, focused session metadata or persistent Code worker.
Folder URI processing itself can save trust, so that log does **not** prove
the submit handler passed its trust check. The exact live refusal branch has
not been identified. Source candidates such as model/default-permission
readiness, stale draft identity or an editor/sweep change are not reported as
confirmed causes. A separate initialize-only diagnostic shows native 2.1.309
accepts Auto mode; it is not the missing Desktop session.

That draft attempt was **BLOCKED_BEFORE_NATIVE_SESSION_START**, with no
classifier/notification/Bash run. Its preserved historical receipt is
`native-ui-blocker-review.json`, alongside `native-submit-diagnosis.json` and
the frozen baseline. The available computer-use inventory has `apps=[]` and
explicitly disables native APIs. Browser-only controls do not provide the
missing native UI action. No unsupported GUI or IPC route was substituted.

`open-manual <run>` is the supported fallback preparation: it dispatches the
same public folder URI without `q` and gives the exact saved `prompt.txt` for
ordinary manual editor paste and Send. It does not submit, drive UI controls,
restart the app, alter configuration or count an opened composer as inference.

The installed app's public Code URI handler supports `q`/`prompt`, `folder`,
`environment` and `runner_pool`. It has no `submit` or `autostart` parameter;
the handler navigates into the composer. A fresh interactive Code run therefore
still needs a functioning native UI submit path.

## Fresh user-started native session: focused functional PASS

The user opened a fresh native Code session and Send worked. This is a new
attempt over the same frozen focused fixture; the old blocked receipt is not
overwritten. The exact cause of the old draft's Send failure remains unknown.
No configuration, permission, model or process changes were made during this
running session.

The fresh session started at **23:36:35 Europe/Moscow** and completed at
**23:37:53**, with status **PASS_NATIVE_FOCUSED_FUNCTIONAL**. Its private evidence
directory is
`.local/desktop-session-validation/20261102T195222787515Z/attempts/20261102T203635873Z/`.
`native-session-review.json` binds:

- Native Desktop main PID 2850851 → disclaimer PID 2884199 → genuine native
  2.1.309 Code worker PID 2884200, with the exact focused fixture as cwd.
- Native session `local_8a97fd31-0b9d-48da-86c3-08c3e28a0997` and CLI transcript
  `05b4ab48-e6b6-4c2a-b31f-f55a80831ebc`, including transcript SHA-256 bindings.
- Actual worker gateway URL, disabled telemetry/error reporting, unchanged
  Qwen 3.8 27B subscription main model, and permission mode `auto`.
- The actual initial user prompt matches the prepared `prompt.txt` except for
  the native editor removing its final LF: 1,273 → 1,272 characters.
- The selected native main effort `high` maps to upstream `xhigh`. The dedicated
  classifier resolves to exact upstream **`qwen3.6-35b-a3b-noreason`**, subscription.
- One real background read-only agent: its actual native Agent result explicitly
  confirms async/background launch and an automatic completion notification,
  although the caller omitted `run_in_background`. Its `SubagentHandback` ends
  `HANDOFF_OK`. Native permission decisions are `accept` with
  `reasonType=classifier` for Agent, SubagentHandback and Bash.
- Four actual classifier requests: Agent stages 1/2 took **3.963 / 3.842 s**;
  hand-back took **1.119 s**; Bash took **1.673 s**. Requests used the native
  2,112/10,240 token maxima, without requested or applied effort. No reasoning
  usage metric was recorded, so zero reasoning tokens/chars is not asserted.
- Zero native classifier-unavailable/timeout warnings in the parent and child
  transcripts. This Desktop run did not enable `--debug-file`; nonexistent
  literal `[Stall] outcome=ok` entries are not claimed. The actual native accept
  decisions, completed actions and recorded response latencies establish the
  functional review result.
- The parent received the actual report and then ran the real unsandboxed
  `python -m unittest -v`: both unchanged frozen tests returned OK. Both fixture
  files remained unchanged, and an independent post-session check also passed.
- The final native assistant response ends exactly
  `DESKTOP_CLASSIFIER_OK 5050`.

The first native request after hand-back was reconstructed from all nine
message hashes and its native system/tool shape. Its exact digest matches
`39af7e03e3fe9418339a7ea542da563c5d026a7929a9d6bd0c2fa0cf24d6451b`.
The current translator keeps one initial control-system message and carries
the preserved hand-back as user data. The parent actually continued with the
reported result. `canonical-handoff-proof.json` records this reconstruction;
it does not claim a provider-side body log. The live gateway revision at review
was `d9017b945301dc44767af32cb6228358855a518d8b305b287c89073a6dce5870`.

This passes the focused native Desktop classifier/notification/shell path.
The earlier full core session separately proves editing, MCP and two parallel
subagents. The failed old session, old UI draft and standalone candidate test
remain separate evidence. One successful focused run does not establish
reliability for every model, task, workflow or platform.

## Full current-settings Workflow attempt: failed and cancelled

The later full run
`.local/desktop-session-validation/20261102T205424032100Z/` used one actual
Desktop session for the requested combined test: a native Workflow, exactly two
parallel read-only child agents, a data-dependent Integrate barrier, a read-only
MCP quota call, then a parent code fix, frozen tests and final artifact. The
fresh implementation really failed the original frozen tests before launch;
the successful focused fixture was not reused as an already-fixed task.

The user started native session
`local_7a668ac1-9340-4aa6-bfa0-9c4690311d55`, CLI
`3fc92e40-a5a0-43e3-aa7b-dfaeccdd893d`, at **20:57:37 UTC**. It ran the genuine
2.1.309 worker PID 2912247 under the existing Desktop PID 2850851, using Qwen 3.8
27B subscription, selected effort mapping, Auto mode and the same dedicated
35B A3B noreason classifier. No settings or model were changed during the run;
all five saved settings-file hashes still matched immediately before cancel.

This run is **FAIL_NATIVE_FULL_WORKFLOW_CANCELLED**, not a clean full pass:

- The native direct-title sideband timed out at 20:57:52 UTC. Its stock host
  fallback also failed with exit 1 at 20:58:22. These failures alone prevent
  the requested unqualified “without timeouts” result.
- The main session read all three fixture files, loaded the builtin
  `workflow-authoring` reference and invoked the real builtin Workflow once.
  Its script matches the frozen file except for one omitted final LF; its
  exact `args.cwd` points at the new fixture. The journal records launched,
  both children started, and one completed result.
- Two genuine workflow children had **67.141865 seconds** of overlapping active
  gateway API requests. Each completed request is bound to its native child
  transcript by the exact input/output/cache usage counts and response-end
  timestamp, then measured using gateway request/finished times. This is API
  concurrency evidence, not provider GPU compute concurrency.
- The parent discovered and successfully called
  `mcp__neuraldeep-search__search_quota` once on subscription while the Workflow
  was still pending, proving this asynchronous continuation path.
- The tests reviewer returned a substantive `TEST_REVIEW_OK`. The implementation
  reviewer instead repeated the coordinator's full checklist, read all three
  files and repeatedly searched for a nested Workflow. Its correctly present
  computed read-only task was not lost. Native Workflow relays the original
  coordinator request as authoritative user text, followed by the computed
  child task as script output; the initial prompt did not explicitly scope the
  full checklist to the coordinator. This exposed a child-role selection
  failure. No safety provenance or permission rule was weakened to hide it.
- The implementation child's final streamed API request remained active for
  **802.112 seconds** at cancellation, without a completed assistant result.
  The remaining implementation review, Integrate barrier, Workflow completion, parent Edit/Bash,
  completion artifact and success marker were not reached.

After the failed snapshot and unchanged settings hashes were saved, the owning
agent explicitly authorized cancelling this test. A standard SIGINT was sent
only to PID 2912247 after checking its real executable, cwd and CLI session
binding. That worker exited promptly; Desktop PID 2850851, the old completed
focused-session worker PID 2884200 and shared services were left running. The
gateway still reported one orphaned upstream request immediately afterwards;
worker exit is not misreported as gateway idle. That request eventually ended
naturally at **21:22:02 UTC**, with total gateway elapsed time **1,012.783 s**,
approximately **210 s after SIGINT**. The gateway then reported zero active
requests; no signal to the gateway was needed or sent by this monitor. This
delayed cancellation is retained as a separate defect to address.

Private evidence includes `native-session-review.json`,
`pre-cancel-native-failure-review.json`, `native-cancel-receipt.json`,
`sideband-title-failure.json`, `workflow-child-role-drift.json`,
`gateway-overlap-live.json`, the genuine native journal/transcripts, and the
original preflight/settings baseline. The old run and its raw results remain
unchanged. A fresh, unsent follow-up fixture has an explicit user-level
coordinator/reviewer role contract; it is not treated as a successful retest.

## Role-scoped full retry: workflow completed, parent continuation failed

The fresh run
`.local/desktop-session-validation/20261103T063051207548Z/` used the new explicit
coordinator/reviewer role contract and gateway revision
`525cd4064e84e11df59148ef1fc60956f1c4e4720344abc75489a25f083842c4`.
The user started genuine native 2.1.309 session
`local_26f3c323-cfe9-4626-8e1c-5fe00fa5203b`, CLI
`da44abc6-29e8-4f5d-b98d-f607527ae017`, at **06:46:38 UTC on November 3**.
Initial prompt/cwd/template, unchanged Qwen 3.8 main model, selected effort,
35B noreason classifier and Auto mode were bound to the real process.

Several previously failing paths worked in this attempt:

- The real native coding-title request used the configured subscription
  `qwen3.6-35b-a3b-noreason` helper and finished in **0.440167 s**, without
  cancellation, effort or title fallback.
- Both real Workflow children performed only Read of their own assigned file
  and returned `CALC_REVIEW_OK` / `TEST_REVIEW_OK`. No child repeated the parent
  checklist, searched for nested Workflow, loaded skills or ran commands.
- Native Workflow `wf_dbf7c3dd-0a4` completed; its actual output contains
  `WF_BARRIER_PASSED` and its completion result contains `READY_TO_INTEGRATE`.
- The two child transcripts are bound to actual gateway request intervals by
  exact usage counts and response-end timestamps. Maximum observed active API
  overlap was **27.483686 s**; no GPU-compute concurrency is inferred.
- Subscription `search_quota` succeeded while the Workflow was pending.

Nevertheless the result is
**FAIL_NATIVE_FULL_WORKFLOW_COMPLETION_DELIVERY**. The native completion
notification was queued at **06:49:29 UTC** and delivered with
`absorbed_mid_turn` at **06:49:44**. The parent then returned stale waiting text
at **06:50:14** and ended idle. It performed **zero Edit calls and zero final
unittest Bash calls**, wrote no completion artifact and emitted no success
marker. A separate earlier Bash `ls` was only a directory listing.

The exact final native request was reconstructed with matching digest
`028b86619b0cd8d8325182a771964c85622c1e0deef5d810315ea402e3173621`.
Its actual completed `<task-notification>` was a dynamic system message.
The current translator recognised the ordinary SubagentHandback report frame,
but not this Workflow-result frame, and merged the completion data into its
initial system-control context. The private
`workflow-completion-role-proof.json` records the resulting placement. This is
request reconstruction and translation evidence, not a provider-side body log.

The immutable fixture and all five settings hashes still matched the baseline;
independent fixture tests remained RED because the parent had not fixed the
bug. Gateway active requests were zero. The idle worker was left untouched and
no corrective prompt, model change or runtime edit was injected into this
attempt. `native-session-review.json` retains the failed outcome, successful
component evidence and the complete raw Workflow notification/output for the
subsequent narrow compatibility correction and a separate fresh retry.

## Native full workflow completed after the notification correction

The fresh disposable run
`.local/desktop-session-validation/20261103T070733335115Z/` completed in
**13m 37.025s** on November 3, 2026, from **10:10:06 to 10:23:43 Moscow time**.
The genuine Desktop Code 2.1.309 worker was bound to Desktop session
`local_f042a42b-e0ab-47b3-ab65-c1faeb3c19d7` and CLI transcript
`40810a7f-5399-4937-a31a-82274b8da4b5`. The gateway revision was
`ecc16d0777f3d4a5a4ff601a8d5ae094cfe945001d34e613dcf4470fd3b989d7`.
This was one completed native turn, with the frozen test initially RED,
Qwen 3.8 27B on subscription, native high mapped to provider xhigh and Auto
permission checks enabled.

| Native evidence | Observed result |
| --- | --- |
| Automatic Desktop title | The configured Qwen 3.6 35B A3B noreason subscription helper returned in **1.816 s**. Desktop saved the automatic title. |
| Dynamic Workflow | One builtin call with the frozen script, task `w5fstt321` and run `wf_9dc9ce90-467`. Both journal starts preceded the first result, and each reviewer performed only its assigned Read. The successful child API intervals overlapped by **38.523 s**, measured from gateway receipt to response finish. |
| MCP | ToolSearch discovered `search_quota`. A single subscription call succeeded while the Workflow was running. |
| Completion delivery and Edit | The native notification was absorbed at **10:15:52**. The next coordinator response cited `READY_TO_INTEGRATE` and both review findings, then successfully called Edit on `calc.py`. |
| Real tests and completion | Native Bash ran `python -m unittest -v` and returned **2 tests, OK**. The coordinator wrote `DESKTOP_SESSION_DONE.json` and its final response ended with `DESKTOP_FULL_WORKFLOW_OK 5050`. |
| Isolation and permissions | The frozen test and Workflow files and all five settings hashes matched. Three tool-result classifier boundaries accepted. No safety classifier timeout or stream watchdog fired. Desktop logged a healthy completed cycle and gateway active requests returned to zero. |

The receipt status is **PASS_NATIVE_FULL_WITH_PROVIDER_RETRIES**. The run
demonstrated the full native sequence and recovered from **eight** upstream
overload responses. Native diagnostics recorded six stream errors and two
nonstream fallback errors. Five of those responses affected the test reviewer:
three stream attempts and two nonstream attempts, with a 15-second backoff
after each failed nonstream attempt. The third nonstream attempt succeeded in
103.184 seconds. The remaining three responses affected coordinator streams.
The requests matched the gateway's upstream execution path and native
`overloaded_error` reports, corresponding to upstream HTTP 503. The finer
provider cause was not present in the diagnostics. There was no manual retry,
model or effort change, permission bypass, or corrective prompt within the
turn. A retry-free run is still unverified.

The private run directory contains `native-session-review.json` with all
14 functional gates and the eight matched gateway/native overload attempts.
`live-native-observation.json` records both child bindings, native journal,
notification and actual tool results. `artifact-review.json` records an
independent green test rerun and the unchanged settings and fixture hashes.
