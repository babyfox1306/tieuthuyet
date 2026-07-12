"""target_language — một dòng direction.yaml đổi ngôn ngữ cả pipeline."""

from __future__ import annotations

import re
from typing import Any

# Ký tự lạ theo ngôn ngữ đích
_CJK_RE = re.compile(
    r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef"
    r"\uac00-\ud7af\u3040-\u30ff]"
)
_VN_LETTER_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
# Latin extended letters valid in English prose (café, resumé, naïve, etc.)
_EN_LATIN_EXTENDED_RE = re.compile(
    r"[\u00c0-\u00ff]"
)


def _is_en_latin_extended(ch: str) -> bool:
    return bool(_EN_LATIN_EXTENDED_RE.match(ch))

LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "vi": {
        "label": "tiếng Việt",
        "word_unit": "chữ",
        "target_words": "1600-1900",
        "prose_style_rule": "Tiếng Việt hiện đại, không sến cải lương, không Hán-Việt lỗi thời.",
        "language_only_rule": "CHỈ tiếng Việt — không chèn ký tự Hàn/Trung/Nhật.",
        "foreign_char_desc": "ký tự Hàn/Hán/Nhật lạ",
        "role_header": (
            "Mày là cây bút ngôn tình mạng chuyên nghiệp, viết cho nền tảng đọc trả phí "
            "theo chương (GoodNovel / Dreame / Vella). {audience}. Mục tiêu DUY NHẤT: unlock chương sau."
        ),
        "prior_heading": "ĐÃ XẢY RA",
        "prior_empty": "- (chương đầu — không có chương trước)",
        "tech_heading": "YÊU CẦU KỸ THUẬT",
        "task_heading": "VIỆC CẦN LÀM",
        "must_happen_label": "Phải xảy ra",
        "must_not_label": "Cấm / không được mâu thuẫn",
        "output_instruction": (
            "Chỉ output nội dung chương (có tiêu đề `# Chương N: ...`). Không meta, không checklist."
        ),
        "word_count_patch": "Target 1600-1900 chữ <<language_label>> — dưới 1250 = fail.",
        "spice": {
            1: "## [SPICE] Mức 1 (sweet)\nCăng thẳng tình cảm, ánh mắt, gần chạm — không thân mật thể xác.",
            2: "## [SPICE] Mức 2 (steamy)\nHôn, sức hút cơ thể, căng đến giới hạn — dừng trước cảnh giường hoặc fade-to-black.",
            3: (
                "## [SPICE] Mức 3 — EXPLICIT 18+ (BẮT BUỘC)\n"
                "- Cảnh thân mật **đầy đủ**, mô tả cụ thể — văn phong ngôn tình mạng 18+.\n"
                "- Hai người trên 18, đồng thuận rõ. Giằng co quyền lực.\n"
                "- <<male_lead>> ít lời TRONG lúc; <<female_lead>> vẫn mỉa.\n"
                "- KHÔNG: trẻ vị thành niên, incest, non-con không redemption."
            ),
        },
    },
    "en": {
        "label": "English",
        "word_unit": "words",
        "target_words": "1600-1900",
        "prose_style_rule": "Modern commercial romance English — tight, vivid, not purple prose or archaic diction.",
        "language_only_rule": "ENGLISH ONLY — no Vietnamese diacritics, no CJK/Hangul characters.",
        "foreign_char_desc": "non-English letters (Vietnamese diacritics, CJK, Hangul, etc.)",
        "role_header": (
            "You are a professional paid-chapter romance writer (GoodNovel / Dreame / Vella style). "
            "{audience}. ONLY goal: make readers unlock the next chapter."
        ),
        "prior_heading": "STORY SO FAR",
        "prior_empty": "- (first chapter — no prior events)",
        "tech_heading": "TECHNICAL REQUIREMENTS",
        "task_heading": "YOUR TASK",
        "must_happen_label": "Must happen",
        "must_not_label": "Forbidden / must not contradict",
        "output_instruction": (
            "Output chapter prose only (title `# Chapter N: ...`). No meta, no checklist."
        ),
        "word_count_patch": "Target 1600-1900 <<language_label>> words — under 1250 = fail.",
        "spice": {
            1: "## [SPICE] Level 1 (sweet)\nEmotional tension, eye contact, almost-touch — no physical intimacy.",
            2: "## [SPICE] Level 2 (steamy)\nKissing, body tension, stop before explicit bed scene or fade-to-black.",
            3: (
                "## [SPICE] Level 3 — EXPLICIT 18+ (REQUIRED)\n"
                "- Full intimate scene, sensory detail — commercial romance 18+ voice.\n"
                "- Both 18+, clear consent. Power struggle in who leads.\n"
                "- <<male_lead>> stays terse IN scene; <<female_lead>> stays sharp.\n"
                "- NO: minors, incest, non-con without redemption."
            ),
        },
    },
}


def normalize_language(code: str | None) -> str:
    if not code:
        return "vi"
    base = str(code).strip().lower().replace("_", "-").split("-")[0]
    return base if base in LANGUAGE_PROFILES else "vi"


def target_language(direction: dict | None, cfg: dict | None = None) -> str:
    lang = (direction or {}).get("target_language")
    if not lang and cfg:
        lang = cfg.get("default_target_language", "vi")
    return normalize_language(lang)


