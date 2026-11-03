# Desktop without Anthropic network traffic

The user's later requirement forbids requests to Anthropic, including background traffic. This supersedes the earlier choice to retain background telemetry and update behavior. The shared proxy relay on `127.0.0.1:20171`, its upstream `nl.notevil.ai:8888`, its independent configuration, and Codex/ChatGPT proxy settings are outside this change's scope.

## Native settings verified in the installed source

The inspected application is Linux Claude Desktop **4.4212.0**. Its unchanged `/usr/lib/claude-desktop/resources/app.asar` has SHA-256 `58ad49c6bf569d433b2dbf4809e0d4f29c2a2166bcadd94153935c680217c102`. The configuration schema and its consumers are in `.vite/build/index.chunk-CvhJZ02X.js` inside that archive. Inspection did not modify the native program or its signatures.

The generated native configuration now explicitly sets:

| Flat setting | Value | Purpose |
| --- | --- | --- |
| `disableEssentialTelemetry` | `true` | Suppress native crash/error telemetry. |
| `disableNonessentialTelemetry` | `true` | Suppress usage telemetry and diagnostic uploads. |
| `disableNonessentialServices` | `true` | Suppress hosted preview/widget assets, icon lookups, and dictionary downloads. |
| `disableAutoUpdates` | `true` | Suppress the native updater. |
| `installedUpdateEnforcementEnabled` | `false` | Avoid enforcing previously downloaded updates. |
| `modelCatalogEnabled` | `false` | Use bundled model metadata instead of downloading Anthropic's signed catalog. |
| `disableDeploymentModeChooser` | `true` | Hide the alternative Claude.ai sign-in path. |
| `bootstrapEnabled` | `false` | Disable bootstrap configuration fetching. |
| `skipWebFetchPreflight` | `true` | Avoid the first-party domain preflight for WebFetch. |

The local gateway remains the inference provider, with explicit static credentials and no Anthropic API key in the Desktop profile. Existing model/billing/effort entries and all enabled local MCP groups remain configured. The native profile contains only the local gateway token, never upstream NeuralDeep keys.

