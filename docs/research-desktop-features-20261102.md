# Native Desktop feature controls — 2026-11-02

This report records read-only source inspection of installed Claude Desktop
4.4212.0. No native application, VM, browser session, Anthropic request, or shared
proxy was started or changed for this inspection.

Source: `/usr/lib/claude-desktop/resources/app.asar`, SHA-256
`58ad49c6bf569d433b2dbf4809e0d4f29c2a2166bcadd94153935c680217c102`.
Locations below are decoded UTF-8 character offsets in the named ASAR member,
not source line numbers. Private extracted research copies are in
`.local/desktop-validation/extracted/` and are not installation inputs.

## Exact controls

| Requested setting | Native flat configuration key | Meaning / dependencies |
| --- | --- | --- |
| Model discovery | `modelDiscoveryEnabled: true` | Gateway provider reads its own `/v1/models`; omit `inferenceModels` to let discovered rows determine the complete picker. |
| Use 1M wherever it is available | `modelPrefer1mContext: true` | Applies `prefer1m` to rows already known to support at least 1M. It does not expand a smaller model's context. |
| Show estimated cost | `inferenceModelPricingEnabled: true` | Passes configured prices to the local Claude Code engine, which reports per-turn estimates. |
| Model pricing | `inferenceModelPricing: [...]` | Each entry requires `name`, `inputPerMtok`, `outputPerMtok`, `cacheReadPerMtok`, and `cacheWritePerMtok`. All four rates must be finite numbers in `[0, 10000]`. |
| Model catalog metadata | `modelCatalogEnabled: true` | This is the actual UI title corresponding to the user's “Model cache metadata”. Uses a bundled seed plus an optional signed downloaded catalog. |
| Enable tool search | `toolSearchEnabled: true` | Local gateway mode normally enables the local CLI `ToolSearch` protocol; gateway must preserve deferred tool definitions and hydrate tool references. |
| Allow the built-in browser | `builtinBrowserEnabled: true` | Enables the native browser surface and tools; public-site safety classification still depends on Anthropic. Local previews do not need that classification. |
| Advanced file analysis | `chatAdvancedFileAnalysisEnabled: true` | Enables Chat's analysis shell only when Chat is enabled, Bash is allowed, and its VM backend is supported and usable. |
| Code shell sandbox | nested Claude Code `sandbox.enabled: false` | This is a Claude Code setting, not a Desktop flat configuration key. See sandbox details below. |

Relevant schema: `.vite/build/index.chunk-CvhJZ02X.js` offsets
`742000–752100`, `723300–724550`, `783100–783900`, and
`822300–824850`. `inferenceModelPricingMultiplier`, when supplied, must be
strictly positive and at most 1. The price schema makes all four rate fields
required; omitting an unpublished rate does not produce a valid native entry.
The installer must choose a truthful accounting policy for a missing price
rather than pretend the field is optional.

`chatTabEnabled: true` should accompany advanced analysis. `desktopHome: "off"`
disables Chat and analysis; `"no-vm"` also disables analysis. `"standard"` grants
Chat, analysis, and Cowork, and `"simple"` grants Chat and analysis. Leaving
`desktopHome` unset permits explicit per-surface switches. Native
`secureVmFeaturesEnabled` user preference defaults to true; a false preference
also prevents advanced analysis. To override an existing user opt-out, merge
`preferences.secureVmFeaturesEnabled: true` into
`<Desktop userData>/claude_desktop_config.json`. This is separate from the
`configLibrary` third-party profile and from Electron's `config.json`.
The native `Qv` / `iy` / `$b` readers, offsets `1694877–1698590` and
`2039118–2041220`, establish that path. Its enterprise flat field is scoped to
first-party mode and should not be treated as a new third-party override.
The same user preferences include `coworkBrowserToolsEnabled: true` and
`coworkPreferredBrowser: "built_in"` by default.

## Discovery parser and automatic refresh

Gateway `Jfn` / `Yfn`, in `index.chunk-CvhJZ02X.js` offsets `2450240–2452960`,
requests `/v1/models?limit=1000`, follows at most three pages, and follows another
page only when `has_more === true` and `last_id` is a string. The document must
contain an array in `data`.

The gateway discovery consumer accepts these row properties:

- `id`: sanitized to a displayable identity and subjected to native model checks.
- `display_name`: display name, sanitized to at most 255 characters.
- `description`: sanitized to at most 100 characters.
- `supports_1m`: boolean; if absent, `max_input_tokens >= 1000000` implies 1M.
- `anthropic_family_tier`: a recognized Claude tier, and optionally
  `is_family_default: true`.

