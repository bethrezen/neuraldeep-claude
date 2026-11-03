"""Refresh both authenticated catalogs; preserve real billing identities."""
from __future__ import annotations
import copy
import datetime
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, DecimalException
from pathlib import Path
from .config import atomic_json, key_for, load_env
from .effort import describe as describe_effort
from .transport import request


class RetiredModelError(ValueError):
    """A deliberately retired ID requires an explicit user replacement."""


def gateway_alias(model_id: str) -> str:
    """Anthropic-protocol route; its label always identifies the real model.

    Desktop filters provider strings for model-family words before looking at
    custom profiles. Opaque routing IDs let the documented custom inference
    list describe the adapter's protocol without impersonating another model.
    """
    return "anthropic/neuraldeep/" + str(int.from_bytes(hashlib.sha256(model_id.encode()).digest()[:16], "big"))

def policy(model: str, reasoning: bool) -> dict:
    if not reasoning:
        return {"efforts": [], "effort_status": "not-supported"}
    if model in ("gpt-oss-120b", "gpt-oss-20b"):
        return {"efforts": ["low", "medium", "high"], "default_effort": "high",
                "effort_status": "neuraldeep-documented" if model == "gpt-oss-120b" else "family-documented-live-accepted"}
    if model == "qwen3.8-27b":
        return {"efforts": ["low", "medium", "xhigh"], "effort_aliases": {"high": "xhigh"},
                "default_effort": "xhigh", "upstream_default_effort": "low", "effort_status": "neuraldeep-documented"}
    if model.startswith("qwen3.6"):
        return {"efforts": [], "effort_status": "ignored-by-provider"}
    if model.startswith("deepseek-v4"):
        return {"efforts": ["low", "high", "max"], "default_effort": "max", "effort_status": "upstream-documented-neuraldeep-experimental"}
    if model == "glm-5.3":
        return {"efforts": ["low", "high", "max"], "default_effort": "max", "effort_status": "upstream-documented-neuraldeep-experimental"}
    if model == "gemma-4-31b":
        return {"efforts": [], "effort_status": "upstream-thinking-toggle-only",
                "thinking_options": ["enabled", "disabled"],
                "sources": ["https://ai.google.dev/gemma/docs/capabilities/thinking"]}
    return {"efforts": [], "effort_status": "unknown"}

