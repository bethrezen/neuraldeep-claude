---
name: nd-design
description: Create and refine local responsive designs, working frontend prototypes, and image assets using NeuralDeep models and services. Use for /nd-design, local UI design, and design-to-code work through NeuralDeep.
---

# Local design through NeuralDeep

Create the requested design as usable local files in the user's project. This workflow uses NeuralDeep inference and services; the user chose it instead of Anthropic's hosted Design, login, sync, and sharing flows.

Inspect the existing app, design system, reference images, and available assets first. Clarify decisions that materially change the result, while making progress on independent work. Follow the project's stack and conventions. For a standalone brief, produce a responsive HTML/CSS/JS prototype or a small runnable app, with the assets and launch instructions needed to use it.

Read [runtime and services](references/runtime.md) for this machine's integration commands and tool names. Use `mcp__neuraldeep-search__web_search` / `read_page` when outside references are needed, and `mcp__neuraldeep-images__image_generate` / `image_edit` for bitmap assets. Prefer code-native SVG/CSS for ordinary interface geometry and icons. Preserve the user's references and established visual language.

For image work, inspect the actual source file before editing. Start the appropriate NeuralDeep task, retain its task ID, poll `image_status`, then fetch `image_result` after completion using the same billing choice. An accepted job is pending work, not a finished image. Inspect the returned local image file before incorporating it; keep the final asset in the project with a stable local path. Reuse a pending task rather than generating duplicate paid tasks after a timeout.

Implement useful interaction states, layout at narrow and wide widths, readable type, keyboard access, and semantic controls. When browser tools are available, start the prototype, view it, check the requested flows, inspect screenshots at relevant sizes, and fix visible problems. When browser or image inspection is unavailable, report exactly which verification remains. A successful build is not evidence that the visual result was reviewed.

Use parallel subagents for independent research, assets, implementation, and review when this helps. Give each writer a separate file scope and integrate their results before final verification. Use the current model's real vision/tool/thinking limits and the user's billing choice. Subscription is preferred; wallet use is explicit and stays within the user's authorized scope. Do not select a more expensive billing route silently.

Deliver clickable local output paths, the run command, and a clear account of what was visually and functionally verified. Publish or upload only when requested.