The gateway consumer does **not** read `behaves_as`, `max_effort_level`,
`prefer_1m`, `max_output_tokens`, arbitrary numeric context metadata, model
capability arrays, or pricing from this endpoint. A separate parser `zfn` reads
some of those fields for other provider/host listing paths; it is not called by
gateway `Yfn`. Extra gateway extension metadata is useful for this project's
tools, but must not be described as understood by the native Desktop picker.

Native `Uo` rejects non-Claude family substrings in model IDs even when an ID
also contains `anthropic`. Opaque `anthropic/neuraldeep/<numeric digest>` IDs
pass without falsely assigning a Claude family to Qwen, GPT, or Gemini. The
project's truthful model/billing/effort names belong in `display_name` and
`description`; distinct effort routes remain individually selectable.

`nRn`, at offsets `2979000–2981700`, is important: **any nonempty
`inferenceModels` list becomes the entire picker**. It is not a sparse metadata
overlay. Discovery may contribute names/descriptions to those configured rows,
but newly discovered rows are not appended. Therefore omit `inferenceModels`
when using automatic discovery. The global 1M preference applies only to
`supports1m` rows after discovery.

## Catalog metadata without Anthropic traffic

`modelCatalogUrl` exists and its local configuration schema permits HTTPS, or
HTTP on loopback. The remote policy has a stricter loopback rejection; that is
separate from the local configuration parser.

The native explicitly recognized no-fetch sentinel is:

```json
{
  "modelCatalogEnabled": true,
  "modelCatalogUrl": "https://model-catalog.invalid/unreadable"
}
```

`tln` at offsets `2351460–2351930` turns that sentinel into an invalid catalog
location. `runRefresh` in `.vite/build/index.chunk-B3ssbVLN.js`, offsets
`4390–5290`, publishes the bundled seed before inspecting the location, skips
the fetch for an invalid location, and publishes again. Therefore this control
can remain enabled with shipped metadata, without an attempted connection to
Anthropic or to the sentinel host.

The bundled seed in this installation is schema version 1, catalog version
3373, issued `2026-10-29T05:58:15Z`, expiring `2026-11-05T05:58:15Z`.
It contains Claude metadata, not this project's opaque NeuralDeep identities.
Its expiry is reported by the native snapshot; it does not turn an unsigned
custom catalog into acceptable input. Updating Desktop may replace the seed.

Downloaded catalogs require an accompanying `.raw-sig.json` and verification
against the hardcoded `claude-code-release-signing-key`, using signing context
`claude-code-model-catalog-v1\0`. `index.chunk-B3ssbVLN.js` offsets
`731–1300`, `5300–7200`, and `10400–11400` establish the trust roots, signature
requirement, and reader setup. No configuration field for an additional trust
root was found. A local unsigned catalog containing custom Qwen/GPT/Gemini
metadata would be rejected. Do not forge an Anthropic signature or silently
patch the installed app to bypass validation.

The offline sentinel is a truthful supported fallback: “catalog metadata
enabled, bundled Claude metadata only”. It does not prove numeric native
metadata support for all NeuralDeep models. Actual per-route context limits
remain the gateway/catalog's responsibility.

## Built-in browser and the no-Anthropic rule

The native setting is usable for localhost previews and appropriate local
files. Public sites have an additional dependency that cannot be satisfied by
NeuralDeep API credentials.

In local third-party mode, `authenticatesHostedSiteCheck()` returns false.
`i8n` at offsets `3246050–3247450` POSTs the site URL to:

```text
https://releases.claude.com/api/web/url_hash_check/browser_extension?anonymous=1
```

`skipWebFetchPreflight` only becomes the CLI `skipWebFetchPreflight` setting
through `j4t` at offsets `2159540–2160100`; it is not consulted by this browser
site-classification path. No supported site-check URL or skip override was
found in the installed native schema/consumer.

The logs use “failing open” for some classification failures, but that must not
be mistaken for successful tool access. `o9n` at offsets `3273200–3273900`
converts a classification error to `kind: "unavailable"`; `vAi` at offsets
`4735200–4736700` maps it to `verdict: "blocked-unavailable"`. `v1` retries three
times at 30-second intervals. Localhost returns `kind: "loopback"` before this
classification call, and files inside the admitted local root can be allowed
before it.

Enabling `builtinBrowserEnabled` is compatible with the existing egress guard.
The guard must continue blocking Anthropic, including this releases endpoint.
The resulting supported native functionality is local preview, not verified
public-site browsing. Public browsing should use a separately configured
NeuralDeep-compatible/browser MCP route if available; that is not the same
native browser switch. Persisting an allowed-site list does not constitute a
supported bypass of the mandatory classification path.

## Code sandbox versus Chat's analysis runtime

Native Desktop reads Code settings with `YI`, `f2n`, and `p2n` at offsets
`3200560–3201230`:

- `sandbox.enabled` maps to the displayed `sandboxEnabled` result.
- `sandbox.allowUnsandboxedCommands` is inverted to produce the displayed
  `strictSandboxMode` result.
