---
name: nd-workflow
description: Coordinate substantive coding or research work through NeuralDeep using native dynamic workflows and parallel subagents, preserving ownership, dependencies, and verification. Use for /nd-workflow and requested parallel agent execution through NeuralDeep.
---

# Coordinated work through NeuralDeep

Complete the requested task with an explicit coordinator and independent workers where parallel work helps. Keep the user's scope, preferences, model choice, and billing authorization. Ask about consequential ambiguities while continuing work that does not depend on the answer.

Read [runtime and services](references/runtime.md) for installation commands and actual MCP names. For a substantive task, use Claude Code's native `Workflow` tool when available; consult its live schema or `/workflow-authoring` instructions. Native workflow availability depends on the installed client and current model. If it is unavailable, coordinate parallel `Agent` calls and identify that fallback in the final report; do not claim a dynamic workflow ran.

Start from the concrete result and acceptance checks. Split independent investigations and disjoint file edits into parallel workers; keep dependent changes in order. Each assignment should name its deliverable, relevant source context, file ownership, constraints, and how the worker will verify its result. Keep integration ownership with the coordinator. Workers can delegate further when helpful and supported by the client and model.

Maintain a compact record of active assignments, dependencies, completed evidence, and unresolved decisions so the run survives context compaction. Avoid having two workers edit the same file simultaneously. Read worker results, resolve conflicting conclusions against actual sources, integrate changes, and perform the checks that establish the user's requested outcome.

Do not impose a new worker count, nesting depth, token budget, or tool restriction on the user's work. Respect actual provider concurrency limits, client runtime caps, model context and output limits, and any budget the user specified. Parallel requests share the same provider quota. Route workers through existing NeuralDeep model IDs; keep identical models on subscription by default and make wallet selection explicit. Select only efforts and thinking flags the chosen model actually supports.

Use NeuralDeep's search, OCR, embeddings, reranking, image, audio, and other services when relevant and enabled. Preserve asynchronous task IDs and failed results; avoid duplicate paid submissions after a timeout. A service being configured does not establish that it works for the current key or input.

Report the resulting artifact or change, substantive validation, and any remaining blocker. Distinguish real worker execution, successful tool calls, completed provider jobs, measured results, and untested configuration. Do not describe a mock, a prepared script, or a single-model smoke test as proof that every model, automatic compaction, or every dynamic workflow works.
