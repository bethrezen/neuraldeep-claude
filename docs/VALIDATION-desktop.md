# Native Desktop validation

Checked 2026-11-02, Claude Desktop Debian package 4.4212.0.

## Latest result: startup under the no-Anthropic policy

The native **Claude Desktop 4.4212.0** application passed the later bounded
startup with the offline native settings and dedicated guard. It accepted
**117 model/billing/effort entries**, registered **14 NeuralDeep MCP groups**,
activated local gateway mode, and logged **provider health `healthy`** at
20:00:18 Europe/Moscow, three seconds after launch. The first configured route
remains the exact subscription Qwen route. This is startup/parser and built-in
provider-health evidence; interactive picker clicks and visual usability remain
unverified.

This run used a real kernel network boundary: a new `bwrap --unshare-net`
namespace with **only `lo`**, a private PID namespace, private `/run` and `/tmp`,
a private D-Bus session, and only an owned Xvfb Unix display socket imported.
The Unix bridge could reach only host loopback **8787 and 18790**. Native
execution started only after namespace verification. The trace shows **zero
successful or pending non-loopback connections**; eleven non-loopback IPv6
`connect` syscalls to `[2001:4860:4860::8888]:443` failed with `ENETUNREACH`.
The trace did not capture socket creation/type: these are consistent with a
Chromium IPv6 route probe, but are not classified as proven UDP or TCP traffic.
See the [read-only forensic scope](research-offline-desktop.md#read-only-interpretation-of-the-ipv6-syscalls).
The host guard recorded **zero accepted external
connections** during the observed interval. Twelve first-party destination
attempts in the guard slice were rejected locally before upstream resolution.
Shared guard/gateway slices can include concurrent checks, so those event counts
are interval evidence, not an attribution of every event to this app.

The successful run is
`.local/desktop-validation/offline-20261102T170015318922Z/`:

- `receipt.json`, SHA-256 `e57c19d83a11ec852a12cf94d67dbd5450fbbcdd0adbe8450dfab8d97c848d0c`.
- `native-main.log`, SHA-256 `9ff8145cfb5f3649d851a99d6b7e3e4e4c009b058bcb286e3ba1d131b4687e94`.
- `strace.log`, SHA-256 `8ea1e0e8ebcc85085412861d65abacef5a28480b732f2455373e41cc04655b89`.
- `namespace.json`, `bridge-events.json`, `connect-summary.json`, and
  `evidence-summary.json` preserve the boundary and derived checks.
- `probe-offline.py.snapshot`, `driver.py.snapshot`, and `desktop.py.snapshot`
  preserve the exact source revisions matching the receipt's hashes.

The native profile's SHA-256 at startup was
`dd98c9a4137621b759158d8d07db0f099e8b5c74e2b1b347660af96b7dfd2735`.
The unchanged native `app.asar` SHA-256 was
`58ad49c6bf569d433b2dbf4809e0d4f29c2a2166bcadd94153935c680217c102`.
The receipt binds the test driver, bridge helper and Desktop integration source
hashes as well.

Two earlier namespace-only failures are retained: the nested SUID-sandbox
failure at `offline-20261102T165756818260Z` and the native rejection of an
unsupported DNS override flag at `offline-20261102T165832763401Z`. The successful
test used **test-only `--no-sandbox` inside the outer kernel namespace** to
accommodate the nested Electron SUID restriction. The production launcher does
**not** use `--no-sandbox`. The native signature and signed-harness gate were not
modified. All owned native/Xvfb process groups and the bridge socket were
removed after the bounded run; no native Desktop process remained.

The shared relay `127.0.0.1:20171`, its upstream `nl.notevil.ai:8888`, independent
settings/service/script, unrelated service on `8790`, and Codex/ChatGPT proxies
were untouched. The hard network boundary above belongs to this bounded
experiment. Ordinary proxy-aware production launch is not an OS firewall for
arbitrary child tools; see the [network scope audit](research-offline-desktop.md).

## Earlier startup before the network-policy change

The evidence below preserves the earlier native startup, before the user
prohibited all Anthropic network requests. Its `--no-proxy-server` launch was
replaced by the separate per-Claude guard and offline native settings. These
historical logs are not evidence for the later network policy.

The final native Desktop configuration loaded **all 117 model/billing/effort options and all 14 NeuralDeep MCP groups**. There were **zero model-name rejections**. Its first configured route resolves exactly to **`nd/qwen3.8-27b@subscription`**, under the label `[ПОДПИСКА] qwen3.8-27b · ctx 262144`. Gateway third-party mode activated successfully.

This is startup/parser evidence. The built-in inference connection probe timed out and ended as **`not_testable`**, so provider-health verification did not pass in this test. Interactive model selection, screenshots, native tool calls, subagents, workflows, and compaction remain outside this bounded startup validation.

## Earlier evidence

The earlier bounded run started at approximately 18:37:49 Europe/Moscow. The application logged:

- `Credentials loaded { configSource: 'local', provider: 'gateway', mcpServerCount: 14 }`
- `3P mode active { provider: 'gateway' }`
- `picker = 117 (inferenceModels)`
- At 18:38:09, `ConfigHealth recomputed { state: 'not_testable', provider: 'gateway' }`

The bounded log slice is `.local/desktop-validation/final-health-startup-main.log`, SHA-256 `ea18942b8d62d8a736d0890da626e289daaa7522f01287331a994003c13442bb`. The machine-readable receipt is `.local/desktop-validation/final-health-validation-result.json`. It records the configured default, option counts, elapsed time, process IDs, cleanup and exact relevant log records.

## Why opaque routes are necessary

The original direct IDs failed the native filter: 82 of the earlier 85 options were removed, including Qwen subscription; the three surviving routes were wallet Claude models. Leaving that version installed could have allowed a wallet model to become the default after the subscription row was discarded.

Inspection and a separate bounded startup established that native filtering looks only at a route's name. It ignores `behavesAs` during that filtering and explicitly rejects known non-Claude family words, even inside a name beginning with `claude-`. Thus `claude-neuraldeep-qwen3.8-27b-subscription` and `nd/qwen3.8-27b@subscription` with a Claude `behavesAs` both failed.

The final integration exposes opaque **Anthropic-format protocol routes**, `anthropic/neuraldeep/<numeric digest>`. `catalog.gateway_alias` computes them deterministically for the complete original row, including its billing and explicit effort. The gateway resolves them back to the exact original NeuralDeep ID before invoking the provider. Labels keep the real model, billing badge, effort and actual published context. Non-Claude models receive **no false `behavesAs`** or edited Anthropic model catalog. Genuine Claude models can retain their own known native identity.

A Desktop integration test checks every generated option against its original row for model ID, billing and selected effort. The actual native startup then accepted all 117 routes. This establishes that the name-filter problem is resolved for this installed build; it does not establish correct per-model native numeric context metadata or full runtime compatibility.

## Earlier provider health probe

The initial opaque-route test reached an old gateway process that had not reloaded the new resolver; a read-only local `count_tokens` call confirmed HTTP 400 for the new route. After that gateway was restarted, the same local alias resolved correctly. Subsequent native startup had no name rejections but its real provider probe did not finish inside the native timeout.

Read-only source inspection shows that native startup sends an automatic `/v1/messages` connection probe with `max_tokens: 1`, and uses a 10-second health timeout with one retry for an unreachable result. A responsive gateway with an inference timeout is classified `not_testable`. That earlier verdict appeared after 20.41 seconds; the latest namespace run above instead reached `healthy`. No manual task prompt was entered, but these native connection probes are real model requests and can consume quota. Earlier blanket statements that startup performed no inference are superseded by this finding.

## Execution environment and cleanup

The task environment exposed no display or desktop bus. Xvfb was downloaded from the configured official Ubuntu apt repository, package `2:21.1.22-1ubuntu1.3`, and extracted under `.local/desktop-validation/tooling/`; no system package was installed. The tests used virtual display `:77`, 1280×900, TCP listening disabled, and a dedicated `dbus-run-session`. They launched the real `/usr/lib/claude-desktop/claude-desktop` with `--no-proxy-server` and `--ozone-platform=x11`.

The initial test's `CLAUDE_USER_DATA_DIR` override did not produce an isolated application store in this packaged build: actual logs and runtime files appeared under the primary `~/.config/Claude-3p`. The source-based isolation assumption is therefore unverified and must not be relied on for protecting a running user session. No other native Desktop process was present before these tests. Later runs deliberately tested the activated primary profile.

Test application and Xvfb process groups were terminated after each bounded run. No existing user session, history or open native tab was closed. The main persistent configuration keeps the final 117 opaque routes and 14 service connectors.

That historical startup used eager MCP tools. The current adapter now supports the actual client `ToolSearch` / `defer_loading` / `tool_reference` path, and both clients enable it. A real native CLI lifecycle passed; see [research-tool-search.md](research-tool-search.md). Hosted Anthropic server search remains unsupported and is not needed for this client path. The current Desktop profile uses gateway discovery with no `inferenceModels` allowlist; the earlier 117 explicitly configured routes above are historical evidence, not proof of current discovery UI. `desktop.sync_services` preserves unrelated connectors and retained tool policies. A reload or new session is needed to connect newly enabled servers.

CUA exposes no native applications in this environment and requires CUA for UI interactions. Raw CDP/Playwright control was not substituted, and the packaged app's remote-debugging gate was not bypassed. Therefore `ui_verified` remains false. Virtual-session keyring/renderer diagnostics also preclude a visual-usability claim from the startup logs alone.

## Current result

| Requirement | Result |
|---|---|
| Read local gateway credentials and activate 3P mode | PASS at startup |
| Accept every configured model/billing/effort option | PASS: 117 accepted, zero filtered |
| Preserve subscription Qwen as first actual configured route | PASS: accepted opaque route resolves exact subscription ID |
| Load independently configured NeuralDeep service connectors | PASS at configuration load: 14 groups |
| Native built-in inference connection health | PASS: `healthy` in latest namespace run; older timeout retained above |
| No successful external native connections in latest bounded startup | PASS: kernel netns, trace and guard audit; only fixed host loopback bridge |
| Permanent OS-level network policy for ordinary production Desktop | Not established; proxy-aware launch controls are not an OS firewall |
| Arbitrary native per-model context and effort metadata | Limited by the public schema; explicit effort variants are available |
| Native interactive selection, tools, subagents, compaction, workflows | Not established by this startup check |
| Installed `/nd-design` and `/nd-workflow` files | Skills validate; native Desktop execution not established here |

CLI live checks and individual service API checks are separate evidence and must retain their own scope.

## Portable launch and activation

`desktop prepare` creates reviewable configuration files only. `desktop launch` now requires the explicit main-activation marker and fails clearly if `install --activate` has not been run; it no longer tries the unverified packaged-app profile-isolation mechanism.

On another computer, install the native Claude Code and Claude Desktop applications, place the NeuralDeep keys in the portable checkout's `.env`, then run:

```text
python scripts/nd.py install --activate
python scripts/nd.py desktop launch
```

The integration installs a gateway-aware Desktop launcher for each supported operating system:

- Linux: `~/.local/bin/claude-desktop`; the inspected existing desktop menu entry already uses this path.
- macOS: `~/Applications/Claude NeuralDeep.command`.
- Windows: `%LOCALAPPDATA%/NeuralDeep/bin/Claude NeuralDeep.cmd`.

These launchers refresh the catalog, start the local gateway if needed, and then launch the real native application. After a fresh reboot, use the generated launcher or the portable `desktop launch` command. Starting a stock macOS Dock/Windows app shortcut alone does not create the local gateway process. No automatic login service, LaunchAgent, or scheduled task is installed. macOS/Windows launcher generation and executable selection have unit coverage; native runtime on those systems was not exercised on this Linux host.