- `sandbox.failIfUnavailable` is consulted when sandboxing is enabled/required.

`sandboxEnabled` and `strictSandboxMode` are resolved UI result properties, not
supported Desktop flat configuration keys to write into a deployment profile.
For an unrestricted Code shell, use `sandbox.enabled: false` and
`sandbox.allowUnsandboxedCommands: true` in actual Claude Code settings. A
generated enforced launch/settings layer may be needed if project-local
settings would otherwise re-enable it; this report does not prescribe an
unsupported environment variable.

There is a second forcing path. `D4t` at offsets `2157920–2159150` sets
`sandbox.enabled = true` when it generates a managed network restriction or
filesystem restriction. In third-party Desktop those originate from the
non-wildcard `coworkEgressAllowedHosts` policy or an `allowedWorkspaceFolders`
restriction. To keep Code Bash sandboxing disabled, use
`coworkEgressAllowedHosts: ["*"]` and do not impose a workspace folder
allowlist. This does not remove the independent per-Claude no-Anthropic guard.

Native Chat advanced analysis intentionally runs shell commands in an isolated
analysis runtime. `aFe` at offsets `796900–797120` requires Chat, file-analysis,
and an allowed Bash tool. `XWr`, at offsets `3944250–3944800`, then requires a
supported VM backend and the secure-VM user preference. The session environment
in `.vite/build/index.chunk-BK_sL6Pi.js` offset `260900` computes
`chatAdvancedFileAnalysisEnabled` from that result and requests VM startup;
offsets `431200–432200` permit shell tools and build a Chat-specific system
prompt accordingly.

Thus Code Bash sandbox off and Chat analysis on can coexist. Claiming that all
VMs are disabled while claiming native Chat advanced analysis works would be
contradictory. The user subsequently clarified that the analysis VM should be
preserved while Code and Electron sandboxing should be disabled. Electron
Chromium `webPreferences` also hardcode their own renderer sandbox; a supported
Electron launcher flag is a separate control from Code's nested sandbox
settings. This research did not patch renderer preferences or installed
binaries, and did not validate the launcher's Electron sandbox state.

## Linux host prerequisite observation

Read-only filesystem observation on this host, 2026-11-02:

- Ubuntu 26.04.1 LTS, x86_64, kernel `7.0.0-38-generic`.
- `/usr/bin/qemu-system-x86_64`, `/usr/share/OVMF/OVMF_CODE_4M.fd`, and
  `/usr/libexec/virtiofsd` exist and are usable.
- Packaged `cowork-linux-helper`, `virtiofsd`, and `smol-bin.x64.img` exist.
- `/dev/kvm` is readable and writable by the current user.
- `/dev/vhost-vsock` exists as `crw-rw----`, owned by root/group 992; the current
  user has neither read nor write access and is not a member of that group.

The source Linux probe `eGn` at offsets `3077150–3077500` maps `EACCES` on
either `/dev/kvm` or `/dev/vhost-vsock` to `no_permission`. `xWr` at offsets
`3938800–3941350` then reports `unsupportedCode: "kvm_permission_denied"`.
Consequently the analysis switch can be installed correctly while this host's
native analysis backend remains unavailable due to OS permissions. No device
permissions, groups, kernel modules, global services, or native binaries were
modified. Loading the native binding to check its required
`connectUnixSocketSameUid` export or booting a VM was not performed; filesystem
prerequisites alone are not an end-to-end Chat analysis pass.

## Tool search consumer

`f4t` / `h4t`, offsets `2152620–2154900`, select native third-party gateway
tool-search mode. When enabled and not host-managed, mode is `legacy`, setting
`ENABLE_TOOL_SEARCH: "true"` and leaving experimental betas enabled for the
local CLI's search protocol. With a host that explicitly honors host tool
search, mode is `host`; `D4t` then sets `ENABLE_TOOL_SEARCH: "force"` in managed
settings. Chat sessions also include the local `ToolSearch` tool in their
allowed tools.

This is not proof that arbitrary upstream models understand deferred tool
references: the gateway adapter must test and implement tool-reference
hydration. Enabling the switch alone is not a functional test.

## Repeatable isolated native validation

`python scripts/probe-desktop.py` prints a dry-run plan on every platform.
`python scripts/probe-desktop.py --execute --duration 60` runs the bounded native
startup test on Linux when `bwrap`, `strace`, `dbus-run-session`, Xvfb, and
ImageMagick `import` are available. It requires the already running local
gateway and private guard; it does not stop, install, restart, or reconfigure
either of them.

