"""Map Claude's effort selector to the selected model's real controls.

This adapter maps known discrete levels, never manufactures provider levels or
numeric thinking budgets. Models without a documented adjustable control keep
their configured thinking preset for every stock Claude effort selection.
"""
from __future__ import annotations

from collections.abc import Mapping


CLAUDE_LEVELS = ("low", "medium", "high", "xhigh", "max")
_RANK = {name: index for index, name in enumerate(CLAUDE_LEVELS)}
_RESET = {"auto", "default"}


def _levels(model: Mapping) -> tuple[list[str], bool]:
    """Return known, ordered native levels and whether their ordering is known."""
    raw = model.get("efforts") or []
    if not isinstance(raw, (list, tuple)) or any(not isinstance(level, str) for level in raw):
        return [], False
    levels = list(dict.fromkeys(raw))
    if any(level not in _RANK for level in levels):
        # A future provider vocabulary needs an evidenced mapping, rather than
        # assuming that unknown words have the same semantics as stock levels.
        return levels, False
    return sorted(levels, key=_RANK.__getitem__), True


def describe(model: Mapping) -> dict:
    """Describe the deterministic mapping without mutating model metadata."""
    levels, ordered = _levels(model)
    aliases = model.get("effort_aliases") or {}
    if not isinstance(aliases, Mapping):
        aliases = {}
    mapping = {}
    for requested in CLAUDE_LEVELS:
        if not levels or not ordered:
            mapping[requested] = None
            continue
        alias = aliases.get(requested)
        if alias in levels:
            mapping[requested] = alias
        else:
            # Ceiling preserves at least the requested strength when available;
            # requests beyond the native range saturate at its real maximum.
            mapping[requested] = next(
                (native for native in levels if _RANK[native] >= _RANK[requested]),
                levels[-1],
            )
    adjustable = bool(levels and ordered)
    return {
        "claude_levels": list(CLAUDE_LEVELS),
        "native_levels": levels,
        "mapping": mapping,
        "adjustable": adjustable,
        "default": levels[-1] if adjustable else None,
        "strategy": "ceiling-then-native-maximum" if adjustable else "configured-thinking-preset",
        "status": "mapped" if adjustable else "unmapped-provider-vocabulary" if levels else "no-documented-discrete-effort",
        "note": ("Several Claude levels may map to the same real provider level."
                 if adjustable else
                 "Claude effort selection is accepted; no unsupported reasoning_effort or numeric budget is invented."),
    }


def resolve_effort(model: Mapping, requested=None) -> dict:
    """Resolve a stock selector value or an explicit legacy route suffix.

    ``selected_effort`` belongs to a previously persisted ``~effort`` route and
    is a fallback for old clients. An explicit stock selector takes precedence
    so resuming an old route cannot lock the user out of ``/effort``.
    """
    explicit = model.get("selected_effort") if requested is None else None
    value = explicit if explicit is not None else requested
    if value is not None and not isinstance(value, str):
        raise ValueError("Effort must be a Claude effort name")
    info = describe(model)
    levels = info["native_levels"]
    if value is None or value in _RESET:
        return info | {"requested": value, "upstream_effort": info["default"],
                       "thinking_disabled": False, "selection": "maximum-default"}
    off = model.get("reasoning_off_efforts") or []
    if value in off:
        return info | {"requested": value, "upstream_effort": None,
                       "thinking_disabled": True, "selection": "documented-thinking-off"}
    # An explicit legacy suffix names a provider value, not a stock selector.
    if explicit is not None and value in levels:
        return info | {"requested": value, "upstream_effort": value,
                       "thinking_disabled": False, "selection": "legacy-native-effort"}
    aliases = model.get("effort_aliases") or {}
    alias = aliases.get(value) if isinstance(aliases, Mapping) else None
    if alias in levels:
        return info | {"requested": value, "upstream_effort": alias,
                       "thinking_disabled": False, "selection": "documented-alias"}
    if value in CLAUDE_LEVELS:
        return info | {"requested": value, "upstream_effort": info["mapping"][value],
                       "thinking_disabled": False,
                       "selection": "stock-mapped" if info["adjustable"] else "fixed-preset"}
    raise ValueError(f"Unsupported effort {value!r}; choose {', '.join(CLAUDE_LEVELS)} or auto")


def _disable_thinking(request: dict, model: Mapping) -> None:
    """Use only a documented off alias and a known provider control shape."""
    kwargs = request.get("chat_template_kwargs")
    thinking = request.get("thinking")
    if isinstance(kwargs, dict) and "enable_thinking" in kwargs:
        request["chat_template_kwargs"] = kwargs | {"enable_thinking": False}
    elif "enable_thinking" in request or str(model.get("upstream_id", "")).startswith("qwen"):
        request["enable_thinking"] = False
    elif isinstance(thinking, dict) or str(model.get("upstream_id", "")).startswith("glm"):
        request["thinking"] = (thinking if isinstance(thinking, dict) else {}) | {"type": "disabled"}
    else:
        raise ValueError("Documented thinking-off effort has no configured provider control")
    # Qwen documents these as mutually exclusive controls. Off also cannot
    # sensibly coexist with a positive thinking budget.
    request.pop("reasoning_effort", None)
    request.pop("thinking_budget", None)
    kwargs = request.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and "thinking_budget" in kwargs:
        request["chat_template_kwargs"] = {key: val for key, val in kwargs.items() if key != "thinking_budget"}


def apply_effort(request: dict, model: Mapping, requested=None) -> dict:
    """Apply the resolved control in place and return an honest decision record."""
    decision = resolve_effort(model, requested)
    if decision["thinking_disabled"]:
        _disable_thinking(request, model)
    elif decision["upstream_effort"] is not None:
        request["reasoning_effort"] = decision["upstream_effort"]
        # Effort wins over a model-preset numeric budget when both controls are
        # documented as exclusive. Do not send a provider-invalid combination.
        options = model.get("parameter_options") or {}
        option = options.get("thinking_budget", {}) if isinstance(options, Mapping) else {}
        if isinstance(option, Mapping) and option.get("mutually_exclusive_with") == "reasoning_effort":
            request.pop("thinking_budget", None)
            kwargs = request.get("chat_template_kwargs")
            if isinstance(kwargs, dict) and "thinking_budget" in kwargs:
                request["chat_template_kwargs"] = {key: val for key, val in kwargs.items() if key != "thinking_budget"}
    return decision
