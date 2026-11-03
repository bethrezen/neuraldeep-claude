# Native CLI catalog and pricing source audit

Read-only source inspection: installed Claude Code 2.1.316, SHA256
`fd13c70000fec3f2116dfbcbb6121210b4a29328bf0e46210a59dd594a67d824`.
Offsets below refer to its installed native Linux binary. No native source,
signature enforcement, trust roots or organization policy files were modified.

## Current Desktop installer policy

The installer enables native signed catalog metadata and leaves `modelCatalogUrl`
unset. The default location is
`https://downloads.claude.ai/model-catalog/v1/catalog.json`; native signature
verification, refresh and caching remain in charge. This catalog does not change
the offered models, their order or the default model. NeuralDeep limits,
capabilities, efforts and tariffs remain in gateway discovery and supported
model settings, rather than an unsigned replacement catalog.

Native Desktop's `disableAutoUpdates` default is `false`, which the installer
now uses. The inspected Linux build explicitly disables its in-app updater and
uses the system package manager; the setting does not override that platform
behavior. It no longer blocks the native updater on Windows/macOS.
`bootstrapEnabled` is also left unset (native default `true`); no bootstrap URL
is added. Without a URL this config-fetch switch is inert, and it does not
control account `/api/bootstrap`. Both telemetry blocks remain enabled, while
the separate content-service block is disabled. This is installer preparation,
not evidence that a running Desktop has already reloaded these changes.

These defaults were checked in the installed Desktop 4.4212.0 schema and main
process: `ion-dist.asar/assets/v1/c6f6cf4c2-DjyEM_NG.js` and
`app.asar/.vite/build/index.chunk-CvhJZ02X.js`. No native source was changed.

## CLI catalog

`CLAUDE_CODE_MODEL_CATALOG=0` disables the served/published catalog path. It does
not remove the built-in model metadata: `a1e()` returns the compiled `uio`
catalog through the baked-catalog cache independently of that variable.

The CLI supports a `CLAUDE_CODE_MODEL_CATALOG_URL` with a local `file:` URL. Both
file and network documents require their signature sidecar and verification
against the compiled RSA trust roots. A missing/invalid file is not a mechanism
for supplying arbitrary unsigned NeuralDeep metadata. The managed-source
function in this build returns no custom URL or public key. Published catalog
activation for a custom first-party base URL also encounters the build's
release gate; changing the environment variable to `1` does not establish a
working custom metadata feature.

The current CLI configuration keeps its dynamic catalog fetch disabled
and its compiled metadata intact. NeuralDeep-specific limits, capabilities,
efforts and tariffs belong in the local gateway discovery data and supported
model settings. In the earlier no-fetch Desktop policy its separate catalog
toggle used the bundled signed catalog with the exact no-fetch sentinel. That
Desktop restriction is historical and is no longer emitted by the installer;
the current Desktop policy is described above. Neither policy turns the signed
catalog into a NeuralDeep metadata catalog.

| Owning code | Byte offset |
| --- | ---: |
| Baked catalog cache and `a1e` | 273837100 |
| Provider identity `Hn` / `us` | 273845484 |
| Dynamic catalog environment gate `hUt` | 293241276 |
| Local URL selection and validation | 292263494 |
| Local file read and `.raw-sig.json` sidecar | 292266900 |
| RSA signature verification | 292268800 |
| Published catalog custom-provider release gate | 293247100 |
| Release gate `mwi`, compiled false in this build | 276729678 |

## CLI pricing

Claude Code supports this settings shape; the rates are USD per million tokens:

```json
{
  "modelPricing": {
    "multiplier": 1,
    "overrides": {
      "nd/example@wallet": {
        "input": 1.25,
        "output": 2.5,
        "cacheRead": 0.125,
        "cacheWrite": 0
      }
    }
  }
}
```

The multiplier is optional, greater than zero and at most ten. All four rate
fields are required per row and each must be between zero and 10,000. Custom
provider IDs match exactly after case normalization and removal of `[1m]` or
`[2m]`. Effort suffixes remain part of the exact ID. Built-in Claude IDs have
additional family/provider matching rules and must not be used to mislabel
NeuralDeep models.

