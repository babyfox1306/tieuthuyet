# -*- coding: utf-8 -*-
"""Export chapter .txt files to PDF (Vietnamese-safe fonts)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "pdf"
FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\times.ttf"),
]


def find_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("No Vietnamese-capable TTF found in Windows Fonts")


def md_to_plain(text: str) -> str:
    """Light markdown cleanup for PDF."""
    lines = []
    for line in text.splitlines():
        if line.startswith("# "):
            lines.append(line[2:].strip().upper())
            lines.append("")
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"\*(.+?)\*", r"\1", line)
        lines.append(line)
    return "\n".join(lines)


class ChapterPDF(FPDF):
    def __init__(self, font_path: Path):
        super().__init__(format="A5")
        self.add_font("vn", "", str(font_path))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 16, 16)

    def write_chapter(self, body: str) -> None:
        self.add_page()
        self.set_font("vn", size=11)
        for para in body.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if para.isupper() and len(para) < 80:
                self.set_font("vn", size=13)
                self.multi_cell(0, 8, para, align="C")
                self.ln(4)
                self.set_font("vn", size=11)
                continue
            self.multi_cell(0, 6.5, para)
            self.ln(2)


def export_one(src: Path, dst: Path, font_path: Path) -> None:
    text = src.read_text(encoding="utf-8")
    body = md_to_plain(text)
    pdf = ChapterPDF(font_path)
    pdf.write_chapter(body)
    dst.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dst))


def main() -> None:
    font = find_font()
    files = [
        "chapter1_output.txt",
        "chapter2_output.txt",
        "chapter3_output_18plus.txt",
    ]
    for name in files:
        src = ROOT / name
        if not src.exists():
            print(f"SKIP missing: {src}", file=sys.stderr)
            continue
        dst = OUT_DIR / (src.stem + ".pdf")
        export_one(src, dst, font)
        print(f"OK {dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
