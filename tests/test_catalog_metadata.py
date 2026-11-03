import copy
import json
import unittest
from decimal import Decimal

from neuraldeep_claude import catalog


def sample_catalog():
    models = {}
    for billing in ("subscription", "wallet"):
        mid = "nd/qwen3.8-27b@" + billing
        models[mid] = {
            "id": mid, "upstream_id": "qwen3.8-27b", "billing": billing,
            "capabilities": {"tools": True, "vision": True, "reasoning": True},
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "limit": {"context": 262144, "output": 235929},
            "pricing": {"unit": "token", "currency": "RUB", "input_per_1m": 30.6,
                        "output_per_1m": 153.0, "cached_input_per_1m": 7.65},
            "efforts": ["low", "medium", "xhigh"], "default_effort": "xhigh",
            "effort_status": "documented",
            "parameters": {"chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True}},
            "parameters_status": "experimental-family-preset",
            "created": 1677610602,
        }
    models["nd/claude-haiku-5.5@wallet"] = {
        "id": "nd/claude-haiku-5.5@wallet", "upstream_id": "claude-haiku-5.5", "billing": "wallet",
        "capabilities": {"tools": True, "vision": True, "reasoning": True},
        "limit": {"context": 1000000, "output": 128000}, "input_limit": 90000,
        "input_limit_status": "provider-documented-approximate",
        "pricing": {"unit": "token", "currency": "RUB", "input_per_1m": 12.5,
                    "output_per_1m": 62.5, "cached_input_per_1m": 1.25},
        "last_probe": {"status": "failed", "at": "2026-11-02T00:00:00Z", "failures": [{"error": "private diagnostic"}]},
    }
    models["nd/future-model@wallet"] = {
        "id": "nd/future-model@wallet", "upstream_id": "future-model", "billing": "wallet",
        "capabilities": {"tools": False, "vision": False, "reasoning": False},
    }
    models["nd/large-model@wallet"] = {
        "id": "nd/large-model@wallet", "upstream_id": "large-model", "billing": "wallet",
        "capabilities": {"tools": True, "vision": True, "reasoning": True},
        "limit": {"context": 1310720},
    }
    return {
        "refreshed_at": "2026-11-02T00:00:00Z", "models": models,
        "aliases": {"qwen3.8-27b": "nd/qwen3.8-27b@subscription",
                    "claude-haiku-5.5": "nd/claude-haiku-5.5@wallet",
                    "future-model": "nd/future-model@wallet", "large-model": "nd/large-model@wallet"},
        "limits": {"subscription": {"private_account_balance": 999, "key": {"key": "do-not-publish"}}},
    }


class DiscoveryMetadataTests(unittest.TestCase):
    def test_discovery_labels_distinguish_effort_from_thinking_presets(self):
        source = sample_catalog()
        expected = {
            "qwen3.8-27b": "effort: low/medium/xhigh",
            "future-model": "no thinking",
            "large-model": "effort unspecified by Hub",
        }
        for model_id, policy, label in (
            ("qwen3.6-35b-a3b", {"effort_status": "ignored-by-provider"}, "fixed thinking; no effort"),
            ("kimi-k2.7-code", {"thinking_options": ["enabled"]}, "thinking always on"),
            ("gemma-4-31b", {"thinking_options": ["enabled", "disabled"]}, "thinking toggle only upstream"),
            ("qwen3.7-plus", {"parameter_options": {"thinking_budget": {}}}, "budget upstream; Hub unverified"),
        ):
            route = f"nd/{model_id}@wallet"
            source["models"][route] = {
                "id": route, "upstream_id": model_id, "billing": "wallet",
                "capabilities": {"reasoning": True, "tools": True, "vision": True},
                "limit": {"context": 1310720, "output": 235929},
                **policy,
            }
            expected[model_id] = label
        for row in catalog.discovery_data(source)["data"]:
            model_id = row["neuraldeep"]["upstream_id"]
            if model_id in expected:
                self.assertIn(expected[model_id], row["description"])

    def test_explicit_visibility_policy_hides_only_named_models_until_a_successful_probe(self):
        source = sample_catalog()
        source["picker_policy"] = {
            "hide_until_probe_passes": ["qwen3.8-27b"],
            "excluded_upstream_ids": ["large-model"],
        }
        # Unrelated failed Haiku stays visible; failures are not a general
        # deletion policy. Hidden routes remain available for explicit rechecks.
        rows = {row["model"] for row in catalog.picker(source)}
        self.assertIn("nd/claude-haiku-5.5@wallet", rows)
        self.assertNotIn("nd/large-model@wallet", rows)
        self.assertNotIn("nd/qwen3.8-27b@subscription", rows)
        self.assertEqual(catalog.resolve(source, "qwen3.8-27b")["billing"], "subscription")
        source["models"]["nd/qwen3.8-27b@subscription"]["last_probe"] = {"status": "passed"}
        rows = {row["model"] for row in catalog.picker(source)}
        self.assertIn("nd/qwen3.8-27b@subscription", rows)
        self.assertNotIn("nd/qwen3.8-27b@wallet", rows)
        self.assertEqual(len(source["models"]), 5)  # Diagnostics are retained.

    def test_retired_raw_and_opaque_routes_fail_explicitly_without_redirect(self):
        source = sample_catalog()
        source["picker_policy"] = {"excluded_upstream_ids": ["qwen3.8-27b"]}
        original = copy.deepcopy(source)
        for requested in ("qwen3.8-27b", "nd/qwen3.8-27b@wallet",
                          "nd/qwen3.8-27b@wallet~medium",
                          catalog.gateway_alias("nd/qwen3.8-27b@wallet~medium") + "[1m]"):
            with self.subTest(requested=requested), self.assertRaisesRegex(catalog.RetiredModelError, "replace it explicitly"):
                catalog.resolve(source, requested)
        self.assertEqual(source, original)

    def test_automatic_discovery_starts_with_chosen_subscription_and_wallet_rows_follow(self):
        source = sample_catalog()
        rows = catalog.discovery_data(source)["data"]
        self.assertEqual(rows[0]["neuraldeep"]["route"], "nd/qwen3.8-27b@subscription")
        self.assertIn("ПОДПИСКА", rows[0]["display_name"])
        self.assertIn("ctx 262144", rows[0]["display_name"])
        modes = [row["neuraldeep"]["billing"] for row in rows]
        self.assertEqual(modes, sorted(modes))
        wallet_rows = [row["neuraldeep"]["route"] for row in rows if row["neuraldeep"]["billing"] == "wallet"]
        expected_wallet = [row["model"] for row in catalog.picker(source) if "@wallet" in row["model"]]
        self.assertEqual(wallet_rows, expected_wallet)

    def test_every_billing_route_survives_native_gateway_filter_without_effort_duplicates(self):
        source = sample_catalog()
        result = catalog.discovery_data(source)
        expected = {row["model"] for row in catalog.picker(source)}
        self.assertEqual(expected, set(source["models"]))
        self.assertTrue(all("~" not in entry for entry in expected))
        self.assertEqual({m["neuraldeep"]["route"] for m in result["data"]}, expected)
        self.assertEqual(len({m["id"] for m in result["data"]}), len(expected))
        for entry in result["data"]:
            self.assertTrue(entry["id"].startswith("anthropic/neuraldeep/"))
            self.assertLessEqual(len(entry["description"]), 100)
            self.assertNotIn("anthropic_family_tier", entry)
            self.assertNotIn("behaves_as", entry)
            model = catalog.resolve(source, entry["id"])
            self.assertEqual(model["billing"], entry["neuraldeep"]["billing"])
            self.assertEqual(model.get("selected_effort"), entry["neuraldeep"].get("selected_effort"))
            self.assertEqual(model["upstream_id"], entry["neuraldeep"]["upstream_id"])
        self.assertEqual(result["first_id"], result["data"][0]["id"])
        self.assertEqual(result["last_id"], result["data"][-1]["id"])
        self.assertFalse(result["has_more"])

    def test_old_opaque_effort_ids_roundtrip_without_reappearing_in_discovery(self):
        source = sample_catalog()
        routes = {entry["id"] for entry in catalog.discovery_data(source)["data"]}
        for billing in ("subscription", "wallet"):
            base = "nd/qwen3.8-27b@" + billing
            for effort in source["models"][base]["efforts"]:
                old = catalog.gateway_alias(base + "~" + effort)
                self.assertNotIn(old, routes)
                model = catalog.resolve(source, old + "[1m]")
                self.assertEqual(model["id"], base)
                self.assertEqual(model["selected_effort"], effort)

    def test_effective_context_controls_1m_without_inventing_unknown_output_caps(self):
        rows = {m["neuraldeep"]["route"]: m for m in catalog.discovery_data(sample_catalog())["data"]}
        haiku = rows["nd/claude-haiku-5.5@wallet"]
        self.assertEqual(haiku["max_input_tokens"], 90000)
        self.assertFalse(haiku["supports_1m"])
        self.assertEqual(haiku["neuraldeep"]["limit"]["context"], 1000000)
        large = rows["nd/large-model@wallet"]
        self.assertTrue(large["supports_1m"])
        self.assertEqual(large["max_input_tokens"], 1310720)
        self.assertNotIn("output", large["neuraldeep"]["limit"])
        unknown = rows["nd/future-model@wallet"]
        self.assertNotIn("max_input_tokens", unknown)
        self.assertNotIn("limit", unknown["neuraldeep"])
        self.assertFalse(unknown["supports_1m"])

    def test_currency_subscription_and_cache_metadata_keep_their_actual_semantics(self):
        source = sample_catalog()
        rows = {m["neuraldeep"]["route"]: m for m in catalog.discovery_data(source)["data"]}
        sub = rows["nd/qwen3.8-27b@subscription"]["neuraldeep"]
        wallet = rows["nd/qwen3.8-27b@wallet"]["neuraldeep"]
        self.assertTrue(sub["is_default_billing"])
        self.assertFalse(wallet["is_default_billing"])
        self.assertEqual(sub["pricing"]["currency"], "RUB")
        self.assertEqual(sub["pricing_application"], "wallet-reference-tariff; subscription-quota-applies")
        self.assertEqual(wallet["pricing_application"], "wallet-tariff")
        self.assertEqual(wallet["cache"]["explicit_prompt_cache_creation"], "unverified")
        self.assertTrue(wallet["cache"]["cached_input_tariff_reported"])
        self.assertEqual(rows["nd/claude-haiku-5.5@wallet"]["neuraldeep"]["cache"]["explicit_prompt_cache_creation"], "unsupported")
        self.assertEqual(sub["parameters"]["chat_template_kwargs"], {"enable_thinking": True, "preserve_thinking": True})
        self.assertEqual(sub["claude_effort"]["mapping"], {
            "low": "low", "medium": "medium", "high": "xhigh", "xhigh": "xhigh", "max": "xhigh"})
        self.assertTrue(sub["claude_effort"]["adjustable"])
        self.assertFalse(rows["nd/future-model@wallet"]["neuraldeep"]["claude_effort"]["adjustable"])
        self.assertNotIn("private_account_balance", json.dumps(rows))
        self.assertNotIn("do-not-publish", json.dumps(rows))
        self.assertNotIn("private diagnostic", json.dumps(rows))

    def test_discovery_cannot_mutate_the_cached_catalog_and_empty_list_is_well_formed(self):
        source = sample_catalog()
        snapshot = copy.deepcopy(source)
        result = catalog.discovery_data(source)
        result["data"][0]["neuraldeep"]["capabilities"]["tools"] = False
        self.assertEqual(source, snapshot)
        self.assertEqual(catalog.discovery_data({"models": {}, "aliases": {}}), {
            "data": [], "has_more": False, "first_id": None, "last_id": None,
        })


class NativePricingTests(unittest.TestCase):
    def test_wallet_rub_tariffs_convert_to_usd_once_per_billing_model(self):
        source = sample_catalog()
        report = catalog.native_pricing_report(source, Decimal("76.5"))
        prices = {row["name"]: row for row in report["models"]}
        rate = prices[catalog.gateway_alias("nd/qwen3.8-27b@wallet")]
        self.assertEqual(rate, {"name": rate["name"], "inputPerMtok": 0.4,
                               "outputPerMtok": 2.0, "cacheReadPerMtok": 0.1, "cacheWritePerMtok": 0})
        self.assertEqual(len(prices), 3)
        for effort in ("low", "medium", "xhigh"):
            self.assertNotIn(catalog.gateway_alias("nd/qwen3.8-27b@wallet~" + effort), prices)
        self.assertEqual(report["currency"], "USD")
        self.assertEqual(report["usd_rub_rate"], "76.5")
        self.assertEqual(catalog.native_pricing(source, Decimal("76.5")), report["models"])
        self.assertIn("not-free-service", report["subscription_note"])
        self.assertIn("tariff-unpublished", report["cache_write_note"])

    def test_prepaid_subscription_incremental_cost_and_schema_required_cache_rates(self):
        report = catalog.native_pricing_report(sample_catalog(), 80)
        for row in report["models"]:
            self.assertEqual(set(row), {"name", "inputPerMtok", "outputPerMtok", "cacheReadPerMtok", "cacheWritePerMtok"})
            for field, value in row.items():
                if field != "name":
                    self.assertIsInstance(value, (float, int))
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 10000)
            if catalog.resolve(sample_catalog(), row["name"])["billing"] == "subscription":
                self.assertTrue(all(value == 0 for field, value in row.items() if field != "name"))

    def test_missing_unknown_and_out_of_native_range_prices_are_recorded_not_guessed(self):
        source = sample_catalog()
        source["models"]["nd/claude-haiku-5.5@wallet"]["pricing"]["input_per_1m"] = "Infinity"
        report = catalog.native_pricing_report(source, 80)
        missing = {row["route"]: row["reason"] for row in report["omitted"]}
        self.assertIn("nd/future-model@wallet", missing)
        self.assertIn("nd/large-model@wallet", missing)
        self.assertEqual(missing["nd/claude-haiku-5.5@wallet"], "published-tariff-outside-native-0-to-10000-usd-range")
        source["models"]["nd/qwen3.8-27b@wallet"]["pricing"].pop("cached_input_per_1m")
        report = catalog.native_pricing_report(source, 80)
        self.assertEqual(len(report["models"]), 1)  # Known subscription base route remains usable.
        self.assertEqual(len(report["omitted"]), 4)

    def test_fx_must_be_finite_and_positive(self):
        for rate in (0, -1, float("nan"), float("inf"), Decimal("NaN"), None, "not-a-number", True):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, "finite positive"):
                catalog.native_pricing(sample_catalog(), rate)


if __name__ == "__main__":
    unittest.main()
