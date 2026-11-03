#!/usr/bin/env python3
"""Build a portable ZIP from explicit source paths; never include credentials."""
from pathlib import Path
import hashlib
import zipfile

root = Path(__file__).resolve().parent.parent
target = root / "dist/neuraldeep-claude-portable.zip"
target.parent.mkdir(exist_ok=True)
files = []
for name in ("README.md", "pyproject.toml", ".env.example", ".gitignore", "install.sh", "install.ps1", "update-models.sh", "update-models.ps1"):
    path = root / name
    if path.exists(): files.append(path)
for folder, pattern in (("neuraldeep_claude", "*.py"), ("scripts", "*.py"), ("config", "*.json"), ("tests", "*.py"), ("skills", "*.md"), ("docs", "*.md"), (".github", "*.yml")):
    files.extend(p for p in (root / folder).rglob(pattern) if "upstream" not in p.parts and "__pycache__" not in p.parts)
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(files)):
        relative = path.relative_to(root)
        if ".local" in relative.parts or path.name == ".env":
            raise RuntimeError("Refusing credential/state file: " + str(relative))
        archive.write(path, Path("neuraldeep-claude") / relative)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n")
print(str(target))
print("sha256 " + digest)
