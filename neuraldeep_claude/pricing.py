"""Native USD estimates from NeuralDeep RUB tariffs and an explicit FX quote."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
import json

from . import catalog
from .config import atomic_json, load_env
from .transport import open_request

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


def positive_rate(value) -> Decimal:
    try:
        rate = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("USD/RUB rate must be a finite positive number") from None
    if not rate.is_finite() or rate <= 0:
        raise ValueError("USD/RUB rate must be a finite positive number")
    return rate


def parse_cbr(raw: bytes) -> dict:
    document = ET.fromstring(raw)
    for node in document.findall("Valute"):
        if node.findtext("CharCode") == "USD":
            nominal = positive_rate(node.findtext("Nominal"))
            value = positive_rate((node.findtext("Value") or "").replace(",", ".")) / nominal
            date = dt.datetime.strptime(document.attrib["Date"], "%d.%m.%Y").date()
            return {"usd_rub_rate": str(value), "effective_date": date.isoformat(),
                    "source": CBR_URL, "currency": "RUB-per-USD"}
    raise ValueError("Official CBR response contains no USD quote")


def fx_quote(root: Path, *, refresh=False) -> dict:
    """Fetch direct, cache for one day; retain dated stale evidence on outage."""
    override = load_env(root).get("NEURALDEEP_USD_RUB_RATE")
    now = dt.datetime.now(dt.timezone.utc)
    if override:
        return {"usd_rub_rate": str(positive_rate(override)), "source": "NEURALDEEP_USD_RUB_RATE",
                "fetched_at": now.isoformat(), "stale": False}
    path = root / ".local/pricing-fx.json"
    previous = None
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            positive_rate(previous["usd_rub_rate"])
            fetched = dt.datetime.fromisoformat(previous["fetched_at"])
            if fetched.tzinfo is None:
                raise ValueError("FX timestamp has no timezone")
            if not refresh and dt.timedelta(0) <= now - fetched < dt.timedelta(days=1):
                return previous | {"stale": False}
        except (ValueError, KeyError, TypeError, OSError):
            previous = None
    try:
        with open_request("GET", "/scripts/XML_daily.asp", base="https://www.cbr.ru", timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("CBR quote response exceeds size limit")
        quote = parse_cbr(raw) | {"fetched_at": now.isoformat(), "stale": False}
        atomic_json(path, quote)
        return quote
    except Exception as error:
        if previous is None:
            raise RuntimeError("Cannot obtain USD/RUB pricing quote; set NEURALDEEP_USD_RUB_RATE in .env or retry") from error
        # Do not replace the cached original timestamp or pretend this is fresh.
        return previous | {"stale": True, "refresh_error": type(error).__name__}


def desktop_report(root: Path, data: dict) -> dict:
    has_wallet_prices = any(model.get("billing") == "wallet" and model.get("pricing")
                            for model in data.get("models", {}).values())
    if has_wallet_prices:
        quote = fx_quote(root)
        report = catalog.native_pricing_report(data, positive_rate(quote["usd_rub_rate"]))
    else:
        # There are no prices to convert; the rate is not used by any quoted row.
        quote = {"source": "not-required-no-published-wallet-prices", "stale": False}
        report = catalog.native_pricing_report(data, Decimal(1))
        report["usd_rub_rate"] = None
    report["fx"] = quote
    report["estimate_note"] = "USD display estimate; NeuralDeep wallet billing remains RUB; prepaid subscription fees excluded"
    atomic_json(root / ".local/desktop-pricing.json", report)
    return report
