"""Model routing — flexible (OmniRoute auto) vs fixed chains."""

from __future__ import annotations

import unittest

from factory.engine.lib.call_9router import (
    _is_auto_model,
    _should_try_next_model,
    resolve_priority_chain,
)


class TestModelRouting(unittest.TestCase):
    def test_is_auto_model(self):
        self.assertTrue(_is_auto_model("auto"))
        self.assertTrue(_is_auto_model("auto/fast"))
        self.assertFalse(_is_auto_model("kr/deepseek-3.2"))

    def test_flexible_auto_only_by_default(self):
        cfg = {
            "model_routing": "flexible",
            "model_priority_groups": {"phase2_write": ["auto", "auto/fast"]},
            "model_priority_by_role": {"writer": "phase2_write"},
            "model_preferences": [],
            "avoid_models": [],
            "avoid_models_by_role": {},
        }
        chain = resolve_priority_chain(cfg, "writer")
        self.assertEqual(chain, ["auto", "auto/fast"])

    def test_flexible_preferences_are_last_resort(self):
        cfg = {
            "model_routing": "flexible",
            "model_priority_groups": {"phase_light": ["auto/fast"]},
            "model_priority_by_role": {"qc": "phase_light"},
            "model_preferences": ["kr/deepseek-3.2", "groq/llama-3.3-70b-versatile"],
            "avoid_models": [],
            "avoid_models_by_role": {},
        }
        chain = resolve_priority_chain(cfg, "qc")
        self.assertEqual(chain[0], "auto/fast")
        self.assertEqual(chain[1:], ["kr/deepseek-3.2", "groq/llama-3.3-70b-versatile"])

    def test_fixed_mode_skips_preferences(self):
        cfg = {
            "model_routing": "fixed",
            "model_priority_groups": {"phase1_plan": ["kr/claude-sonnet-4.5"]},
            "model_priority_by_role": {"architect": "phase1_plan"},
            "model_preferences": ["kr/deepseek-3.2"],
            "avoid_models": [],
            "avoid_models_by_role": {},
        }
        chain = resolve_priority_chain(cfg, "architect")
        self.assertEqual(chain, ["kr/claude-sonnet-4.5"])

    def test_dual_gateway_writer_chain(self):
        cfg = {
            "model_routing": "flexible",
            "model_priority_groups": {
                "phase2_write": ["moi", "auto/fast", "auto", "auto/best-fast", "gh/gpt-4o"]
            },
            "model_priority_by_role": {"writer": "phase2_write"},
            "model_preferences": [],
            "avoid_models": [],
            "avoid_models_by_role": {},
        }
        chain = resolve_priority_chain(cfg, "writer")
        self.assertEqual(chain, ["moi", "auto/fast", "auto", "auto/best-fast", "gh/gpt-4o"])

    def test_404_and_unknown_model_fall_through(self):
        self.assertTrue(
            _should_try_next_model(
                RuntimeError(
                    "Error code: 404 - {'error': {'message': 'No active credentials for provider: auto'}}"
                )
            )
        )
        self.assertTrue(
            _should_try_next_model(
                RuntimeError("model_not_found: auto/best-fast not in catalog")
            )
        )

    def test_avoid_models_applied(self):
        cfg = {
            "model_routing": "flexible",
            "model_priority_groups": {"phase2_write": ["auto", "gh/gpt-4o"]},
            "model_priority_by_role": {"writer": "phase2_write"},
            "model_preferences": [],
            "avoid_models": ["gh/gpt-4o"],
            "avoid_models_by_role": {},
        }
        chain = resolve_priority_chain(cfg, "writer")
        self.assertEqual(chain, ["auto"])


if __name__ == "__main__":
    unittest.main()