This setting changes `/cost`, status-line cost, SDK `total_cost_usd`, budget
accounting and cost metrics. The per-million-token labels in `/model` remain
the client's own list-price labels; configuring spend estimates does not
replace those labels.

The CLI ignores `modelPricing` from user, project, local and ordinary
`--settings`. It accepts real organization managed policy, or a spawning host's
parent settings supplied with `--managed-settings <json>` when
`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1`. Any real admin tier's pricing takes
precedence over the host pricing. The parent argument accepts inline JSON, not
a filename. Redirecting `CLAUDE_CODE_MANAGED_SETTINGS_PATH` to an integration
directory would change the machine-policy source and must not be used as a
shortcut.

Host-managed mode is an actual provider-hosting interface but has wider effects
than pricing: it changes settings-sourced authentication/provider/CA handling,
shell credential sanitization and background-session handoff. Source inspection
alone does not establish complete workflow/agent compatibility. It should be
runtime-validated before becoming an ordinary launch default.

There is also a Windows command-line-size constraint: serializing the current
117 options as raw IDs, opaque aliases and redundant `[1m]` aliases produced
351 rows and 51,446 JSON characters (54,979 with Windows argument quoting).
The suffix aliases can be omitted because native lookup strips the suffix, but
future catalog growth still needs a deliberate command-size strategy. A local
file cannot simply be substituted for the parent JSON argument.

| Owning code | Byte offset |
| --- | ---: |
| Rate schema `us` and multiplier schema `ps` | 274245176 |
| `modelPricing` source restrictions and scope | 274276997 |
| Parent-host pricing selection `Bms` | 274502422 |
| Host-managed context and provider flag | 274916714 |
| Effective pricing getter `qus` | 274919318 |
| Parent `--managed-settings` JSON parser `tUi` | 277949720 |
| Hidden parent CLI option declaration | 293645462 |
| Pricing compilation `Di` / `w0` | 276879900 / 276880720 |
| Matching and cost application `wu` / `jCn` | 276881692 / 276882280 |
| Context suffix normalization `Bn` | 273704587 |

## Experimental host-pricing diagnostic

`scripts/probe-offline.py --tool-search --host-pricing --execute` is an opt-in
diagnostic only. It does not enable host-managed mode for installed launchers.
It supplies 117 raw CLI model IDs, omitting the opaque Desktop and redundant
context-suffix IDs. Its compact parent JSON is 14,600 characters; the complete
Windows-quoted native command was 16,833 characters, below the diagnostic's
30,000-character limit. An oversized future catalog fails before native launch.

The bounded Linux test used the Qwen subscription route and one local MCP echo.
It completed the real ToolSearch/reference/echo lifecycle and reported nonzero
token usage with `costBasis: "managed"`, model cost zero and total cost zero.
The SDK exposes the native pricing basis as `managed`; the internal calculator
uses a different enum, `configured`. That distinction is defined in the SDK
schema at byte 275740997 and the pricing-basis function at 276882690.

The original diagnostic receipt remains unchanged at
`.local/offline-validation/20261102T181115964987Z/receipt.json`. Its status is
`FAIL` because the first diagnostic gate mistakenly expected the internal enum
name in SDK output. The corrected evaluation is separately recorded at
`.local/offline-validation/20261102T181115964987Z/pricing-reevaluation.json`,
with the original receipt and transcript SHA256 values. It passed all original
network and ToolSearch gates plus the corrected pricing gate, without another
inference request. The native namespace had zero successful or unresolved
nonloopback connections and the host guard connected to no external host.

This verifies the opt-in host pricing path for one subscription model. No
wallet model or paid service tool was invoked, and parallel agents, workflows,
background handoff and other platforms were not runtime-tested in host mode.
The follow-on workflow trial was cancelled after the user requested keeping
the ordinary CLI closer to its original installation. Production CLI host-mode
defaults were not introduced.
