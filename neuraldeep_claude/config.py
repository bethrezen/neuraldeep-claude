"""Portable configuration; never execute shell code from .env."""
from __future__ import annotations
import json
import os
import secrets
import tempfile
import hashlib
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

def source_revision() -> str:
    digest = hashlib.sha256()
    folder = Path(__file__).resolve().parent
    # Desktop/launcher/skill edits do not change the running gateway protocol.
    for path in sorted(folder / name for name in ("catalog.py", "config.py", "effort.py", "gateway.py", "protocol.py", "title_helpers.py", "transport.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()

def load_env(root: Path) -> dict[str, str]:
    result = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                raise ValueError("Malformed .env line (expected NAME=value)")
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("Invalid variable name in .env")
            value = value.strip()
            if value and value[0] in "\"'":
                quote = value[0]
                end = next((i for i in range(1, len(value)) if value[i] == quote and value[i - 1] != "\\"), None)
                if end is None or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith("#")):
                    raise ValueError("Invalid quoted value in .env")
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            result[key] = value
    return result

def key_for(root: Path, mode: str) -> str:
    if mode not in ("subscription", "wallet"):
        raise ValueError("Billing must be subscription or wallet")
    key = load_env(root).get("NEURALDEEP_API_KEY_" + mode.upper(), "")
    if not key:
        raise ValueError("Missing NEURALDEEP_API_KEY_" + mode.upper() + " in .env")
    return key

def atomic_json(path: Path, data: object, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if private:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def local_token(root: Path) -> str:
    path = root / ".local/gateway-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    return token

def clean_environment(source: dict | None = None) -> dict:
    env = dict(os.environ if source is None else source)
    # Remove active and renamed proxy variants, from both shell and settings.
    for key in list(env):
        if "proxy" in key.lower() or key in (
            "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
            env.pop(key)
    return env
