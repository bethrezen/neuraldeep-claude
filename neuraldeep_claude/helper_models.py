"""Resolve explicit helper models without replacing the primary coding model."""
from __future__ import annotations

import json
from pathlib import Path

from . import catalog


CLASSIFIER_ENV = "CLAUDE_CODE_AUTO_MODE_MODEL"


def classifier_model(root: Path, opaque: bool = False) -> str | None:
    """Return the configured subscription classifier route or no override.

    Native Desktop passes the opaque route from its spawning-parent environment;
    ordinary Claude Code can read the raw route from its user settings. A bad
    explicit configuration fails clearly instead of selecting another model or
    spending the wallet balance. No permission mode or classifier rule changes.
    """
    root = Path(root)
    path = root / "config/helper-models.json"
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema", 1) != 1:
        raise ValueError("Helper model configuration must be a schema 1 JSON object")
    selected = document.get("auto_permission_classifier")
    if selected is None:
        return None
    if (not isinstance(selected, str) or not selected.startswith("nd/")
            or not selected.endswith("@subscription") or "~" in selected
            or selected.count("@") != 1):
        raise ValueError("Auto permission classifier must use an exact base nd/model@subscription route")
    data = catalog.load(root)
    try:
        model = catalog.resolve(data, selected)
    except ValueError as error:
        raise ValueError("Configured Auto permission classifier is unavailable: " + str(error)) from error
    if model["id"] != selected or model.get("billing") != "subscription":
        raise ValueError("Configured Auto permission classifier must resolve to the exact subscription route; no billing fallback is allowed")
    if catalog.picker_status(data, model) != "visible":
        raise ValueError("Configured Auto permission classifier is hidden until a successful model check; select an available subscription model")
    return catalog.gateway_alias(selected) if opaque else selected
