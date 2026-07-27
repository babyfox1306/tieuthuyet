"""Model routing — flexible (OmniRoute auto) vs fixed chains + external failover."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from factory.engine.lib.call_9router import (
    _format_gateway_error,
    _is_auto_model,
    _should_try_next_model,
    call_9router,
    resolve_external_providers,
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

    def test_connection_errors_fall_through(self):
        self.assertTrue(_should_try_next_model(RuntimeError("Connection refused")))
        self.assertTrue(_should_try_next_model(RuntimeError("Request timed out")))

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

    def test_html_404_gateway_hint(self):
        msg = _format_gateway_error(
            RuntimeError("Error code: 404 - <!DOCTYPE html>Skip to content Page not found"),
            base_url="http://localhost:20128/v1",
            models=["auto"],
        )
        self.assertIn("OmniRoute gateway broken", msg)
        self.assertIn("probe-models", msg)


class TestExternalFallback(unittest.TestCase):
    def test_resolve_skips_incomplete(self):
        self.assertEqual(
            resolve_external_providers(
                {
                    "external_fallback": {
                        "enabled": True,
                        "base_url": "https://x/v1",
                        "models": ["m"],
                    }
                }
            ),
            [],
        )

    def test_resolve_from_env(self):
        cfg = {
            "external_fallback": {
                "enabled": True,
                "name": "paid",
                "base_url": "https://api.example.com/v1",
                "api_key_env": "FACTORY_TEST_EXT_KEY",
                "models": ["gpt-4o"],
            }
        }
        with patch.dict(os.environ, {"FACTORY_TEST_EXT_KEY": "sk-test"}, clear=False):
            providers = resolve_external_providers(cfg)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["api_key"], "sk-test")
        self.assertEqual(providers[0]["models"], ["gpt-4o"])

    def test_resolve_disabled(self):
        cfg = {
            "external_fallback": {
                "enabled": False,
                "base_url": "https://api.example.com/v1",
                "api_key": "sk",
                "models": ["gpt-4o"],
            }
        }
        self.assertEqual(resolve_external_providers(cfg), [])

    def test_omni_fail_jumps_to_external(self):
        cfg = {
            "base_url": "http://localhost:20128/v1",
            "api_key": "local",
            "retry_max": 0,
            "model_routing": "flexible",
            "model_priority_groups": {"phase_light": ["auto"]},
            "model_priority_by_role": {"qc": "phase_light"},
            "model_preferences": [],
            "avoid_models": [],
            "avoid_models_by_role": {},
            "temperature": {"qc": 0.1},
            "external_fallback": {
                "enabled": True,
                "name": "external",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-ext",
                "models": ["gpt-4o"],
            },
        }

        class _Msg:
            content = "OK from external"

        class _Choice:
            message = _Msg()

        class _Usage:
            prompt_tokens = 1
            completion_tokens = 1
            total_tokens = 2

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        omni_client = MagicMock()
        omni_client.chat.completions.create.side_effect = RuntimeError(
            "Error code: 429 - quota exceeded"
        )
        ext_client = MagicMock()
        ext_client.chat.completions.create.return_value = _Resp()

        clients = [omni_client, ext_client]

        def _openai(**_kwargs):
            return clients.pop(0)

        with (
            patch("factory.engine.lib.call_9router.load_config", return_value=cfg),
            patch("factory.engine.lib.call_9router.load_role", return_value="sys"),
            patch("factory.engine.lib.call_9router._append_log"),
            patch("factory.engine.lib.call_9router.OpenAI", side_effect=_openai),
        ):
            text, meta = call_9router("qc", "ping", max_tokens=8)

        self.assertEqual(text, "OK from external")
        self.assertEqual(meta["provider"], "external")
        self.assertEqual(meta["fallback_from"], "omni")
        self.assertEqual(meta["model"], "gpt-4o")


if __name__ == "__main__":
    unittest.main()