These keys are described in the [official Desktop configuration reference](https://claude.com/docs/third-party/claude-desktop/configuration). That reference also identifies `egressProxyUrl` as an MDM-only app-behavior setting. A value in a local config library is therefore insufficient evidence that all native traffic follows it. The launch path must enforce its separate guard independently.

## Effect on features

Suppressing hosted preview and widget frames is required by the network boundary. Local HTML/code/assets, `/nd-design`, direct NeuralDeep image tools, local MCP tools, and text fallbacks remain available. Claude.ai authentication, native Anthropic Design, cloud synchronization, Anthropic-hosted metadata, telemetry and updates cannot be treated as usable network capabilities under this requirement. The bundled signed model catalog remains intact; no fabricated replacement is installed.

## Guard and verification boundary

The per-Claude guard is a separate local listener on `127.0.0.1:18790` (the canonical `egress.DEFAULT_PORT`); it is unrelated to the shared relay. Port `8790` belongs to an existing unrelated host service and is not used by this guard. `desktop.launch` calls `egress.ensure` and `egress.guard_environment` before spawning the native app. Failure prevents the spawn. NeuralDeep and loopback are explicit direct bypasses. Chromium receives an explicit guard proxy and disabled QUIC. Extra app arguments cannot override the proxy, bypass list, PAC or QUIC setting. A guard URL pointing at the shared relay, old port, or another host is rejected. Proxy variables and offline flags belong only to the newly launched Claude process and do not mutate the parent environment or other applications' configuration.

An initial namespace-only startup exposed a native compatibility constraint: packaged Desktop rejects `--host-resolver-rules` and `--host-rules` before application initialization unless an Anthropic-signed test harness authorizes them. The exact rejection and switch list are in `index.pre.js` (`YZ`/`qZ`). The implementation therefore omits these unusable DNS switches and rejects caller overrides. `--proxy-server`, `--proxy-bypass-list` and `--disable-quic` are not in that rejection list. Domain denial belongs to the separate proxy guard; no native signature or harness was bypassed.

The launcher also refuses to start while native Desktop processes exist: Electron could forward a second launch into an old unguarded instance and ignore the new launch arguments. The check reads process names with `ps` on Linux/macOS. On Windows, where the CLI and Desktop can both be named `claude.exe`, it reads only CIM process name, PID and executable path and compares normalized exact Desktop executable paths. CLI processes in another directory do not block Desktop. Command lines are neither requested nor logged. It does not kill processes. If process inspection or a matching process's path is unavailable, startup fails clearly instead of assuming that the instance is protected.

Settings, proxy variables and Chromium flags alone do **not** establish an operating-system network boundary for arbitrary Node/Bun sockets, extensions, shell tools, SSH hosts or Cowork VMs. A process that ignores proxy variables can bypass a local HTTP proxy. This limitation must remain explicit until an actual enforced process/network policy and bounded runtime network evidence cover those paths. Historical pre-change startup logs that show Anthropic requests cannot validate this later policy.

Desktop must not be started for validation before the guard is ready. All **21 Desktop unit tests pass**, including source controls, failure-before-spawn, platform-specific process inspection, Windows CLI/Desktop executable-path separation, restricted proxy arguments, direct NeuralDeep/loopback bypass, parent-environment preservation, and independent relay/Codex/ChatGPT sentinel files. These tests mock the guard and native process creation, so they do not prove runtime network enforcement. The later bounded native run below supplies separate runtime evidence. A locally denied attempt is distinct from an upstream request.

## Bounded native startup with a kernel network boundary

The final run is `.local/desktop-validation/offline-20261102T170015318922Z/`. Its original `receipt.json`, `namespace.json`, `native-main.log`, `strace.log`, bridge audit and event slices are preserved. `evidence-summary.json` binds the receipt/main-log/trace hashes and records the derived checks. The native run began at **20:00:15 Europe/Moscow** and was terminated after the 40-second bounded observation, with the owned process groups and bridge removed.

The real app ran only after the probe verified a new Linux network namespace with **only `lo`**, separate from the host. A private PID namespace ensured child cleanup. Private `/run` and `/tmp` hid unrelated host IPC; the sole imported display socket belonged to an owned Xvfb started with TCP listening disabled. The D-Bus session was created privately inside the namespace. A mode-600 Unix bridge exposed only host loopback **8787 and 18790**. No native app ran outside this boundary.

The app accepted **117 model/billing/effort entries**, registered **14 NeuralDeep MCP groups**, activated gateway mode, and logged **`ConfigHealth: healthy` at 20:00:18**. This supersedes the earlier `not_testable` provider-health result. It does not prove interactive picker use, native tool calls, native agent/workflow execution, or visual rendering.

The trace contains 21 non-Unix connect attempts: ten to the two permitted loopback ports and eleven failed IPv6 attempts to `2001:4860:4860::8888:443`. There were **zero successful or pending non-loopback connections**. The guard event slice records **12 locally denied attempts**: three for `platform.claude.com`, nine for `downloads.claude.ai`; no guard-side external connection was recorded. These are blocked attempts, not requests delivered to Anthropic. The kernel namespace independently prevented a raw-socket escape during this test. Shared gateway/guard event slices can include concurrent validation, so native provider health is bound to the native app's own bounded log rather than an inferred global request count.

The first two failed attempts are retained separately: `offline-20261102T165756818260Z` stopped on the nested Electron SUID-sandbox requirement before app initialization; `offline-20261102T165832763401Z` exposed the forbidden DNS override switch. The successful test used **test-only `--no-sandbox` inside the stronger outer namespace** to accommodate that nested SUID restriction. The production launcher does not add this flag. No native artifact, signature, or signed test-harness authorization was modified.

The tested hard boundary belongs to this explicit namespace experiment. Ordinary production launch still has the proxy-aware-path limitation stated above; this test must not be presented as a permanent OS firewall for every future Claude process.

## Read-only interpretation of the IPv6 syscalls

All eleven non-loopback `connect` calls targeted exactly
`[2001:4860:4860::8888]:443` and returned `ENETUNREACH`, from traced thread 62.
This is the familiar Google Public DNS IPv6 address, not an observed NeuralDeep
or Anthropic route. The installed native executable contains the exact address
literal at file offset `0x13b9eaa` and the Chromium event name
`HOST_RESOLVER_MANAGER_IPV6_REACHABILITY_CHECK`. Their presence and the immediate
subsequent connections to the intended loopback endpoints are consistent with
Chromium's IPv6 reachability/routing probe. This is an inference, not a decoded
call stack.

The saved trace records `connect` and `getsockopt` only. It does not record
`socket`, `getsockname`, or payload-send calls, and no `SO_TYPE` result exists for
the relevant thread/file descriptors. Therefore it cannot establish whether
these were UDP route probes or TCP connection attempts. A UDP `connect` can
perform only a local route/source-address selection; the port number alone is
not proof of HTTPS or an emitted packet. The result must remain “failed IPv6
connect syscalls, transport/purpose not conclusively established.” No additional
network calls or native launches were made to investigate them.

The exact native Sentry initialization host was also recovered read-only from
`index.pre.js`: `o1158394.ingest.us.sentry.io`. The native egress schema lists
`sentry.io`, `*.sentry.io` and `*.ingest.us.sentry.io`. The canonical guard now
denies the `sentry.io` suffix and the exact initialization host, in addition to
the native telemetry-off settings. This subsequent source tightening has not
been represented as a new native runtime test.

A literal guarantee that no future Desktop component or arbitrary child ever
contacts Anthropic still requires a persistent operating-system egress boundary.
The production proxy controls alone are insufficient authority to activate or
run an unisolated Desktop while claiming that guarantee. The bounded namespace
evidence does not remove that requirement, regardless of the likely benign
purpose of the Google-address probes.

The user subsequently explicitly selected configuration plus filtering **without
persistent OS isolation**, accepting the native-helper boundary. Production
launch follows that chosen proxy-aware mode. This acceptance does not turn it
into an OS firewall or broaden the bounded namespace evidence.