def language_profile(lang: str | None = None, *, direction: dict | None = None, cfg: dict | None = None) -> dict:
    code = normalize_language(lang) if lang else target_language(direction, cfg)
    return LANGUAGE_PROFILES[code]


def find_foreign_chars(text: str, lang: str | None = None, *, direction: dict | None = None, cfg: dict | None = None) -> list[str]:
    """Ký tự lạ theo target_language — CJK cho vi; CJK + chữ Việt cho en (Latin extended OK)."""
    code = normalize_language(lang) if lang else target_language(direction, cfg)
    found: set[str] = set()
    if code == "vi":
        found.update(_CJK_RE.findall(text))
    elif code == "en":
        found.update(_CJK_RE.findall(text))
        for ch in _VN_LETTER_RE.findall(text):
            found.add(ch)
    return sorted(found)


def tech_rules_block(profile: dict, *, min_words: int = 1250) -> str:
    tw = profile["target_words"]
    wu = profile["word_unit"]
    return f"""## {profile.get("tech_heading", "TECHNICAL REQUIREMENTS")}
1. Hook in the first 3 sentences. NO scene-setting / weather openers.
2. Stay on bible; tension before escalation. Distinct dialogue voices.
3. <<female_lead>> internal monologue: sharp, sarcastic — never soft / weak.
4. **{tw} {wu} (minimum {min_words}). Under {min_words} = FAIL.** Short paragraphs 2-4 sentences.
5. {profile["prose_style_rule"]}
6. **Signature detail** — one specific, non-cliché detail (no ring/car/watch as main beat).
7. End on a cliffhanger that forces the next chapter.
8. **{profile["language_only_rule"]}**
9. **PLAIN TEXT ONLY — no markdown.** Do NOT use `*italics*`, `**bold**`, backticks, or `#` headings in body prose. Internal thoughts, journal lines, and sound effects are normal sentences — no asterisk emphasis."""


def tech_rules_block_vi(profile: dict, *, min_words: int = 1250) -> str:
    """Vietnamese section headers for vi profile."""
    if profile.get("tech_heading") != "YÊU CẦU KỸ THUẬT":
        return tech_rules_block(profile, min_words=min_words)
    tw, wu = profile["target_words"], profile["word_unit"]
    return f"""## YÊU CẦU KỸ THUẬT
1. Mở 3 câu đầu có móc câu. KHÔNG tả cảnh/thời tiết mở màn.
2. Đúng bible, tension trước — rồi leo thang. Đối thoại mỗi nhân vật một giọng.
3. Internal monologue <<female_lead>>: mỉa, sắc, không đổi thành bánh bèo.
4. **{tw} {wu} (tối thiểu {min_words}). KHÔNG dưới {min_words} = FAIL.** Đoạn ngắn 2-4 câu, nhiều xuống dòng.
5. {profile["prose_style_rule"]}
6. **Signature detail** 1 cái lạ-mà-thật (không nhẫn/xe/đồng hồ sáo).
7. Cliffhanger cuối chương — buộc lật chương sau.
8. **{profile["language_only_rule"]}**
9. **CHỈ VĂN BẢN THUẦN — không markdown.** KHÔNG dùng `*in nghiêng*`, `**đậm**`, backtick, hay `#` heading trong thân chương. Nội tâm, nhật ký, tiếng động viết như câu bình thường — không bọc dấu sao."""


def apply_lead_placeholders(text: str, bible: dict | None) -> str:
    from factory.engine.lib.bible_schema import lead_names

    fn, mn = lead_names(bible or {})
    fl = fn or ("nữ chính" if "chữ" in text else "female lead")
    ml = mn or ("nam chính" if "chữ" in text else "male lead")
    return text.replace("<<female_lead>>", fl).replace("<<male_lead>>", ml)


def build_tech_rules(profile: dict, *, min_words: int = 1250, bible: dict | None = None) -> str:
    if profile.get("word_unit") == "chữ":
        block = tech_rules_block_vi(profile, min_words=min_words)
    else:
        block = tech_rules_block(profile, min_words=min_words)
    return apply_lead_placeholders(block, bible)


def word_count_patch(profile: dict) -> str:
    return profile["word_count_patch"].replace("<<language_label>>", profile["label"])


ROLE_PLACEHOLDERS = (
    "<<language_label>>",
    "<<prose_style_rule>>",
    "<<language_only_rule>>",
    "<<word_unit>>",
    "<<target_words>>",
    "<<min_words>>",
    "<<foreign_char_desc>>",
)


def render_role_template(template: str, direction: dict | None, cfg: dict | None) -> str:
    prof = language_profile(direction=direction, cfg=cfg)
    min_w = int((cfg or {}).get("min_word_count", 1250))
    replacements = {
        "<<language_label>>": prof["label"],
        "<<prose_style_rule>>": prof["prose_style_rule"],
        "<<language_only_rule>>": prof["language_only_rule"],
        "<<word_unit>>": prof["word_unit"],
        "<<target_words>>": prof["target_words"],
        "<<min_words>>": str(min_w),
        "<<foreign_char_desc>>": prof["foreign_char_desc"],
    }
    out = template
    for key, val in replacements.items():
        out = out.replace(key, val)
    return out
