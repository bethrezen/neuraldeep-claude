"""Owned, portable Microsoft Playwright MCP browser for ordinary public sites.

The browser is separate from Claude Desktop's built-in local-preview browser and
from every existing browser/profile. Its child environment does not inherit
proxy settings, and no separate egress-filter process is required.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .config import atomic_json, clean_environment

MCP_VERSION = "0.0.84"
MCP_PACKAGE = "@playwright/mcp"
REGISTRY = "https://registry.npmjs.org/"
CAPABILITIES = ("network", "storage", "testing", "vision", "pdf", "devtools", "config")


def _paths(root: Path) -> dict[str, Path]:
    root = Path(root).resolve()
    runtime = root / ".local/browser-runtime"
    return {
        "root": root, "runtime": runtime,
        "package": runtime / "node_modules/@playwright/mcp/package.json",
        "entry": runtime / "node_modules/@playwright/mcp/cli.js",
        "playwright": runtime / "node_modules/playwright/cli.js",
        "browsers": runtime / "browsers", "config": runtime / "browser-config.json",
        "receipt": runtime / "installation.json", "output": root / ".local/browser-output",
    }


def _environment(root: Path) -> dict[str, str]:
    env = clean_environment()
    # Do not inherit extension attachment, another browser's executable/profile,
    # package mirror, Node preload code, or upstream API credentials.
    for key in list(env):
        if key.startswith(("PLAYWRIGHT_", "NEURALDEEP_API_KEY", "NEURALDEEP_DRIFT_TOKEN")) or key == "NODE_OPTIONS":
            env.pop(key)
    paths = _paths(root)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(paths["browsers"])
    env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
    env["npm_config_cache"] = str(paths["runtime"] / "npm-cache")
    env["npm_config_registry"] = REGISTRY
    env["npm_config_userconfig"] = str(paths["runtime"] / "empty.npmrc")
    env["npm_config_globalconfig"] = str(paths["runtime"] / "empty-global.npmrc")
    return env


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Portable browser requires Node.js 18+ and npm on PATH; install Node.js, then run browser install")
    return str(Path(node).resolve())


def _npm_cli(node: str) -> Path:
    """Execute npm's JavaScript entry directly, including on Windows (.cmd)."""
    npm = shutil.which("npm")
    node_path = Path(node)
    candidates = []
    if npm:
        npm_path = Path(npm).resolve()
        if npm_path.name in ("npm-cli.js", "npm.js"):
            candidates.append(npm_path)
        candidates.append(npm_path.parent / "node_modules/npm/bin/npm-cli.js")
    candidates.extend((
        node_path.parent / "node_modules/npm/bin/npm-cli.js",
        node_path.parent.parent / "lib/node_modules/npm/bin/npm-cli.js",
        node_path.parent.parent / "share/nodejs/npm/bin/npm-cli.js",
    ))
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise RuntimeError("npm CLI was not found next to Node.js/npm; install a standard Node.js 18+ distribution including npm")


