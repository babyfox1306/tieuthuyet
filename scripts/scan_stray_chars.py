# -*- coding: utf-8 -*-
"""Scan chapter txt for non-Vietnamese stray characters."""
import re
import sys
from pathlib import Path

ALLOWED = re.compile(
    r"^[\u0009\u000A\u000D"
    r"\u0020-\u007E"
    r"\u00A0-\u024F"
    r"\u1E00-\u1EFF"
    r"\u2010-\u2027\u2030-\u205E"
    r"\u20AB"
    r"]+$"
)

ROOT = Path(__file__).parent


def scan(path: Path) -> list[tuple[int, str, str]]:
    bad: list[tuple[int, str, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for j, ch in enumerate(line):
            if not ALLOWED.match(ch):
                bad.append((i, ch, f"U+{ord(ch):04X}"))
    return bad


def main() -> None:
    for name in sys.argv[1:] or [
        "chapter1_output.txt",
        "chapter2_output.txt",
        "chapter3_output_18plus.txt",
    ]:
        p = ROOT / name
        issues = scan(p)
        print(f"\n=== {name} ===")
        if not issues:
            print("  CLEAN")
        else:
            for ln, ch, code in issues:
                print(f"  line {ln}: {code} {repr(ch)}")


if __name__ == "__main__":
    main()
