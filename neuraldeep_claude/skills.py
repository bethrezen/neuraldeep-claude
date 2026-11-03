"""Install portable Claude skills and inject only local runtime paths."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .config import atomic_json

NAMES = ("nd-design", "nd-workflow", "nd-browser")


def install_skills(root: Path, destination: Path | None = None) -> dict:
    root = Path(root).resolve()
    destination = Path(destination) if destination is not None else Path.home() / ".claude/skills"
    argv = [sys.executable, str(root / "scripts/nd.py"), "--root", str(root)]

    def command(*arguments):
        tokens = argv + list(arguments)
        return subprocess.list2cmdline(tokens) if os.name == "nt" else shlex.join(tokens)

    runtime = (
        "# Installed NeuralDeep runtime\n\n"
        f"Integration directory: `{root}`. Keys live only in its `.env`. Never print or copy those keys.\n\n"
        "Commands work from any current directory:\n\n"
        "```text\n"
        + command("models", "list") + "\n"
        + command("models", "update") + "\n"
        + command("services", "list") + "\n"
        + command("services", "enable", "images", "search") + "\n"
        + command("services", "disable", "images") + "\n"
        + "```\n\n"
        "Read the installed service guide when endpoint details matter: "
        f"`{root / 'docs/SERVICES.md'}`. Read live MCP tool schemas before calls.\n\n"
        "MCP server names are `neuraldeep-<group>`. Claude tool names include "
        "`mcp__neuraldeep-images__image_generate`, `mcp__neuraldeep-images__image_edit`, "
        "`mcp__neuraldeep-images__image_status`, `mcp__neuraldeep-images__image_result`, "
        "`mcp__neuraldeep-images__images_quota`, `mcp__neuraldeep-search__web_search`, "
        "`mcp__neuraldeep-search__read_page`, `mcp__neuraldeep-ocr__ocr_extract`, "
        "`mcp__neuraldeep-embeddings__embed`, and `mcp__neuraldeep-rerank__rerank`.\n\n"
        "Each service can be enabled or disabled separately. A newly enabled server "
        "may need an MCP reload or a new session before its tools appear. "
        "All NeuralDeep service requests bypass environment proxies.\n\n"
        "For public websites use the independent `local-browser` Playwright MCP, "
        "discovering its `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` "
        "and other tools with ToolSearch. Its isolated browser is headless with "
        "command sandbox disabled. Do not use "
        "the user's personal browser/profile. Native Desktop built-in browser is "
        "available for previews; the independent MCP also handles public websites. Read "
        f"`{root / 'docs/BROWSER.md'}`. Toggle using services enable/disable browser.\n\n"
        "Subscription is preferred; wallet is an explicit billing choice, never "
        "an automatic quota-error fallback. Use the same billing route when polling "
        "a created task and downloading its result. Pending is not completion. "
        f"Downloaded service output is stored under `{root / '.local/artifacts'}`; "
        "inspect the returned actual file before using it in a deliverable.\n\n"
        "The native client may limit arbitrary model contexts or dynamic workflow "
        "availability. Report actual execution and untested cells accurately. "
        "Use `/nd-design` for local code/prototypes/assets; do not invoke Anthropic Design login or sync.\n"
    )
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backups = []
    installed = []
    for name in NAMES:
        source = root / "skills" / name
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError(f"Missing portable skill {name}")
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            target = destination / name / relative
            text = runtime if relative == Path("references/runtime.md") else path.read_text(encoding="utf-8")
            previous = target.read_text(encoding="utf-8") if target.exists() else None
            if previous == text:
                continue
            if previous is not None:
                backup = root / ".local/backups" / ("skills-" + stamp) / name / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backups.append({"source": str(target), "backup": str(backup)})
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        installed.append(str(destination / name / "SKILL.md"))
    result = {"skills": installed, "backups": backups}
    atomic_json(root / ".local/skills-installation.json", result, private=True)
    return result