def _run(command: list[str], root: Path, *, timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(command, cwd=_paths(root)["runtime"], env=_environment(root),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Portable browser installation command timed out after " + str(timeout) + " seconds") from exc
    if completed.returncode:
        raise RuntimeError("Portable browser command failed: " + completed.stdout[-6000:])
    return completed


def _configuration(root: Path) -> dict:
    paths = _paths(root)
    return {
        "browser": {
            "browserName": "chromium", "isolated": True,
            "launchOptions": {
                "channel": "chromium", "headless": True, "chromiumSandbox": False,
            },
        },
        "capabilities": list(CAPABILITIES),
        "allowUnrestrictedFileAccess": True,
        "outputDir": str(paths["output"]),
    }


def install(root: Path) -> dict:
    """Install exact package + Chromium under .local only; no system packages."""
    paths = _paths(root)
    paths["runtime"].mkdir(parents=True, exist_ok=True)
    paths["output"].mkdir(parents=True, exist_ok=True)
    for name in ("empty.npmrc", "empty-global.npmrc"):
        (paths["runtime"] / name).write_text("", encoding="utf-8")
    node = _node()
    version = _run([node, "--version"], root, timeout=30).stdout.strip()
    try:
        major = int(version.lstrip("v").split(".", 1)[0])
    except ValueError:
        raise RuntimeError("Cannot determine Node.js version") from None
    if major < 18:
        raise RuntimeError("Portable browser requires Node.js 18+; found " + version)
    atomic_json(paths["runtime"] / "package.json", {
        "name": "neuraldeep-owned-browser", "private": True, "version": "1.0.0",
        "dependencies": {MCP_PACKAGE: MCP_VERSION},
    }, private=True)
    _run([node, str(_npm_cli(node)), "install", "--ignore-scripts", "--no-audit", "--no-fund", "--registry", REGISTRY], root)
    package = json.loads(paths["package"].read_text(encoding="utf-8"))
    if package.get("version") != MCP_VERSION:
        raise RuntimeError("Installed Playwright MCP version differs from the pinned version")
    # No --with-deps or install-deps: these can change the operating system.
    _run([node, str(paths["playwright"]), "install", "chromium"], root)
    atomic_json(paths["config"], _configuration(root), private=True)
    receipt = {
        "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "package": MCP_PACKAGE, "version": MCP_VERSION, "registry": REGISTRY,
        "node": node, "node_version": version,
        "package_lock": str(paths["runtime"] / "package-lock.json"),
        "browser_path": str(paths["browsers"]), "config": str(paths["config"]),
        "capabilities": list(CAPABILITIES), "headless": True, "isolated": True, "sandbox": False,
        "ambient_proxy_env_removed": True, "dedicated_network_filter": False,
        "existing_browser_profile_used": False, "system_install": False,
        "network_policy": "ordinary-browser-network; no-custom-proxy-or-egress-filter",
    }
    atomic_json(paths["receipt"], receipt, private=True)
    return receipt


def status(root: Path) -> dict:
    """Read installation status without launching browsers or changing services."""
    paths = _paths(root)
    result = {"installed": False, "package": MCP_PACKAGE, "expected_version": MCP_VERSION,
              "runtime": str(paths["runtime"]), "browser_path": str(paths["browsers"]),
              "capabilities": list(CAPABILITIES), "headless": True, "isolated": True, "sandbox": False,
              "ambient_proxy_env_removed": True, "dedicated_network_filter": False}
    if paths["receipt"].exists():
        try:
            result["installation"] = json.loads(paths["receipt"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result["reason"] = "invalid-installation-receipt"
            return result
    try:
        package = json.loads(paths["package"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result["reason"] = "package-not-installed"
        return result
    result["version"] = package.get("version")
    if package.get("version") != MCP_VERSION:
        result["reason"] = "package-version-mismatch"
    elif not paths["entry"].is_file() or not paths["config"].is_file():
        result["reason"] = "installation-incomplete"
    elif not paths["browsers"].is_dir() or not any(paths["browsers"].glob("chromium-*")):
        result["reason"] = "owned-chromium-not-installed"
    else:
        result["installed"] = True
    return result


def mcp_command(root: Path, python: str | None = None) -> dict:
    """A portable stdio MCP entry with owned browser/profile settings."""
    root = Path(root).resolve()
    return {"command": python or sys.executable,
            "args": [str(root / "scripts/browser-mcp.py"), "--root", str(root), "launch"]}


def launch(root: Path) -> int:
    """Run the pinned stdio MCP with fresh config and a clean child environment."""
    # Lazy import: services includes this module only while building MCP config.
    from .services import service_state
    if not service_state(root).get("browser", True):
        raise RuntimeError("Portable browser service is disabled; enable browser before launching it")
    paths = _paths(root)
    state = status(root)
    if not state["installed"]:
        raise RuntimeError("Portable browser is not ready (" + state.get("reason", "unknown") + "); run browser install")
    atomic_json(paths["config"], _configuration(root), private=True)
    env = _environment(root)
    command = [_node(), str(paths["entry"]), "--config", str(paths["config"]),
               "--headless", "--isolated", "--no-sandbox", "--idle-timeout", "0"]
    # Inherit MCP streams. Only this child is owned; never terminate another
    # browser or change an independent network service.
    process = subprocess.Popen(command, cwd=paths["root"], env=env)
    try:
        while process.poll() is None:
            if not service_state(root).get("browser", True):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                return 0
            time.sleep(0.25)
        return process.returncode
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
