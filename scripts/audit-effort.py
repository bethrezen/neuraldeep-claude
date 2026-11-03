#!/usr/bin/env python3
"""Audit Claude effort mapping across the cached NeuralDeep model catalog.

Dry run by default. --execute sends one billable gateway request for each
distinct translated control on each visible model/billing route. Responses
demonstrate API acceptance, not a provider's internal reasoning budget.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from neuraldeep_claude import catalog, protocol
from neuraldeep_claude.config import atomic_json, local_token, source_revision
from neuraldeep_claude.effort import CLAUDE_LEVELS, describe
from neuraldeep_claude.integration import active_port
from neuraldeep_claude.transport import UpstreamError, request

MARKER = "ND_EFFORT_AUDIT_OK"
CONTROL_FIELDS = ("reasoning_effort", "enable_thinking", "preserve_thinking",
                  "thinking", "thinking_budget", "chat_template_kwargs")


def now():
    return datetime.now(timezone.utc)


def effort_controls(translated):
    return {key: translated[key] for key in CONTROL_FIELDS if key in translated}


def control_key(route, controls):
    return route, json.dumps(controls, sort_keys=True)


def histories(root):
    """Read previous provider probes as historical acceptance, with provenance."""
    evidence = {}
    relative = ".local/model-probes.json"
    path = root / relative
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("checks", []):
            for item in row["checks"]:
                if item["kind"] == "effort" or (item["kind"] == "text" and not item["effort_requested"]):
                    controls = effort_controls(row.get("parameters", {}))
                    if item["effort_requested"]:
                        controls["reasoning_effort"] = item["effort_requested"]
                    evidence[control_key(row["model"], controls)] = {
                        "source": row.get("run_receipt") or relative,
                        "at": item.get("started_at"), "status": item["status"],
                        "scope": item["kind"],
                    }
    relative = ".local/new-effort-probes.json"
    path = root / relative
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["checks"]:
            route = f"nd/{item['model']}@{data['billing']}"
            evidence[control_key(route, effort_controls(item["request"]))] = {
                "source": relative, "at": item["started_at"], "status": item["status"],
                "scope": "effort",
            }
    for path in sorted((root / ".local/effort-audit").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("rows", []):
            for item in row["controls"]:
                if item["status"] == "passed":
                    evidence[control_key(row["route"], item["controls"])] = {
                        "source": str(path.relative_to(root)), "at": data.get("finished_at"),
                        "status": "PASS", "scope": "live-gateway-effort",
                    }
    return evidence


def diagnostic_body(route, level, max_tokens):
    return {
        "model": route,
        "max_tokens": max_tokens,
        "output_config": {"effort": level},
        "messages": [{"role": "user", "content": f"Reply with exactly {MARKER}."}],
    }


def build_plan(data, evidence, billing, max_tokens, routes, missing_history=False):
    rows = []
    jobs = []
    selected = {catalog.resolve(data, route)["id"] for route in routes}
    for route, original in sorted(data["models"].items()):
        if billing != "all" and original["billing"] != billing:
            continue
        if selected and route not in selected:
            continue
        visibility = catalog.picker_status(data, original)
        opaque = catalog.gateway_alias(route)
        row = {"route": route, "desktop_id": opaque, "visibility": visibility,
               "effort_status": original.get("effort_status"),
               "claude_effort": describe(original), "controls": []}
        rows.append(row)
        if visibility == "retired":
            try:
                catalog.resolve(data, opaque)
            except catalog.RetiredModelError:
                row["retirement_verified"] = True
                continue
            raise RuntimeError(f"Retired route unexpectedly resolves: {route}")
        model = catalog.resolve(data, opaque)
        if model["id"] != route or model["billing"] != original["billing"]:
            raise RuntimeError(f"Desktop route resolved to wrong model/billing: {route}")
        groups = {}
        for level in CLAUDE_LEVELS:
            body = diagnostic_body(opaque, level, max_tokens)
            translated = protocol.to_openai(body, model, model["upstream_id"])
            if translated["model"] != original["upstream_id"]:
                raise RuntimeError(f"Wrong upstream model: {route}")
            controls = effort_controls(translated)
            fingerprint = control_key(route, controls)
            if fingerprint not in groups:
                item = {"controls": controls, "claude_levels": [],
                        "gateway_probe_level": level, "status": "planned" if visibility == "visible" else "hidden"}
                historical = evidence.get(fingerprint)
                if historical:
                    item["historical_provider_response"] = historical
                groups[fingerprint] = item
                if visibility == "visible":
                    if missing_history and historical and historical["status"] in ("PASS", "accepted"):
                        item["status"] = "covered-by-history"
                    else:
                        jobs.append((route, body, item))
            groups[fingerprint]["claude_levels"].append(level)
        row["controls"] = list(groups.values())
    return rows, jobs


def probe(base, token, body, timeout):
    started = time.monotonic()
    try:
        response = request("POST", "/v1/messages", token, body, base=base, timeout=timeout)
    except UpstreamError as exc:
        result = {"status": "http-error", "http_status": exc.status}
    except (OSError, ValueError) as exc:
        result = {"status": "connection-or-response-error", "error_type": type(exc).__name__}
    else:
        blocks = response.get("content", [])
        answer = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        result = {"status": "passed" if answer.strip() == MARKER and response.get("model") == body["model"]
                  else "unexpected-response", "http_status": 200,
                  "model_matches": response.get("model") == body["model"],
                  "marker_matches": answer.strip() == MARKER, "stop_reason": response.get("stop_reason"),
                  "usage": response.get("usage"), "provider_internal_effort": "unproven"}
    return result | {"elapsed_seconds": round(time.monotonic() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send inference requests, including wallet charges")
    parser.add_argument("--billing", choices=("all", "subscription", "wallet"), default="all")
    parser.add_argument("--model", action="append", default=[], help="Restrict to exact model/billing route; repeatable")
    parser.add_argument("--missing-history", action="store_true",
                        help="Probe only control shapes without a matching successful historical response")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    if min(args.timeout, args.max_tokens) < 1:
        parser.error("timeout and max-tokens must be positive")
    if not (ROOT / ".local/catalog.json").is_file():
        parser.error("Run python scripts/nd.py models update to create a cached catalog first")
    data = catalog.load(ROOT)
    rows, jobs = build_plan(data, histories(ROOT), args.billing, args.max_tokens, args.model, args.missing_history)
    if not rows:
        parser.error("No routes match selection")
    counts = {mode: sum(row["visibility"] == "visible" and row["route"].endswith("@" + mode)
                        for row in rows) for mode in ("subscription", "wallet")}
    requests = {mode: sum(group["status"] == "planned" for row in rows
                          if row["route"].endswith("@" + mode) for group in row["controls"])
                for mode in counts}
    report = {"started_at": now().isoformat(), "catalog_refreshed_at": data["refreshed_at"],
              "source_revision": source_revision(), "execute": args.execute,
              "visible_route_counts": counts, "gateway_request_counts": requests,
              "covered_by_history": sum(group["status"] == "covered-by-history"
                                        for row in rows for group in row["controls"]),
              "offline_stock_level_cells": sum(len(group["claude_levels"]) for row in rows
                                              for group in row["controls"]),
              "diagnostic_max_tokens": args.max_tokens, "workers": args.workers,
              "scope": "offline Claude request translation; optional live gateway acceptance, no UI or provider internals",
              "rows": rows}
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    base = f"http://127.0.0.1:{active_port(ROOT)}"
    health = request("GET", "/health", base=base, timeout=5)
    if health.get("revision") != report["source_revision"] or health.get("direct_network") is not True:
        parser.error("Gateway must be active on the current source revision with direct upstream networking")
    token = local_token(ROOT)
    started = now()
    receipt = ROOT / ".local/effort-audit" / (started.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    report["gateway_revision"] = health["revision"]
    atomic_json(receipt, report, private=True)
    print(f"{len(jobs)} probes ({requests}); receipt {receipt}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(probe, base, token, body, args.timeout): (route, item)
                   for route, body, item in jobs}
        for future in as_completed(pending):
            route, item = pending[future]
            item.update(future.result())
            atomic_json(receipt, report, private=True)
            print(f"{route} {item['claude_levels']}: {item['status']}", flush=True)
    report["finished_at"] = now().isoformat()
    report["passed"] = sum(item["status"] == "passed" for _, _, item in jobs)
    atomic_json(receipt, report, private=True)
    return 0 if report["passed"] == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
