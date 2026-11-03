# Runtime and NeuralDeep services

The installer replaces this reference with machine-specific commands. From the portable integration root, run `python scripts/nd.py models list` to inspect billing-specific models and efforts, and `python scripts/nd.py services list` for individually enabled services.

MCP servers use `neuraldeep-<group>` and Claude names tools as `mcp__neuraldeep-<group>__<tool>`. Examples: `mcp__neuraldeep-search__web_search`, `mcp__neuraldeep-search__read_page`, `mcp__neuraldeep-images__image_generate`, `mcp__neuraldeep-ocr__ocr_extract`, `mcp__neuraldeep-embeddings__embed`, and `mcp__neuraldeep-rerank__rerank`. Read the tool's live schema before calling it.

Use the provider's published per-model flags and context from the current catalog. Native Claude UI effort names may differ from the upstream API vocabulary; explicit `~<effort>` picker entries preserve the selected provider effort. Do not raise a model's actual limit by labeling it as another model.

Subscription is the default; wallet routing must be explicit. All NeuralDeep network requests bypass environment proxies. Keep API keys only in the integration's `.env`; task prompts and model outputs must not contain them. Native Anthropic Design is outside this local workflow; use `/nd-design` for local prototypes and assets.
