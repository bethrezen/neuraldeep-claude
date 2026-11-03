# Local tool search protocol

The installed Claude Code 2.1.316 implements a client-side `ToolSearch` tool. It
searches the client's connected deferred tools, then sends an ordinary user
`tool_result` containing `tool_reference` blocks with a `tool_name` property.
The full definitions stay in the request's `tools` array with `defer_loading:
true`. This path does not require an Anthropic-hosted search service.

The NeuralDeep Messages adapter now binds those referenced definitions to
OpenAI function tools. Definitions that have not been discovered stay out of
the provider's function-tool list. Reference results become brief text results;
their full input schemas are supplied through the provider's normal `tools`
parameter. Previously called tools and an explicit `tool_choice` also bind the
matching deferred definition. Loading is derived from each request's transcript,
so concurrent conversations and process restarts do not share mutable discovery
state.

This adapter supports the actual local `ToolSearch` lifecycle used by the
installed client. It does not claim to implement Anthropic-hosted native search
tool types. Other native server tool types continue to produce an explicit
unsupported-feature error.

Source inspection used the installed Linux native binary at
`/home/bethrezen/.local/share/claude/versions/2.1.316`, SHA256
`fd13c70000fec3f2116dfbcbb6121210b4a29328bf0e46210a59dd594a67d824`.
The following byte offsets identify the owning embedded JavaScript:

| Area | Byte offset |
| --- | ---: |
| Model compatibility gate `rme` | 279207013 |
| `ENABLE_TOOL_SEARCH` selection `Jie` | 279205539 |
| Request `tool_reference` schema | 275734950 |
| `ToolSearch` result mapping | 284833534 |
| Discovery from conversation history | 285574550 |
| Deferred definition binding | 281451375 |

The model gate in this version excludes its configured legacy-model blacklist;
it does not require the real provider to be Anthropic. Native Desktop 4.4212.0
launches local Claude Code sessions for Chat, Code and Cowork, and its tool
search setting controls that engine's tool-search environment.

Protocol validation command:

```sh
python -m unittest discover -s tests -p test_protocol.py
```

The four tool-search tests cover discovery, exact schema hydration, isolation
between conversations, streamed parallel tool invocations, invocation history
after compaction, explicit selection, malformed references, and arbitrary JSON
tool arguments that happen to resemble reference blocks. This is source
and synthetic protocol evidence; native runtime evidence is recorded below.

The optional native runtime smoke is dry-run first:

```sh
python scripts/probe-offline.py --tool-search
python scripts/probe-offline.py --tool-search --execute
```

Execution requires Linux, `bwrap`, `strace`, an already running gateway and the
per-Claude egress guard. It starts the real CLI only after verifying a new
network namespace, with the existing fixed bridge exposing host loopback ports
8787 and 18790. It enables just one local stdio MCP echo fixture, without the
NeuralDeep MCP service tools. Real inference still uses the selected NeuralDeep
model and its quota. The fixture itself opens no network connections.

The runtime pass condition requires the native client to invoke `ToolSearch`,
receive a `tool_reference`, invoke the discovered echo with a unique marker,
record its real fixture execution, and return the matching final marker. A
claimed success sentence alone does not pass. The receipt retains the native
transcript, fixture audit, namespace identity, connection trace and gateway and
guard metadata. The portable adapter and installer remain independent of this
Linux-only diagnostic.

## Native runtime result, 2026-11-02

The guarded Linux CLI 2.1.316 passed the full discovery lifecycle with Qwen 3.8
27B, subscription billing, at:

`.local/offline-validation/20261102T175007710217Z/receipt.json`

The native transcript records one real `ToolSearch` call, the matching
`tool_reference`, one subsequent discovered MCP echo call, and the matching
final marker. The local fixture audit independently confirms echo execution.
The gateway received three inference requests: the initial request exposed one
function, and the two requests after discovery exposed two. This verifies that
the deferred schema was bound only after discovery. The connection trace
contains zero successful or unresolved nonloopback connections from the native
namespace; the host egress guard connected to no external host. Only the host
inference gateway handled the NeuralDeep requests. No NeuralDeep MCP service
tool was invoked.

The initial failed diagnostic is retained at:

`.local/offline-validation/20261102T174931229171Z/receipt.json`

That native session loaded an older active user setting
`ENABLE_TOOL_SEARCH=false`, overriding the probe's inherited environment. The
client exposed the echo eagerly and did not advertise `ToolSearch`; the pass
gate correctly rejected the result even though the echo worked. The probe now
sets `ENABLE_TOOL_SEARCH=force` through the command-level `--settings` JSON as
well as its child environment, without modifying the user's active files.
Current CLI source explicitly supports this value so tool search can run while
unrelated experimental betas remain disabled. The passing retry exercises that
setting. Installer activation must persist the same value for ordinary CLI
launches; setting it merely to `true` is insufficient when experimental betas
are suppressed.

This proves the installed CLI's local discovery path with one deferred fixture
and one selected model. It does not constitute a native Desktop UI session test,
every model's tool-use quality test, or support for an Anthropic-hosted native
server-tool protocol.
