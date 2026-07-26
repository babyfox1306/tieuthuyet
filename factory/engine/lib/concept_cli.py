"""concept — chỉ đạo câu chuyện từ tác giả trước develop-narrative."""

from __future__ import annotations

from pathlib import Path

import yaml

from factory.engine.lib.narrative_schema import (
    concept_content_errors,
    concept_is_ready,
    concept_validation_errors,
    load_concept,
)
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import workspace_dir

def _out(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))

CONCEPT_TEMPLATE = """# CHỈ ĐẠO CÂU CHUYỆN — BẠN ĐIỀN, MÁY KHÔNG TỰ ĐOÁN
concept_status: draft
target_language: vi

title: ""
logline: ""

# Bắt buộc cho compile-intent (form UI cũng có ô riêng):
pov:
  character: ""
  mode: first_person   # first_person | third_person_limited
  tense: past
  single_pov: true

# Chapter map — mỗi chương một beat (hoặc Ch1:/Ch2: trong author_directive):
chapter_map:
  1: "beat khóa chương 1"
  2: "beat khóa chương 2"

author_directive: |
  (ĐIỀN CHỈ ĐẠO CỦA BẠN)
  CAST:
  - Name: ...

surface_plot: ""
true_plot: ""

must_include: []
must_avoid: []
# must_include_by_chapter:
#   "1": ["..."]
#   "10": ["ending obligation"]

ending_book1: ""
hook_book2: ""

notes: ""
"""

INTERVIEW_QUESTIONS = [
    ("title", "Tiêu đề working (có thể đổi sau)?"),
    ("logline", "Logline — 1-2 câu hook?"),
    ("surface_plot", "SURFACE PLOT — độc giả tưởng đang đọc gì?"),
    ("true_plot", "TRUE PLOT — thật ra chuyện gì đang xảy ra bên dưới?"),
    ("ending_book1", "Cuốn 1 phải TRẢ gì cho reader (case đóng)?"),
    ("hook_book2", "Hook mở cuốn 2?"),
]


def _save_concept(ws: Path, data: dict) -> Path:
    path = ws / "concept.yaml"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


def concept_init(ws: Path) -> Path:
    path = ws / "concept.yaml"
    if not path.exists():
        path.write_text(CONCEPT_TEMPLATE, encoding="utf-8")
    return path


def concept_show(ws: Path) -> None:
    _out("\n=== CONCEPT — cau hoi ban can tra loi truoc khi AI sinh narrative ===\n")
    for i, (key, q) in enumerate(INTERVIEW_QUESTIONS, 1):
        _out(f"  {i}. {q}")
    _out("\n  + author_directive: viet tu do — nhan vat, bi an, spice, chuong khoa, dieu cam…")
    _out(f"\nFile: {ws / 'concept.yaml'}")
    concept = load_concept(ws)
    if concept:
        errs = concept_validation_errors(concept)
        status = concept.get("concept_status", "draft")
        _out(f"\nTrang thai: concept_status={status}")
        if errs:
            _out("Chua san sang develop-narrative:")
            for e in errs:
                _out(f"  - {e}")
        else:
            _out("San sang — co the chay develop-narrative")
    else:
        _out("\nChua co concept.yaml — chay: concept --init hoac concept --interview")


def concept_check(ws: Path) -> list[str]:
    return concept_validation_errors(load_concept(ws))


def concept_mark_ready(ws: Path) -> tuple[bool, list[str]]:
    from factory.engine.lib.book_config import sync_chapter_count_from_concept
    from factory.engine.lib.workspace_metadata import sync_direction_from_concept

    concept = load_concept(ws)
    check = concept_content_errors(concept)
    if check:
        return False, check
    concept["concept_status"] = "ready"
    _save_concept(ws, concept)
    sync_direction_from_concept(ws, preserve_gate_status=True, force_setting=True)
    sync_chapter_count_from_concept(ws, book=int(load_direction(ws).get("book") or 1))
    return True, []


def concept_interview(ws: Path) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    existing = load_concept(ws)
    data: dict = {**existing} if existing else {"concept_status": "draft"}

    print("\n=== CONCEPT INTERVIEW — trả lời, Enter trống = giữ/bỏ qua ===\n")

    for key, question in INTERVIEW_QUESTIONS:
        current = data.get(key, "")
        hint = f" [{current}]" if current else ""
        ans = input(f"{question}{hint}\n> ").strip()
        if ans:
            data[key] = ans

    print(
        "\nauthor_directive — viết tự do (kết thúc bằng dòng trống + END trên 1 dòng riêng):\n"
    )
    lines: list[str] = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    if lines:
        data["author_directive"] = "\n".join(lines).strip()

    must_inc = input("\nmust_include (phân cách bằng dấu ; ): ").strip()
    if must_inc:
        data["must_include"] = [x.strip() for x in must_inc.split(";") if x.strip()]

    must_av = input("must_avoid (phân cách bằng dấu ; ): ").strip()
    if must_av:
        data["must_avoid"] = [x.strip() for x in must_av.split(";") if x.strip()]

    data["concept_status"] = "draft"
    path = _save_concept(ws, data)
    print(f"\nĐã lưu -> {path}")
    print("Kiểm tra: concept --check")
    print("Khi ổn: concept --ready → develop-narrative")
    return path
