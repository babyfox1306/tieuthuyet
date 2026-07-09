# -*- coding: utf-8 -*-
"""Call 9router for CEO romance chapters."""
import argparse
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).parent

SPICE_SNIPPETS = {
    1: "## [SPICE] Mức 1 (sweet)\nCăng thẳng tình cảm, ánh mắt, gần chạm — không thân mật thể xác.",
    2: "## [SPICE] Mức 2 (steamy)\nCơ thể gần nhau, nụ hôn, sức hút thể xác rõ — dừng trước cảnh giường chiếu, fade-to-black.",
    3: "## [SPICE] Mức 3 (explicit 18+)\nCảnh thân mật đầy đủ, mô tả cụ thể, hai người trên 18 đồng thuận, giữ bible nhân vật. Không non-con / không trẻ vị thành niên.",
}


def word_count_vi(text: str) -> int:
    body = re.sub(r"^#.*$", "", text, flags=re.M).strip()
    return len(re.findall(r"\S+", body))


def apply_spice(prompt: str, level: int) -> str:
    """Replace or append [SPICE] block in prompt."""
    snippet = SPICE_SNIPPETS[level]
    if re.search(r"## \[SPICE\].*", prompt, flags=re.S):
        return re.sub(r"## \[SPICE\].*", snippet, prompt, count=1, flags=re.S)
    return prompt.rstrip() + "\n\n" + snippet + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CEO romance chapter via 9router")
    parser.add_argument("--chapter", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--spice", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--prompt", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.prompt:
        prompt_path = args.prompt
    elif args.chapter == 1:
        prompt_path = ROOT / "prompt_chapter1_ceo.txt"
    elif args.chapter == 3:
        prompt_path = ROOT / "prompt_chapter3_ceo_explicit.txt"
        args.spice = 3  # ch3 template is explicit-first
    else:
        prompt_path = ROOT / "prompt_chapter2_ceo_v2.txt"

    suffix = {1: "", 2: "_steamy", 3: "_18plus"}[args.spice]
    out_path = args.out or ROOT / f"chapter{args.chapter}_output{suffix}.txt"

    prompt = prompt_path.read_text(encoding="utf-8")
    if args.chapter != 3:
        prompt = apply_spice(prompt, args.spice)

    client = OpenAI(base_url="http://localhost:20128/v1", api_key="local")
    resp = client.chat.completions.create(
        model="kr/claude-sonnet-4.5",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.88,
        max_tokens=8192,
    )
    out = resp.choices[0].message.content or ""
    out_path.write_text(out, encoding="utf-8")
    wc = word_count_vi(out)
    print(f"OK -> {out_path} | spice={args.spice} | ~{wc} words | {len(out)} chars", file=sys.stderr)
    if wc < 1500:
        print(f"WARN: under 1500 words ({wc})", file=sys.stderr)


if __name__ == "__main__":
    main()