def experimental_parameters(mid: str, reasoning: bool) -> dict:
    if not reasoning:
        return {}
    if mid.startswith("qwen"):
        return {"chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True}}
    if mid.startswith("deepseek-v4"):
        return {"thinking": {"type": "enabled"}}
    if mid.startswith("glm"):
        return {"thinking": {"type": "enabled", "clear_thinking": False}}
    if mid.startswith("kimi"):
        return {"thinking": {"type": "enabled", "keep": "all"}}
    return {}


def _picker_policy(root: Path) -> dict:
    path = root / "config/picker-policy.json"
    if not path.exists():
        return {"hide_until_probe_passes": [], "excluded_upstream_ids": []}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema", 1) != 1:
        raise ValueError("Picker policy must be a schema 1 JSON object")
    result = {}
    for key in ("hide_until_probe_passes", "excluded_upstream_ids"):
        values = document.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Picker policy " + key + " must be an array of upstream IDs")
        result[key] = list(dict.fromkeys(values))
    return result


def picker_status(catalog: dict, model: dict) -> str:
    """Apply explicit user visibility choices, not a blanket failed-probe filter."""
    policy = catalog.get("picker_policy", {})
    upstream = model["upstream_id"]
    if upstream in policy.get("excluded_upstream_ids", []):
        return "retired"
    if (upstream in policy.get("hide_until_probe_passes", [])
            and model.get("last_probe", {}).get("status") != "passed"):
        return "hidden-until-successful-probe"
    return "visible"


def refresh(root: Path) -> dict:
    env = load_env(root)
    modes = [m for m in ("subscription", "wallet") if env.get("NEURALDEEP_API_KEY_" + m.upper())]
    if not modes:
        raise ValueError("Add NeuralDeep keys to .env first")
    def fetch(mode):
        key = key_for(root, mode)
        return mode, request("GET", "/v1/models", key, timeout=45), request("GET", "/v1/limits", key, timeout=45)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fetched = list(pool.map(fetch, modes))
    overrides_path = root / "config/model-overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")).get("models", {}) if overrides_path.exists() else {}
    families_path = root / "config/family-capabilities.json"
    families = json.loads(families_path.read_text(encoding="utf-8")).get("models", {}) if families_path.exists() else {}
    entries = {}
    services = {}
    limits = {}
    for mode, catalog, quota in fetched:
        actual_mode = quota.get("key", {}).get("billing_mode")
        if actual_mode and actual_mode != mode:
            raise ValueError(f"{mode} key is configured as {actual_mode} in NeuralDeep; correct its mode in cabinet")
        limits[mode] = quota
        all_models = catalog["data"]
        # Option models are currently omitted from /models despite /limits entitlement.
        option_models = [m for opt in quota.get("options", []) for m in opt.get("models", [])]
        for mid in option_models:
            if mid.startswith("qwen3.6-unlim") and not any(x["id"] == mid for x in all_models):
                all_models.append({"id": mid, "type": "chat", "capabilities": {"vision": False, "tools": True, "reasoning": not mid.endswith("-noreason"), "streaming": True}, "limit": {"context": 138000 if "-xl" in mid else 46000, "output": 16384 if "-xl" in mid else 8000}, "metadata_status": "option-entitlement; context-docs-rounded; output-agent-config; vision-unverified"})
        for source in all_models:
            mid = source["id"]
            if mid == "qwen-flash-next-ru" and not source.get("type"):
                canonical = next((m for m in all_models if m["id"] == "qwen3.8-flash-next-ru"), None)
                if canonical:
                    source = copy.deepcopy(canonical) | {"id": mid, "metadata_status": "provider-alias-of-qwen3.8-flash-next-ru"}
            if source.get("type") != "chat":
                services.setdefault(mid, {})[mode] = source
                continue
            m = copy.deepcopy(source)
            m.update(policy(mid, m.get("capabilities", {}).get("reasoning", False)))
            family = copy.deepcopy(families.get(mid, {}))
            if family.get("efforts"):
                family["upstream_default_effort"] = family.get("default_effort")
                family["default_effort"] = family["efforts"][-1]
            m.update(family)
            m.update(overrides.get(mid, {}))
            m["billing"] = mode
            m["upstream_id"] = mid
            m["id"] = "nd/" + mid + ("@wallet" if mode == "wallet" else "@subscription")
            m["parameters"] = (copy.deepcopy(family.get("parameters")) if "parameters" in family else experimental_parameters(mid, m.get("capabilities", {}).get("reasoning", False))) | overrides.get(mid, {}).get("parameters", {})
            m["parameters_status"] = "experimental-family-preset; may be ignored or rejected by NeuralDeep"
            if mid == "claude-haiku-5.5":
                m["input_limit"] = 90000
                m["input_limit_status"] = "provider-documented-approximate"
            entries[m["id"]] = m
    aliases = {}
    probe_path = root / ".local/model-probes.json"
    if probe_path.exists():
        probes = json.loads(probe_path.read_text(encoding="utf-8"))
        for probe in probes.get("checks", []):
            entry = entries.get(probe.get("model"))
            if entry is not None:
                checks = probe.get("checks", [])
                failed = [p for p in checks if p.get("status") != "PASS"]
                entry["last_probe"] = {"at": probe.get("checked_at", probes.get("finished_at", probes.get("updated_at"))), "status": "passed" if checks and not failed else "failed", "failures": [{k: p[k] for k in ("kind", "status", "http_status", "error") if k in p} for p in failed]}
    for m in entries.values():
        mid = m["upstream_id"]
        if mid not in aliases or m["billing"] == "subscription":
            aliases[mid] = m["id"]
    result = {"schema": 1, "refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "models": entries, "aliases": aliases, "service_models": services, "limits": limits, "picker_policy": _picker_policy(root)}
    atomic_json(root / ".local/catalog.json", result, private=True)
    return result

def load(root: Path) -> dict:
    path = root / ".local/catalog.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else refresh(root)
    # Updating visibility does not require inference or a provider metadata call.
    # The public pure helpers consume this embedded policy, never global files.
    result["picker_policy"] = _picker_policy(root)
    return result


def _legacy_routes(catalog: dict):
    """Resolve old session IDs without publishing effort variants in pickers."""
    for mid, model in catalog["models"].items():
        yield mid
        for effort in model.get("efforts", []):
            yield mid + "~" + effort


def resolve(catalog: dict, requested: str) -> dict:
    if requested.endswith("[1m]"):
        requested = requested[:-4]
    if requested.startswith("anthropic/neuraldeep/"):
        matched = next((route for route in _legacy_routes(catalog) if gateway_alias(route) == requested), None)
        if matched is None:
            raise ValueError("Unknown NeuralDeep protocol route; update Desktop config")
        requested = matched
    # Existing sessions and explicit legacy URLs remain valid. New picker rows
    # contain only the base model; native /effort supplies the requested level.
    parts = requested.split("~", 1)
    mid = catalog["aliases"].get(parts[0], parts[0])
    if mid not in catalog["models"] and "nd/" + mid in catalog["models"]:
        mid = "nd/" + mid
    if mid not in catalog["models"]:
        raise ValueError("Unknown model; run models update: " + requested)
    model = copy.deepcopy(catalog["models"][mid])
    if picker_status(catalog, model) == "retired":
        raise RetiredModelError("Retired NeuralDeep model " + model["upstream_id"]
                                + "; replace it explicitly in settings. No automatic redirect is configured.")
    if len(parts) == 2:
        if parts[1] not in model.get("efforts", []):
            raise ValueError("Unsupported effort for " + mid + ": " + parts[1])
        model["selected_effort"] = parts[1]
    return model

def _effort_label(model: dict) -> str:
    levels = model.get("efforts", [])
    if levels:
        prefix = "exp. effort: " if model.get("effort_status", "").endswith("-experimental") else "effort: "
        return prefix + "/".join(levels)
    if not model.get("capabilities", {}).get("reasoning"):
        return "no thinking"
    if model.get("effort_status") == "ignored-by-provider":
        return "fixed thinking; no effort"
    if model.get("thinking_options") in (["always-on"], ["enabled"]):
        return "thinking always on"
    if "thinking_budget" in model.get("parameter_options", {}):
        return "budget upstream; Hub unverified"
    if "disabled" in model.get("thinking_options", []):
        return "thinking toggle only upstream"
    return "effort unspecified by Hub"


def picker(catalog: dict) -> list:
    rows = []
    for mid, model in sorted(catalog["models"].items(), key=lambda pair: (pair[1]["upstream_id"], pair[1]["billing"])):
        if picker_status(catalog, model) != "visible":
            continue
        ctx = model.get("input_limit", model.get("limit", {}).get("context"))
        capabilities = model.get("capabilities", {})
        desc = ", ".join(k for k in ("tools", "vision", "reasoning") if capabilities.get(k))
        desc += f"; context={ctx or 'unknown'}; output={model.get('limit', {}).get('output', 'unknown')}"
        desc += "; " + _effort_label(model)
        badge = "₽ КОШЕЛЁК" if model["billing"] == "wallet" else "ПОДПИСКА"
        if model.get("last_probe", {}).get("status") == "failed":
            badge += "; ПРОВЕРКА НЕ ПРОШЛА"
            desc += "; last probe=" + str(model["last_probe"].get("at"))
        rows.append({"model": mid, "label": f"[{badge}] {model['upstream_id']}", "description": desc})
    return rows


def _discovery_description(model: dict) -> str:
    """Keep the native gateway discovery description within its 100-char limit."""
    ctx = model.get("input_limit", model.get("limit", {}).get("context"))
    output = model.get("limit", {}).get("output")
    parts = [f"context={ctx or 'unknown'}", f"output={output or 'unknown'}", _effort_label(model)]
    capabilities = model.get("capabilities", {})
    enabled = ",".join(k for k in ("tools", "vision", "reasoning") if capabilities.get(k))
    if enabled:
        parts.append(enabled)
    if model.get("selected_effort"):
        parts.append("effort=" + model["selected_effort"])
    if model.get("last_probe", {}).get("status") == "failed":
        parts.append("probe failed")
    # Full pricing, capability, and provenance fields live in the extension below;
    # the stock client's gateway discovery parser only accepts short descriptions.
    return "; ".join(parts)[:100]


def _discovery_metadata(catalog: dict, model: dict, route: str) -> dict:
    """Publish provider metadata without implying stock clients consume it.

    A quoted cached-input tariff is not proof that explicit Anthropic prompt-cache
    creation is supported. Likewise token prices on a subscription-key catalog are
    the provider's wallet tariffs, not metered subscription charges.
    """
    metadata = {
        "schema": 1,
        "provider": "NeuralDeep",
        "route": route,
        "upstream_id": model["upstream_id"],
        "billing": model["billing"],
        "is_default_billing": catalog.get("aliases", {}).get(model["upstream_id"]) == model["id"],
        "pricing_application": "wallet-tariff" if model["billing"] == "wallet" else "wallet-reference-tariff; subscription-quota-applies",
        "claude_effort": describe_effort(model),
        "cache": {
            "explicit_prompt_cache_creation": "unsupported" if model["upstream_id"] in (
                "claude-haiku-5.5", "claude-sonnet-5.5", "claude-opus-5.5"
            ) else "unverified",
            "cached_input_tariff_reported": "cached_input_per_1m" in model.get("pricing", {}),
            "usage_metadata": "forwarded-when-reported-by-provider",
            "cache_creation_tokens_reported_by_adapter": 0,
            "native_cache_write_estimate": "zero-placeholder; adapter-emits-no-cache-creation-tokens; not-a-provider-tariff",
        },
    }
    for name in (
        "capabilities", "modalities", "attachment", "tool_call", "reasoning", "limit",
        "pricing", "efforts", "default_effort", "selected_effort", "effort_aliases",
        "effort_status", "parameters", "parameters_status", "input_limit_status",
        "metadata_status", "sources", "upstream_default_effort", "thinking_options", "parameter_options",
    ):
        if name in model:
            metadata[name] = copy.deepcopy(model[name])
    context = model.get("input_limit", model.get("limit", {}).get("context"))
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        metadata["effective_input_limit"] = context
    if model.get("last_probe"):
        metadata["last_probe"] = {k: model["last_probe"][k] for k in ("at", "status") if k in model["last_probe"]}
    return metadata


def discovery_data(catalog: dict) -> dict:
    """Anthropic-style gateway discovery with truthful NeuralDeep extensions.

    Desktop's gateway parser filters provider IDs, so use the same opaque routes
    as its explicit picker. It consumes only identity/label/description and the
    1M capability; arbitrary limits, RUB pricing and family flags are exposed in
    ``neuraldeep`` for diagnostics and clients that understand the extension.
    Do not use ``anthropic_family_tier`` to impersonate a different model family.
    """
    data = []
    rows = picker(catalog)
    # Desktop's discovered list uses its first row as the initial model when no
    # explicit inferenceModels allowlist is present. Preserve the user's chosen
    # subscription default while retaining stable catalog order within billing.
    rows.sort(key=lambda row: (
        0 if row["model"] == "nd/qwen3.8-27b@subscription" else
        2 if "@wallet" in row["model"].split("~", 1)[0] else 1
    ))
    for row in rows:
        model = resolve(catalog, row["model"])
        context = model.get("input_limit", model.get("limit", {}).get("context"))
        known_context = isinstance(context, int) and not isinstance(context, bool) and context > 0
        entry = {
            "id": gateway_alias(row["model"]),
            "type": "model",
            "display_name": row["label"] + (f" · ctx {context}" if known_context else ""),
            "description": _discovery_description(model),
            "supports_1m": known_context and context >= 1_000_000,
            "neuraldeep": _discovery_metadata(catalog, model, row["model"]),
        }
        if known_context:
            entry["max_input_tokens"] = context
        created = model.get("created")
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            try:
                entry["created_at"] = datetime.datetime.fromtimestamp(created, datetime.timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        if "created_at" not in entry and catalog.get("refreshed_at"):
            entry["created_at"] = catalog["refreshed_at"]
        data.append(entry)
    return {
        "data": data,
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


def native_pricing_report(catalog: dict, usd_rub_rate: Decimal | float) -> dict:
    """Convert published wallet tariffs into the native USD/Mtok schema.

    The caller owns the dated FX quote and its provenance. Subscription rows
    describe zero incremental token charges against prepaid quota. Desktop
    requires all four numeric rate fields; the adapter emits zero cache-creation
    tokens, so its required cache-write estimate is a zero placeholder rather
    than an invented provider tariff or cache capability declaration.
    """
    try:
        fx = Decimal(str(usd_rub_rate))
    except (DecimalException, ValueError, TypeError) as exc:
        raise ValueError("USD/RUB rate must be a finite positive number") from exc
    if not fx.is_finite() or fx <= 0:
        raise ValueError("USD/RUB rate must be a finite positive number")
    models, omitted = [], []
    for row in picker(catalog):
        model = resolve(catalog, row["model"])
        native = {"name": gateway_alias(row["model"])}
        if model["billing"] == "subscription":
            native.update(inputPerMtok=0, outputPerMtok=0, cacheReadPerMtok=0, cacheWritePerMtok=0)
        else:
            pricing = model.get("pricing", {})
            required = ("input_per_1m", "output_per_1m", "cached_input_per_1m")
            reason = None
            if pricing.get("currency") != "RUB" or pricing.get("unit") != "token":
                reason = "missing-or-unsupported-token-currency"
            elif any(pricing.get(name) is None for name in required):
                reason = "missing-published-input-output-or-cache-read-tariff"
            if reason is None:
                for target, source in zip(("inputPerMtok", "outputPerMtok", "cacheReadPerMtok"), required):
                    try:
                        value = Decimal(str(pricing[source])) / fx
                    except (DecimalException, ValueError, TypeError):
                        reason = "invalid-published-tariff"
                        break
                    if not value.is_finite() or value < 0 or value > 10000:
                        reason = "published-tariff-outside-native-0-to-10000-usd-range"
                        break
                    native[target] = float(value)
                native["cacheWritePerMtok"] = 0
            if reason:
                omitted.append({"route": row["model"], "upstream_id": model["upstream_id"], "billing": model["billing"], "reason": reason})
                continue
        models.append(native)
    return {
        "models": models,
        "omitted": omitted,
        "currency": "USD",
        "usd_rub_rate": str(fx),
        "subscription_note": "zero-incremental-token-estimate; prepaid-subscription-quota-not-free-service",
        "cache_write_note": "zero-placeholder; adapter-emits-no-cache-creation-tokens; provider-cache-write-tariff-unpublished",
    }


def native_pricing(catalog: dict, usd_rub_rate: Decimal | float) -> list:
    """Return native pricing rows; use native_pricing_report for omission receipts."""
    return native_pricing_report(catalog, usd_rub_rate)["models"]
