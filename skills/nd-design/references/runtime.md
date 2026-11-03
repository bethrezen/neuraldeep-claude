# Runtime and NeuralDeep services

The installer replaces this reference with commands for the actual installation directory. From the portable integration root, use `python scripts/nd.py services list`, `python scripts/nd.py services enable images search`, and `python scripts/nd.py models list`.

MCP servers are named `neuraldeep-<group>`. Claude tool names are `mcp__neuraldeep-<group>__<tool>`. Relevant examples are `mcp__neuraldeep-images__image_generate`, `image_edit`, `image_status`, `image_result`, `images_quota`, and `mcp__neuraldeep-search__web_search`, `read_page`, `search_quota`.

Read live tool schemas for arguments and documented model flags; do not invent parameters. Image output downloads to the integration's `.local/artifacts/` directory and returns an actual file path. A disabled service must be enabled individually and its MCP server reloaded before use. All service network requests bypass environment proxies.

Billing defaults to subscription. Quota errors do not authorize wallet fallback. Retain task IDs and poll the existing task with the same billing route. Never expose API keys or paste `.env` into prompts, files intended for sharing, or tool arguments.
