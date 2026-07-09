#!/usr/bin/env python3
"""Story factory — batch chapter production via 9router."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_factory.lib.call_9router import call_9router, load_config, parse_json_response
from story_factory.lib.machine_qc import machine_pass, machine_qc, save_machine_issues, word_count_vi
from story_factory.lib.state_updater import load_state, save_state, update_state_after_pass

FACTORY = Path(__file__).resolve().parent


def series_dir(name: str | None = None) -> Path:
    cfg = load_config()
    sid = name or cfg["default_series"]
    return FACTORY / "series" / sid


def chapters_dir(sd: Path, bucket: str) -> Path:
    p = sd / "chapters" / bucket
    p.mkdir(parents=True, exist_ok=True)
    return p


def chapter_path(sd: Path, bucket: str, n: int) -> Path:
    return chapters_dir(sd, bucket) / f"ch_{n:03d}.txt"


def issues_path(sd: Path, bucket: str, n: int) -> Path:
    return chapters_dir(sd, bucket) / f"ch_{n:03d}_issues.json"


def qc_report_path(sd: Path, bucket: str, n: int) -> Path:
    return chapters_dir(sd, bucket) / f"ch_{n:03d}_qc.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_architect(args: argparse.Namespace) -> None:
    cfg = load_config()
    sd = series_dir(args.series)
    sd.mkdir(parents=True, exist_ok=True)
    user = json.dumps(
        {
            "genre": "ngôn tình hiện đại",
            "sub_niche": args.niche,
            "spice_level": args.spice or cfg["spice_level"],
            "planned_books": args.books,
        },
        ensure_ascii=False,
    )
    raw, log = call_9router("architect", user, max_tokens=8192)
    bible = parse_json_response(raw)
    save_json(sd / "series_bible.json", bible)
    print(f"[architect] OK -> {sd / 'series_bible.json'} ({log.get('usage', {})})")


def cmd_outline(args: argparse.Namespace) -> None:
    sd = series_dir(args.series)
    bible = load_json(sd / "series_bible.json")
    prev = ""
    if args.book > 1:
        prev_path = sd / f"book_{args.book - 1}_outline.json"
        if prev_path.exists():
            prev = prev_path.read_text(encoding="utf-8")[:2000]
    user = json.dumps(
        {"series_bible": bible, "book_number": args.book, "previous_book_summary": prev},
        ensure_ascii=False,
    )
    raw, log = call_9router("outliner", user, max_tokens=16384)
    outline = parse_json_response(raw)
    out = sd / f"book_{args.book}_outline.json"
    save_json(out, outline)
    print(f"[outline] OK -> {out} beats={len(outline.get('chapter_beats', []))}")


def build_writer_payload(sd: Path, beat: dict, cfg: dict) -> str:
    bible = load_json(sd / "series_bible.json")
    state = load_state(sd)
    spice = beat.get("spice_note", "none")
    if spice == "none":
        spice_map = {1: "sweet", 2: "steamy", 3: "explicit"}
        spice = spice_map.get(cfg["spice_level"], "sweet")
    return json.dumps(
        {
            "series_bible": bible,
            "story_state": state,
            "chapter_beat": beat,
            "spice_level": cfg["spice_level"],
            "spice_note": spice,
            "banned_phrases": cfg.get("banned_phrases", []),
            "min_words": cfg["min_word_count"],
            "max_words": cfg.get("max_word_count", 2000),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_qc_payload(sd: Path, chapter: str) -> str:
    bible = load_json(sd / "series_bible.json")
    state = load_state(sd)
    return json.dumps(
        {"chapter": chapter, "series_bible": bible, "story_state": state},
        ensure_ascii=False,
    )


def write_one_chapter(sd: Path, beat: dict, cfg: dict) -> tuple[int, str]:
    """Returns (chapter_num, status) where status in ready|needs_fix|needs_review|skipped."""
    ch = beat["chapter"]
    if chapter_path(sd, "ready", ch).exists():
        print(f"  ch_{ch:03d} SKIP (already ready)")
        return ch, "skipped"

    print(f"  ch_{ch:03d} writing...")
    raw, wlog = call_9router("writer", build_writer_payload(sd, beat, cfg), max_tokens=8192)
    chapter = raw.strip()
    time.sleep(cfg.get("throttle_seconds", 4))

    state = load_state(sd)
    m_issues = machine_qc(
        chapter,
        min_words=cfg["min_word_count"],
        banned_phrases=cfg.get("banned_phrases", []),
        phrases_already_used=state.get("phrases_used", []),
    )
    if not machine_pass(m_issues):
        chapter_path(sd, "needs_fix", ch).write_text(chapter, encoding="utf-8")
        save_machine_issues(issues_path(sd, "needs_fix", ch), m_issues)
        print(f"  ch_{ch:03d} NEEDS_FIX {list(m_issues.keys())}")
        return ch, "needs_fix"

    qc_raw, _ = call_9router("qc", build_qc_payload(sd, chapter), max_tokens=4096)
    time.sleep(cfg.get("throttle_seconds", 4))
    try:
        qc = parse_json_response(qc_raw)
    except json.JSONDecodeError:
        qc = {"verdict": "FAIL", "fail_reasons": ["qc_json_parse_error"]}

    if qc.get("verdict") != "PASS":
        chapter_path(sd, "needs_review", ch).write_text(chapter, encoding="utf-8")
        save_json(qc_report_path(sd, "needs_review", ch), qc)
        print(f"  ch_{ch:03d} NEEDS_REVIEW {qc.get('fail_reasons', [])}")
        return ch, "needs_review"

    chapter_path(sd, "ready", ch).write_text(chapter, encoding="utf-8")
    save_json(qc_report_path(sd, "ready", ch), qc)
    update_state_after_pass(sd, ch, chapter, book=beat.get("book", 1))
    wc = word_count_vi(chapter)
    print(f"  ch_{ch:03d} READY (~{wc} words)")
    return ch, "ready"


def cmd_write(args: argparse.Namespace) -> None:
    cfg = load_config()
    sd = series_dir(args.series)
    outline = load_json(sd / f"book_{args.book}_outline.json")
    beats = outline.get("chapter_beats", [])
    beats = [b for b in beats if args.from_chapter <= b["chapter"] <= args.to_chapter]

    if not beats:
        print("No beats in range.")
        return

    counts = {"ready": 0, "needs_fix": 0, "needs_review": 0, "skipped": 0}
    for beat in beats:
        beat["book"] = args.book
        _, status = write_one_chapter(sd, beat, cfg)
        counts[status] = counts.get(status, 0) + 1

    print(f"\n[write] done: {counts}")


def cmd_status(args: argparse.Namespace) -> None:
    sd = series_dir(args.series)
    for bucket in ("ready", "needs_fix", "needs_review"):
        d = chapters_dir(sd, bucket)
        txts = list(d.glob("ch_*.txt"))
        print(f"  {bucket}: {len(txts)}")
    if (sd / "story_state.json").exists():
        st = load_state(sd)
        print(f"  state: book {st.get('current_book')} ch {st.get('current_chapter')}")
    if (FACTORY / "factory_log.json").exists():
        logs = json.loads((FACTORY / "factory_log.json").read_text(encoding="utf-8"))
        recent = logs[-10:]
        total_tok = sum(x.get("usage", {}).get("total_tokens", 0) for x in recent)
        print(f"  factory_log: {len(logs)} calls, last 10 used ~{total_tok} tokens")


def cmd_seed(args: argparse.Namespace) -> None:
    """Import existing ch1-3 + seed bible/state from manual work."""
    cfg = load_config()
    sd = series_dir(args.series)
    sd.mkdir(parents=True, exist_ok=True)
    scripts = ROOT / "scripts"

    bible = {
        "title": "Hợp đồng có giá",
        "genre": "ngôn tình hiện đại",
        "sub_niche": "ceo_contract_marriage",
        "spice_level": cfg["spice_level"],
        "planned_books": 5,
        "hook_central": "Hợp đồng hôn nhân 1 năm — tiền đổi tên trên giấy, lửa đổi hai con người",
        "tropes": ["contract marriage", "CEO", "enemies to lovers", "slow burn"],
        "world_rules": ["Thành A hiện đại", "tập đoàn Hàn", "gia tộc ép cưới họ Lâm"],
        "series_arc": [
            {"book": 1, "thesis": "Giả vợ thật lửa", "ending_hook": "Bí mật Uyên lộ một phần"},
            {"book": 2, "thesis": "Gia tộc vs tự do", "ending_hook": "DT chọn bỏ hay ở"},
            {"book": 3, "thesis": "Tình thật hay hợp đồng", "ending_hook": "Đe dọa từ quá khứ"},
            {"book": 4, "thesis": "Vết thương quá khứ", "ending_hook": "Họ Lâm counter"},
            {"book": 5, "thesis": "Chọn nhau không hợp đồng", "ending_hook": "HEA"},
        ],
        "characters": {
            "female_lead": {
                "name": "Diệp Tâm",
                "age": 24,
                "voice": "sắc, mỉa, câu dài có logic, không cầu xin",
                "tics": ["cắn má khi căng", "đếm nhịp", "móng đỏ"],
                "lines": ["tự trọng > tiền"],
                "internal_voice": "chửi thầm/mỉa",
            },
            "male_lead": {
                "name": "Hàn Thừa Uyên",
                "age": 30,
                "voice": "ít lời, câu ngắn nặng, không giải thích",
                "tics": ["gõ ngón tay tay vịn ghế", "ánh mắt định giá"],
                "lines": ["kiểm soát tuyệt đối"],
                "wound": "không tin tình cảm, quá khứ chưa lộ",
            },
        },
        "supporting_cast": [
            {"name": "Từ Tố Nhi", "role": "mẹ Hàn"},
            {"name": "Lâm Vũ Trinh", "role": "mẹ cô dâu họ Lâm"},
            {"name": "Lê Hồng Vân", "role": "mẹ Diệp Tâm ICU"},
        ],
    }
    save_json(sd / "series_bible.json", bible)

    state = {
        "current_book": 1,
        "current_chapter": 3,
        "timeline": [
            "ký hợp đồng hôn nhân 1 năm",
            "đeo nhẫn, mẹ họ Lâm xuất hiện sảnh",
            "gặp mẹ Hàn Từ Tố Nhi tại cafe",
            "về biệt thự Q2",
            "đêm đầu thân mật sau tin Thử xem",
        ],
        "character_status": {
            "Diệp Tâm": {
                "location": "biệt thự Q2 phòng riêng",
                "knows": ["hợp đồng giả", "mẹ chồng nghi", "viện phí 18tr/tuần"],
                "relationship_uyen": "căng + hút + không thừa nhận",
                "mood": "cảnh giác",
            },
            "Hàn Thừa Uyên": {
                "location": "biệt thự Q2 phòng khác",
                "knows": ["DT thách thức", "cần đóng vai trước gia tộc"],
                "relationship_dt": "kiểm soát + bị thu hút",
                "mood": "lạnh, tính toán",
            },
        },
        "open_threads": [
            "Lâm Vũ Trinh đến 7h sáng",
            "viện phí mẹ Lê Hồng Vân tuần tới",
            "DT công việc designer — Uyên bảo hủy sáng mai",
        ],
        "facts_established": [
            "Hợp đồng 1 năm, 1 tỷ",
            "Uyên ngủ phòng khác sau đêm ch3",
            "DT mẹ ICU tên Lê Hồng Vân",
            "Nhẫn đeo khi ra ngoài",
            "Gọi là đến trong 1 giờ",
        ],
        "spice_progression": "ch3 explicit đầu tiên",
        "phrases_used": ["định giá một món hàng", "không vội không nóng"],
    }
    save_state(sd, state)

    mapping = [
        (scripts / "chapter1_output.txt", 1),
        (scripts / "chapter2_output.txt", 2),
        (scripts / "chapter3_output_18plus.txt", 3),
    ]
    for src, n in mapping:
        if src.exists():
            dst = chapter_path(sd, "ready", n)
            shutil.copy2(src, dst)
            print(f"  seeded ready/ch_{n:03d}.txt")

    # Minimal outline stub for ch4+
    outline_path = sd / "book_1_outline.json"
    if not outline_path.exists():
        beats = []
        stubs = {
            4: ("Sáng sớm mẹ Lâm đến, đóng vai vợ chồng", "giả vờ vs thật", "DT phát hiện Uyên che giấu điều gì"),
            5: ("Công ty DT — Uyên can thiệp?", "quyền lực", "Đồng nghiệp nhìn nhẫn"),
        }
        for i in range(4, 16):
            if i in stubs:
                s, t, c = stubs[i]
            else:
                s, t, c = (f"Beat placeholder ch{i}", "tension", f"Cliff ch{i}")
            beats.append(
                {
                    "chapter": i,
                    "beat_summary": s,
                    "tension_type": t,
                    "cliffhanger": c,
                    "signature_detail_hint": "chi tiết đời thường cụ thể",
                    "spice_note": "steamy" if i % 5 == 0 else "none",
                }
            )
        save_json(outline_path, {"book": 1, "title": "Hợp đồng có giá", "chapter_beats": beats})
        print(f"  stub outline ch4-15 -> {outline_path}")

    print(f"[seed] OK -> {sd}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Story factory")
    parser.add_argument("--series", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_arch = sub.add_parser("architect")
    p_arch.add_argument("--niche", default="ceo_contract_marriage")
    p_arch.add_argument("--spice", type=int, default=None)
    p_arch.add_argument("--books", type=int, default=5)

    p_out = sub.add_parser("outline")
    p_out.add_argument("--book", type=int, default=1)

    p_w = sub.add_parser("write")
    p_w.add_argument("--book", type=int, default=1)
    p_w.add_argument("--from-chapter", type=int, default=4)
    p_w.add_argument("--to-chapter", type=int, default=15)

    sub.add_parser("status")
    sub.add_parser("seed")

    args = parser.parse_args()
    handlers = {
        "architect": cmd_architect,
        "outline": cmd_outline,
        "write": cmd_write,
        "status": cmd_status,
        "seed": cmd_seed,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