The probe refuses an existing Desktop instance. It binds private copies of the
two native configuration profiles over their original paths inside the private
mount namespace and exposes only the two fixed loopback bridge ports. It does
not use a signed-harness bypass or a remote-debugging flag. The actual native
log must say that the full picker came from `discovery`; the former
`inferenceModels` startup line cannot pass that requirement. The receipt
separates static installed feature settings, actual native startup log
evidence, and captured UI images. It does not label screenshots as a reviewed
UI pass automatically.

Each run prints a private evidence directory under
`.local/desktop-validation/features-*`. It captures the actual local
`/v1/models` response, native logs, connect trace, bridge/guard events, owned
Xvfb screenshots, exact source snapshots/config hashes, and a receipt. No user
prompt or analysis VM start is requested. Native Desktop may validate its
static gateway credentials with a one-token subscription inference; this is
explicitly recorded rather than described as an inference-free startup.
Interactive UI actions are deliberately not attempted: the available
computer-use surface has native app control disabled, and this probe does not
bypass that boundary through X11 input injection or a remote-debugging flag.
Screenshots remain read-only evidence, and `ui_verified` remains false without
an actual permitted picker review.

`tests/test_probe_desktop.py` checks that dry runs and unsupported-platform
execution cannot launch native processes, a live instance blocks before any
health request, configured-model counts cannot substitute for actual discovery,
native configuration rejection cannot be hidden by a matching count.

### Recorded execution

Run `.local/desktop-validation/features-20261102T175346552383Z` used the
installed generated configuration and actual gateway response. The native log
reported `117 found in 57ms; picker = 117 (discovery)`, `ConfigHealth` healthy,
bundled metadata seed 3373, and `location_invalid` for the no-fetch catalog
sentinel. The endpoint returned 117 unique opaque identities, including 57
with `supports_1m: true`; the installed configuration had all 117 native price
rows and 15 managed MCP entries. These configuration observations are not
functional tests of every feature or tool.

The verified network namespace had only loopback, and the trace recorded zero
successful or unresolved non-loopback connections. The private guard recorded
no allowed external connection. One Qwen subscription request with
`max_tokens: 1`, one message, no tools, and no streaming matched Desktop's
logged `connection_probe`. The original driver marked its receipt
`INCOMPLETE` because its initial contract rejected all inference; that status
is preserved, and `post_run_review` / `visual-review.json` explicitly classify
the authorized implicit probe and the startup/discovery checks. The exact
original driver was reconstructed and its bytes match the recorded driver
SHA-256; it is retained as `driver.py.snapshot`.

Early screenshots showed the initial dark loading surface. The final
`screen-07.png` was inspected and shows the fully rendered native Home UI, a
Gateway banner, Chat composer, and the selected
`[ПОДПИСКА] qwen3.8-27b · ctx 262144` label. No interactive dropdown was opened;
the complete visible model menu and feature execution remain unverified by UI.
The private DBus instance had no system keyring, which is visible in the
screenshot; this does not establish a keyring problem in the user's regular
desktop session.

### Native Code engine bootstrap limitation

The same run exposed an additional real dependency. Desktop embeds a pin for
Code engine **2.1.309**, separate from the user's installed standalone CLI
2.1.316. The native engine's cache was absent, so Desktop tried to fetch
`https://downloads.claude.ai/claude-code-releases/2.1.309/linux-x64/claude.zst`;
all attempts were blocked by the guard. No Code session was started. This
must be resolved before claiming that native Desktop Code works offline.

Source `Cv()` at `1611728` embeds the Code pin, manifest, and download base URL.
The Linux x64 compressed artifact must have SHA-256
`e52289b95def16148c8d0a48b1ccc0d357429e73473a9a20ac0638fb7460a59b`.
`binaryExistsForTarget` at `4084260` requires the executable and an exact
matching `.verified` artifact digest under
`<userData>/claude-code/2.1.309/e52289b95def/`; `.payload` separately records
the uncompressed binary digest and length. `downloadBinaryForTarget` at
`4089600` verifies the compressed release digest before decompression and
writing those markers.

The literal `CLAUDE_CODE_LOCAL_BINARY` appears only in an environment-redaction
set in this packaged build. `initLocalBinary` exists as a method but has no
call site across the ASAR JavaScript, and `localBinaryInitPromise` is only
initialized to null. It is therefore not a verified supported override.
The manager copies the embedded release base URL in its constructor; no
configuration/environment mirror URL or setter was found. Packaged compressed
preseeds also require the same artifact digest. An uncompressed in-place
preseed branch exists but is MSIX-gated and disabled in this Linux DEB build.

A genuine raw npm binary with its npm SHA-512 integrity can establish the
identity of that npm package. It cannot establish verification of the
different compressed Desktop artifact or justify writing its expected digest
into `.verified`. Do not relabel the installed 2.1.316 executable as 2.1.309 or
forge a pinned artifact marker. A genuine matching compressed artifact supplied
offline or through a permitted independent mirror would preserve the native
verification path. The inspector did not modify native caches or binaries.

