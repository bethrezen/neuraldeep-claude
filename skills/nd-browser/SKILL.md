---
name: nd-browser
description: Browse and test public websites or local prototypes through the independent local-browser Playwright MCP with its own browser profile.
---

Read [the installed runtime](references/runtime.md) for absolute paths and commands.

Use ToolSearch to discover `local-browser` tools. Start with `browser_navigate`
and `browser_snapshot`. Use actual accessible page state for actions, and inspect
real screenshots when visual verification matters. The browser is isolated from
the user's personal tabs and credentials. Request a screenshot output filename
when the user needs an artifact, then link the actual resulting absolute file.

The official MCP exposes navigation, tabs, forms, uploads/downloads, screenshots,
PDF, network inspection, browser storage, evaluation and testing capabilities.
Use the tool schema of the installed version. Do not claim a test passed merely
because the server accepted a request; verify page state and outputs.

Native Desktop's built-in browser is enabled. The independent MCP is also
available for public websites and local previews. NeuralDeep API requests remain
direct. The installation uses ordinary Claude telemetry settings and does not
install a network filter. Do not change the shared system proxy.

If this MCP is disabled, enable only the `browser` service, then reconnect MCP or
start a new session. A missing Node.js runtime or browser dependency is an
installation error; report its actual diagnostic rather than silently switching
to the user's personal browser or enabling a remote service.
