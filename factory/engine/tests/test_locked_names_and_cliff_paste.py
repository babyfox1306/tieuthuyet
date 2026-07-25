"""Tests: locked_names (Đòn 1+2) + EG-16b cliffhanger paste (Đòn 3)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from factory.engine.lib.export_gate import (
    check_eg16_cliffhanger_paste,
    find_cliffhanger_paste,
)
from factory.engine.lib.locked_names import (
    UNKNOWN_UNTIL_REVEAL,
    apply_locked_names_after_pass,
    extract_name_locks_from_prose,
    format_locked_names_block,
    merge_locked_names,
    sanitize_state_for_locked_names,
    state_mentions_emily_as_housekeeper,
)

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "factory" / "workspaces"
SECOND = WS / "the-second-wife" / "books" / "01"
SALT = WS / "the-salt-room" / "books" / "01"
KESSLER = WS / "the-kessler-line" / "books" / "01"


def _ready(ws_book: Path, ch: int) -> Path:
    return ws_book / "pipeline" / "ready" / f"ch_{ch:03d}.txt"


def _plan_cliffs(ws_book: Path) -> dict[int, str]:
    path = ws_book / "master_plan.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for p in data.get("chapter_plans") or data.get("chapter_beats") or []:
        ch = int(p.get("chapter") or 0)
        cliff = p.get("cliffhanger") or ""
        if ch and isinstance(cliff, str):
            out[ch] = cliff
    return out


class LockedNamesUnitTests(unittest.TestCase):
    def test_extract_clara_and_anna_and_em(self) -> None:
        ch2 = _ready(SECOND, 2).read_text(encoding="utf-8")
        ch4 = _ready(SECOND, 4).read_text(encoding="utf-8")
        ch5 = _ready(SECOND, 5).read_text(encoding="utf-8")
        locks = {}
        for text in (ch2, ch4, ch5):
            locks = merge_locked_names(locks, extract_name_locks_from_prose(text))
        self.assertEqual(locks.get("narrator_alias"), "Anna")
        self.assertEqual(locks.get("previous_housekeeper"), "Clara")
        self.assertEqual(locks.get("E.M."), UNKNOWN_UNTIL_REVEAL)

    def test_first_lock_wins_over_emily(self) -> None:
        locks = {"previous_housekeeper": "Clara", "E.M.": UNKNOWN_UNTIL_REVEAL}
        ch6 = _ready(SECOND, 6).read_text(encoding="utf-8")
        merged = merge_locked_names(locks, extract_name_locks_from_prose(ch6))
        self.assertEqual(merged["previous_housekeeper"], "Clara")
        # Emily must not overwrite Clara
        self.assertNotEqual(merged.get("previous_housekeeper"), "Emily")

    def test_format_block(self) -> None:
        block = format_locked_names_block(
            {
                "previous_housekeeper": "Clara",
                "narrator_alias": "Anna",
                "E.M.": UNKNOWN_UNTIL_REVEAL,
            }
        )
        self.assertIn("LOCKED NAMES", block)
        self.assertIn("Clara", block)
        self.assertIn("Anna", block)
        self.assertIn(UNKNOWN_UNTIL_REVEAL, block)


class SecondWifeStateSimTests(unittest.TestCase):
    """Replay extract+sanitize over ready chapters / polluted state — no LLM."""

    def test_replay_locked_names_clara_anna_no_emily(self) -> None:
        state: dict = {
            "current_book": 1,
            "current_chapter": 0,
            "timeline": [],
            "character_status": {},
            "open_threads": [],
            "facts_established": [],
            "phrases_used": [],
            "locked_names": {},
        }
        for ch in range(1, 11):
            path = _ready(SECOND, ch)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            # Simulate polluted LLM facts after ch6 confrontation
            if ch == 6:
                state.setdefault("facts_established", []).extend(
                    [
                        "The previous housekeeper was named Clara and left in the night.",
                        "The watch belonged to Emily Morrison, a former housekeeper who died.",
                    ]
                )
                state.setdefault("character_status", {}).setdefault(
                    "Narrator", {}
                ).setdefault("knows", []).extend(
                    [
                        "bloodstained shirt with name tag 'Clara'",
                        "The watch belonged to Emily Morrison, a housekeeper who died",
                    ]
                )
            state = apply_locked_names_after_pass(state, text)
            state["current_chapter"] = ch

        locked = state.get("locked_names") or {}
        self.assertEqual(locked.get("previous_housekeeper"), "Clara", locked)
        self.assertEqual(locked.get("narrator_alias"), "Anna", locked)
        self.assertEqual(locked.get("E.M."), UNKNOWN_UNTIL_REVEAL, locked)
        self.assertFalse(
            state_mentions_emily_as_housekeeper(state),
            f"Emily still in housekeeper facts: {json.dumps(state, ensure_ascii=False)[:800]}",
        )
        # Sanitize polluted live state.json the same way
        live = json.loads((SECOND / "state.json").read_text(encoding="utf-8"))
        live["locked_names"] = locked
        cleaned = sanitize_state_for_locked_names(live)
        self.assertFalse(
            state_mentions_emily_as_housekeeper(cleaned),
            "live state sanitize must drop Emily-as-housekeeper",
        )


class CliffhangerPasteSecondWifeTests(unittest.TestCase):
    def test_ch8_flags_duplicate_tail(self) -> None:
        cliffs = _plan_cliffs(SECOND)
        body = _ready(SECOND, 8).read_text(encoding="utf-8")
        cliff = cliffs[8]
        hit = find_cliffhanger_paste(body, cliff)
        self.assertIsNotNone(hit, "ch8 duplicate tail must be detected")
        checks, _ = check_eg16_cliffhanger_paste(body, 8, cliff)
        fails = [c for c in checks if not c.get("passed") and c.get("id") == "EG-16b"]
        self.assertTrue(fails, checks)

    def test_ch1_to_ch7_no_false_positive(self) -> None:
        cliffs = _plan_cliffs(SECOND)
        false_pos: list[int] = []
        for ch in range(1, 8):
            path = _ready(SECOND, ch)
            if not path.exists():
                continue
            body = path.read_text(encoding="utf-8")
            cliff = cliffs.get(ch, "")
            hit = find_cliffhanger_paste(body, cliff)
            if hit:
                false_pos.append(ch)
        self.assertEqual(false_pos, [], f"false positives on ch{false_pos}")


class CliffhangerRegressionPublishedTests(unittest.TestCase):
    def test_salt_room_no_false_positive(self) -> None:
        cliffs = _plan_cliffs(SALT)
        flagged: list[int] = []
        evidence: list[str] = []
        for ch, cliff in cliffs.items():
            path = _ready(SALT, ch)
            if not path.exists():
                # try catalog
                continue
            body = path.read_text(encoding="utf-8")
            hit = find_cliffhanger_paste(body, cliff)
            if hit:
                flagged.append(ch)
                evidence.append(f"ch{ch}:{hit}")
        # Also scan ready files even if plan chapter mismatch
        for path in sorted((SALT / "pipeline" / "ready").glob("ch_*.txt")):
            ch = int(path.stem.split("_")[1])
            cliff = cliffs.get(ch, "")
            if not cliff:
                continue
            hit = find_cliffhanger_paste(path.read_text(encoding="utf-8"), cliff)
            if hit and ch not in flagged:
                flagged.append(ch)
                evidence.append(f"ch{ch}:{hit}")
        self.assertEqual(flagged, [], f"salt-room false positives: {evidence}")

    def test_kessler_payloads_no_false_positive(self) -> None:
        """Kessler has payloads only (no ready). Scan attempt outputs vs End cliffhanger in payload."""
        payloads = KESSLER / "payloads"
        if not payloads.exists():
            self.skipTest("kessler payloads missing")
        flagged: list[str] = []
        # Prefer attempt_1 per chapter when present
        by_ch: dict[int, Path] = {}
        for path in sorted(payloads.glob("ch_*_attempt_*.json")):
            parts = path.stem.split("_")
            # ch_008_attempt_1
            try:
                ch = int(parts[1])
                attempt = int(parts[3])
            except (IndexError, ValueError):
                continue
            prev = by_ch.get(ch)
            if prev is None:
                by_ch[ch] = path
            else:
                prev_att = int(prev.stem.split("_")[3])
                if attempt < prev_att:
                    by_ch[ch] = path

        for ch, path in sorted(by_ch.items()):
            data = json.loads(path.read_text(encoding="utf-8"))
            body = data.get("output") or ""
            payload = data.get("user_payload") or ""
            m = __import__("re").search(
                r"End cliffhanger:\s*(.+)", payload, __import__("re").I
            )
            cliff = m.group(1).strip() if m else ""
            if not cliff or not body:
                continue
            hit = find_cliffhanger_paste(body, cliff)
            if hit:
                flagged.append(f"ch{ch:03d}:{hit.get('end_similarity')}")
        self.assertEqual(flagged, [], f"kessler false positives: {flagged}")


if __name__ == "__main__":
    unittest.main()
