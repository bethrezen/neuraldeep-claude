import copy
import json
from pathlib import Path
import unittest

from neuraldeep_claude import effort, protocol


class EffortTests(unittest.TestCase):
    def test_stock_selector_mapping_is_total_monotone_and_native_only(self):
        cases = [
            (["low", "medium", "xhigh"], ["low", "medium", "xhigh", "xhigh", "xhigh"]),
            (["low", "medium", "high"], ["low", "medium", "high", "high", "high"]),
            (["low", "high", "max"], ["low", "high", "high", "max", "max"]),
            (["high", "max"], ["high", "high", "high", "max", "max"]),
            (list(effort.CLAUDE_LEVELS), list(effort.CLAUDE_LEVELS)),
        ]
        rank = {level: index for index, level in enumerate(effort.CLAUDE_LEVELS)}
        for levels, expected in cases:
            with self.subTest(levels=levels):
                model = {"efforts": levels}
                actual = [effort.resolve_effort(model, level)["upstream_effort"] for level in effort.CLAUDE_LEVELS]
                self.assertEqual(actual, expected)
                self.assertTrue(all(level in levels for level in actual))
                self.assertEqual([rank[level] for level in actual], sorted(rank[level] for level in actual))
                self.assertEqual(list(effort.describe(model)["mapping"].values()), expected)

    def test_missing_auto_default_and_unsorted_native_levels_use_real_maximum(self):
        model = {"efforts": ["xhigh", "low", "medium", "medium"], "default_effort": "medium"}
        for requested in (None, "auto", "default"):
            with self.subTest(requested=requested):
                request = {}
                decision = effort.apply_effort(request, model, requested)
                self.assertEqual(request["reasoning_effort"], "xhigh")
                self.assertEqual(decision["selection"], "maximum-default")

    def test_glm_aliases_and_documented_off_control_preserve_flags(self):
        model = {"upstream_id": "glm-5.2", "efforts": ["high", "max"],
                 "effort_aliases": {"low": "high", "medium": "high", "xhigh": "max"},
                 "reasoning_off_efforts": ["none", "minimal"],
                 "parameters": {"thinking": {"type": "enabled", "clear_thinking": False}}}
        original = copy.deepcopy(model)
        for native in ("none", "minimal"):
            request = protocol.to_openai({"output_config": {"effort": native}}, model, "glm-5.2")
            self.assertEqual(request["thinking"], {"type": "disabled", "clear_thinking": False})
            self.assertNotIn("reasoning_effort", request)
        self.assertEqual(protocol.to_openai({"output_config": {"effort": "medium"}}, model, "glm-5.2")["reasoning_effort"], "high")
        self.assertEqual(protocol.to_openai({"output_config": {"effort": "xhigh"}}, model, "glm-5.2")["reasoning_effort"], "max")
        self.assertEqual(model, original)

    def test_qwen_documented_off_and_exclusive_budget_do_not_mutate_preset(self):
        model = {"upstream_id": "qwen3.8-flash", "efforts": ["low", "medium", "xhigh"],
                 "effort_aliases": {"minimal": "low", "high": "xhigh", "max": "xhigh"},
                 "reasoning_off_efforts": ["none"],
                 "parameters": {"enable_thinking": True, "preserve_thinking": True, "thinking_budget": 8192},
                 "parameter_options": {"thinking_budget": {"mutually_exclusive_with": "reasoning_effort"}}}
        original = copy.deepcopy(model)
        off = protocol.to_openai({"output_config": {"effort": "none"}}, model, "qwen3.8-flash")
        self.assertFalse(off["enable_thinking"])
        self.assertTrue(off["preserve_thinking"])
        self.assertNotIn("reasoning_effort", off)
        self.assertNotIn("thinking_budget", off)
        low = protocol.to_openai({"output_config": {"effort": "minimal"}}, model, "qwen3.8-flash")
        self.assertEqual(low["reasoning_effort"], "low")
        self.assertTrue(low["enable_thinking"])
        self.assertNotIn("thinking_budget", low)
        self.assertEqual(model, original)

    def test_nested_qwen_thinking_control_is_copied_and_preservation_survives(self):
        model = {"efforts": ["low", "xhigh"], "reasoning_off_efforts": ["none"],
                 "parameters": {"chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True,
                                                          "thinking_budget": 4096}}}
        original = copy.deepcopy(model)
        request = protocol.to_openai({"output_config": {"effort": "none"}}, model, "actual")
        self.assertEqual(request["chat_template_kwargs"], {"enable_thinking": False, "preserve_thinking": True})
        self.assertEqual(model, original)

    def test_models_without_discrete_effort_accept_every_stock_selection_without_fabrication(self):
        presets = [
            {"thinking": {"type": "enabled"}},
            {"enable_thinking": True, "preserve_thinking": True},
            {},
            {"enable_thinking": True, "thinking_budget": 16384},
        ]
        for preset in presets:
            model = {"efforts": [], "parameters": preset}
            original = copy.deepcopy(model)
            for level in (*effort.CLAUDE_LEVELS, "auto"):
                with self.subTest(preset=preset, level=level):
                    request = protocol.to_openai({"output_config": {"effort": level}}, model, "actual")
                    self.assertNotIn("reasoning_effort", request)
                    self.assertEqual({key: request[key] for key in preset}, preset)
                    self.assertEqual("thinking_budget" in request, "thinking_budget" in preset)
                    decision = effort.resolve_effort(model, level)
                    self.assertFalse(decision["adjustable"])
                    self.assertIsNone(decision["upstream_effort"])
            self.assertEqual(model, original)

    def test_stock_selector_overrides_legacy_route_and_suffix_is_only_a_fallback(self):
        model = {"efforts": ["low", "medium", "xhigh"], "selected_effort": "medium"}
        self.assertEqual(effort.resolve_effort(model)["upstream_effort"], "medium")
        for requested, expected in zip(effort.CLAUDE_LEVELS, ("low", "medium", "xhigh", "xhigh", "xhigh")):
            self.assertEqual(effort.resolve_effort(model, requested)["upstream_effort"], expected)
        self.assertEqual(effort.resolve_effort(model, "auto")["upstream_effort"], "xhigh")
        with self.assertRaises(ValueError):
            effort.resolve_effort(model, "typo")

    def test_unknown_values_reject_without_silent_fallback(self):
        for value in ("turbo", "none", "minimal", "", 4, False, {}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                effort.resolve_effort({"efforts": ["low", "high"]}, value)
        for value in ("high", [], False):
            with self.subTest(output_config=value), self.assertRaisesRegex(ValueError, "output_config"):
                protocol.to_openai({"output_config": value}, {}, "actual")

    def test_future_unmapped_native_vocabulary_is_honest_and_preserves_explicit_preset(self):
        model = {"efforts": ["small", "large"], "parameters": {"reasoning_effort": "large"}}
        info = effort.describe(model)
        self.assertFalse(info["adjustable"])
        self.assertEqual(info["status"], "unmapped-provider-vocabulary")
        for level in effort.CLAUDE_LEVELS:
            request = protocol.to_openai({"output_config": {"effort": level}}, model, "actual")
            self.assertEqual(request["reasoning_effort"], "large")

    def test_all_curated_family_profiles_accept_all_stock_levels(self):
        root = Path(__file__).resolve().parents[1]
        profiles = json.loads((root / "config/family-capabilities.json").read_text())["models"]
        for name, profile in profiles.items():
            model = copy.deepcopy(profile) | {"upstream_id": name}
            for level in effort.CLAUDE_LEVELS:
                with self.subTest(model=name, level=level):
                    request = protocol.to_openai({"output_config": {"effort": level}}, model, name)
                    if profile.get("efforts"):
                        self.assertIn(request["reasoning_effort"], profile["efforts"])
                    else:
                        self.assertNotIn("reasoning_effort", request)


if __name__ == "__main__":
    unittest.main()
