"""Tests for LOCKED CANON injection and context sanitization in prompt_builder."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from factory.engine.lib.canon_registry import (
    CanonRegistry,
    CharacterCanon,
    build_canon_registry,
    sanitize_text_for_registry,
)
from factory.engine.lib.prompt_builder import (
    build_chapter_prompt,
    format_prior_summaries,
    render_locked_canon_block,
)
from factory.engine.lib.write_guards import load_prior_chapter_excerpt
from factory.engine.paths import chapter_pipeline_path

CANON_YAML = """\
characters:
  female_lead:
    canonical: Mara Vale
    allowed_aliases: []
  male_lead:
    canonical: Elias Crane
    allowed_aliases: []
pov_mode: third_person_limited
"""

BASE_PLAN = {
    "chapter": 2,
    "title": "Night Visit",
    "slug": "night-visit",
    "one_line_summary": "Jude checks on Mara after strange sounds.",
    "beat_summary": "Asher arrives; Mara is unsettled.",
    "must_happen": ["a", "b", "c"],
    "must_not": ["x", "y"],
    "opens_with": "Footsteps in the hall.",
    "cliffhanger": "REMEMBER scratched in the sill.",
    "signature_detail_hint": "blue dress",
    "emotional_beat": "fear",
    "spice": 1,
    "spice_note": "",
    "chapter_task": "Write chapter 2 (1600-1900 words).",
    "carries_to_next": "Mara stays.",
}


def _registry_with_forbidden() -> CanonRegistry:
    return CanonRegistry(
        workspace_id="test",
        book=1,
        book_slug="01-test",
        chapter_count=10,
        target_language="en",
        pov_mode="third_person_limited",
        spice_max=1,
        characters={
            "female_lead": CharacterCanon(
                role="female_lead",
                canonical="Mara Vale",
                forbidden_aliases=[],
            ),
            "male_lead": CharacterCanon(
                role="male_lead",
                canonical="Elias Crane",
                forbidden_aliases=["Jude", "Jude Croft", "Jude Ashford", "Asher", "Asher Croft"],
            ),
        },
    )


def _write_ws(root: Path) -> Path:
    ws = root / "canon-prompt-test"
    ws.mkdir()
    (ws / "canon_registry.yaml").write_text(CANON_YAML, encoding="utf-8")
    (ws / "concept.yaml").write_text(
        yaml.dump(
            {
                "title": "Canon Prompt Test",
                "must_avoid": [
                    "Any explicit sexual content / spice above level 1",
                    "Gore or body-horror as the main scare",
                ],
                "must_include": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (ws / "direction.yaml").write_text(
        yaml.dump(
            {
                "id": "canon-prompt-test",
                "book": 1,
                "book_slug": "01-canon-prompt-test",
                "total_chapters": 10,
                "target_language": "en",
                "spice_default": 1,
                "audience": "women 18-35",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (ws / "bible").mkdir()
    (ws / "bible" / "series.json").write_text(
        json.dumps(
            {
                "leads": {
                    "female": {"name": "Mara Vale"},
                    "male": {"name": "Elias Crane"},
                },
                "supporting_cast": [],
                "content_rules": ["No on-page sex", "Dread over shock"],
            }
        ),
        encoding="utf-8",
    )
    (ws / "bible" / "narrative").mkdir()
    (ws / "bible" / "narrative" / "book_arc.json").write_text(
        json.dumps(
            {
                "lead_internal_arc": {
                    "Mara Vale": "arc",
                    "Asher Croft": "arc",
                }
            }
        ),
        encoding="utf-8",
    )
    book_dir = ws / "books" / "01"
    book_dir.mkdir(parents=True)
    (book_dir / "master_plan.json").write_text(
        json.dumps(
            {
                "book": 1,
                "total_chapters": 10,
                "chapter_plans": [
                    {
                        "chapter": 1,
                        "title": "Arrival",
                        "beat_summary": "A man named Jude Ashford approaches Mara.",
                        "one_line_summary": "Jude arrives.",
                        "must_happen": ["a", "b", "c"],
                        "must_not": ["x", "y"],
                        "opens_with": "Hook",
                        "cliffhanger": "End",
                        "signature_detail_hint": "bear",
                        "spice": 1,
                        "chapter_task": "Write chapter 1 (1600-1900 words).",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return ws


class TestRenderLockedCanonBlock(unittest.TestCase):
    def test_block_names_elias_and_forbids_jude_asher(self) -> None:
        block = render_locked_canon_block(_registry_with_forbidden())
        self.assertIn("LOCKED CANON", block)
        self.assertIn("Male lead: Elias Crane ONLY", block)
        self.assertIn("Jude", block)
        self.assertIn("Asher", block)
        self.assertIn("Mara Vale", block)
        self.assertIn("NO first-person", block)
        self.assertIn("MAX level 1", block)


class TestSanitizeText(unittest.TestCase):
    def test_jude_to_elias(self) -> None:
        reg = _registry_with_forbidden()
        self.assertIn(
            "Elias Crane",
            sanitize_text_for_registry("Jude knocked on the door.", reg),
        )
        self.assertNotIn("Jude", sanitize_text_for_registry("Jude knocked.", reg))

    def test_asher_to_elias(self) -> None:
        reg = _registry_with_forbidden()
        out = sanitize_text_for_registry("Asher stood in the doorway.", reg)
        self.assertIn("Elias Crane", out)
        self.assertNotIn("Asher", out)


class TestFormatPriorSummaries(unittest.TestCase):
    def test_story_so_far_sanitizes_jude(self) -> None:
        reg = _registry_with_forbidden()
        prior = format_prior_summaries(
            [{"chapter": 1, "one_line_summary": "Jude visits Mara at the house."}],
            through_ch=2,
            empty_line="(none)",
            registry=reg,
        )
        self.assertIn("Elias Crane", prior)
        self.assertNotIn("Jude", prior)


class TestBuildChapterPromptCanon(unittest.TestCase):
    def _direction(self) -> dict:
        return {
            "target_language": "en",
            "audience": "women 18-35",
            "spice_default": 1,
            "book": 1,
        }

    def test_locked_canon_above_bible_and_story_so_far(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            prior = [{"chapter": 1, "one_line_summary": "Jude arrives at the house."}]
            prompt = build_chapter_prompt(
                BASE_PLAN,
                prior_plans=prior,
                direction=self._direction(),
                chapter=2,
                series_bible=json.loads((ws / "bible" / "series.json").read_text()),
                ws=ws,
            )
            locked = prompt.index("LOCKED CANON")
            bible = prompt.index("CHARACTER BIBLE")
            story = prompt.index("STORY SO FAR")
            self.assertLess(locked, bible)
            self.assertLess(locked, story)
            self.assertIn("Male lead: Elias Crane ONLY", prompt)
            self.assertIn("Jude", prompt)  # in Never write: forbidden list
            self.assertIn("Elias Crane arrives", prompt)
            self.assertNotIn("Jude arrives", prompt)

    def test_concept_must_avoid_in_locked_canon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            prompt = build_chapter_prompt(
                BASE_PLAN,
                prior_plans=[],
                direction=self._direction(),
                chapter=2,
                series_bible=json.loads((ws / "bible" / "series.json").read_text()),
                ws=ws,
            )
            self.assertIn("Content boundaries (MUST AVOID):", prompt)
            self.assertIn("Any explicit sexual content / spice above level 1", prompt)
            self.assertIn("Gore or body-horror as the main scare", prompt)
            self.assertIn("Dread over shock", prompt)
            # Boundaries sit inside LOCKED CANON, before bible
            locked = prompt.index("LOCKED CANON")
            bounds = prompt.index("Content boundaries (MUST AVOID):")
            bible = prompt.index("CHARACTER BIBLE")
            self.assertLess(locked, bounds)
            self.assertLess(bounds, bible)

    def test_spice_capped_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            plan = dict(BASE_PLAN)
            plan["spice"] = 3
            buf = io.StringIO()
            with redirect_stdout(buf):
                prompt = build_chapter_prompt(
                    plan,
                    prior_plans=[],
                    direction=self._direction(),
                    chapter=2,
                    series_bible={},
                    ws=ws,
                )
            out = buf.getvalue()
            self.assertIn("WARN", out)
            self.assertIn("plan spice 3", out)
            self.assertIn("registry max 1", out)
            self.assertIn("[SPICE] Level 1 (sweet)", prompt)
            self.assertNotIn("EXPLICIT 18+", prompt)


class TestPriorExcerptSanitization(unittest.TestCase):
    def test_excerpt_replaces_asher_with_elias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            ready = chapter_pipeline_path(ws, 1, "ready", 1)
            ready.parent.mkdir(parents=True, exist_ok=True)
            ready.write_text(
                "# Chapter 1: Test\n\nAsher stood at the gate watching Mara.\n",
                encoding="utf-8",
            )
            excerpt = load_prior_chapter_excerpt(ws, 1, 2)
            self.assertIn("Elias Crane", excerpt)
            self.assertNotIn("Asher", excerpt)


class TestBuildCanonRegistryIntegration(unittest.TestCase):
    def test_registry_forbidden_from_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            (ws / "bible" / "narrative" / "book_arc.json").write_text(
                json.dumps(
                    {
                        "lead_internal_arc": {
                            "Mara Vale": "arc",
                            "Asher Croft": "arc",
                        }
                    }
                ),
                encoding="utf-8",
            )
            reg = build_canon_registry(ws, 1)
            forbidden = " ".join(reg.characters["male_lead"].forbidden_aliases).lower()
            self.assertIn("asher", forbidden)


if __name__ == "__main__":
    unittest.main()
