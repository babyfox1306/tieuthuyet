"""Past-tense pass for Meridian ch05 + soften early Nadia suspicion."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PATH = Path(
    "catalog/the-meridian-spine/books/01-the-meridian-spine/chapters/05-the-inside-vendor.md"
)

PAIRS = [
    (r"\bNadia Okafor says\b", "Nadia Okafor said"),
    (r"\bdoesn't look\b", "did not look"),
    (r"\bShe reads\b", "She read"),
    (r"\bShe slides\b", "She slid"),
    (r"\bNadia's fingers tap\b", "Nadia's fingers tapped"),
    (r"\bIris closes\b", "Iris closed"),
    (r"\bNadia steps\b", "Nadia stepped"),
    (r"\bIris pulls\b", "Iris pulled"),
    (r"\bNadia's expression shifts\b", "Nadia's expression shifted"),
    (r"\bIris turns\b", "Iris turned"),
    (r"\bNadia reads\b", "Nadia read"),
    (r"\bIris closes the laptop\b", "Iris closed the laptop"),
    (r"\bNadia straightens\b", "Nadia straightened"),
    (r"\bNadia says\b", "Nadia said"),
    (r"\bNadia takes\b", "Nadia took"),
    (r"\bIris stands\b", "Iris stood"),
    (r"\bNadia's face remains\b", "Nadia's face remained"),
    (r"\bIris picks\b", "Iris picked"),
    (r"\bShe walks past\b", "She walked past"),
    (r"\bThe door swings\b", "The door swung"),
    (r"\bThe procurement floor is\b", "The procurement floor was"),
    (r"\bIris takes the stairs\b", "Iris took the stairs"),
    (r"\bThe building hums\b", "The building hummed"),
    (r"\bAlan Torvik's cubicle is\b", "Alan Torvik's cubicle was"),
    (r"\bHis desk is\b", "His desk was"),
    (r"\bThe computer is\b", "The computer was"),
    (r"\bThe chair is\b", "The chair was"),
    (r"\bIris stands in the opening\b", "Iris stood in the opening"),
    (r"\bAn assistant approaches\b", "An assistant approached"),
    (r"\bThe assistant hesitates\b", "The assistant hesitated"),
    (r"\bIris sits\b", "Iris sat"),
    (r"\bShe pulls out\b", "She pulled out"),
    (r"\bShe memorizes\b", "She memorized"),
    (r"\bShe looks up\b", "She looked up"),
    (r"\bThe minutes pass\b", "The minutes passed"),
    (r"\bPeople glance\b", "People glanced"),
    (r"\bNo one stops\b", "No one stopped"),
    (r"\bHe is tall\b", "He was tall"),
    (r"\bHe sees Iris\b", "He saw Iris"),
    (r"\bHe nods\b", "He nodded"),
    (r"\bTorvik's face tightens\b", "Torvik's face tightened"),
    (r"\bHe takes the paper\b", "He took the paper"),
    (r"\bTorvik looks up\b", "Torvik looked up"),
    (r"\bHe hands\b", "He handed"),
    (r"\bTorvik's jaw hardens\b", "Torvik's jaw hardened"),
    (r"\bHe glances\b", "He glanced"),
    (r"\bHe crosses\b", "He crossed"),
    (r"\bIris holds\b", "Iris held"),
    (r"\bHe doesn't blink\b", "He did not blink"),
    (r"\bEither he is telling\b", "Either he was telling"),
    (r"\bhe has prepared\b", "he had prepared"),
    (r"\bTorvik steps\b", "Torvik stepped"),
    (r"\bHe does not ask\b", "He did not ask"),
    (r"\bwhy she is interested\b", "why she was interested"),
    (r"\bIris walks away\b", "Iris walked away"),
    (r"\bTorvik's answer is\b", "Torvik's answer was"),
    (r"\bIt is also\b", "It was also"),
    (r"\bHe is deflecting\b", "He was deflecting"),
    (r"\bshe has already burned\b", "she had already burned"),
    (r"\bif he is right\b", "if he was right"),
    (r"\bThey will prove\b", "They would prove"),
    (r"\bShe reaches\b", "She reached"),
    (r"\bthe corridor hums\b", "the corridor hummed"),
    (r"\bThe building is full\b", "The building was full"),
    (r"\bShe takes the stairs down\b", "She took the stairs down"),
    (r"\bThe basement level is\b", "The basement level was"),
    (r"\bThe air smells\b", "The air smelled"),
    (r"\bShe swipes\b", "She swiped"),
    (r"\bThe lock clicks\b", "The lock clicked"),
    (r"\bHer evidence box is\b", "Her evidence box was"),
    (r"\bShe pulls it down\b", "She pulled it down"),
    (r"\bThe tamper seal is\b", "The tamper seal was"),
    (r"\bShe cuts\b", "She cut"),
    (r"\bthe paper evidence is there\b", "the paper evidence was there"),
    (r"\bthe slide tray is missing\b", "the slide tray was missing"),
    (r"\bShe lifts\b", "She lifted"),
    (r"\bShe tilts\b", "She tilted"),
    (r"\bShe photographs\b", "She photographed"),
    (r"\bThen she closes\b", "Then she closed"),
    (r"\breturns it\b", "returned it"),
    (r"\bShe signs\b", "She signed"),
    (r"\bShe stares\b", "She stared"),
    (r"\bThe ink is\b", "The ink was"),
    (r"\bThe time stamp matches\b", "The time stamp matched"),
    (r"\bShe takes a picture\b", "She took a picture"),
    (r"\bIris slides the photo\b", "Iris slid the photo"),
    (r"\bwalks out\b", "walked out"),
    (r"\bThe corridor is empty\b", "The corridor was empty"),
    (r"\bThe lights flicker\b", "The lights flickered"),
    (r"\bShe has Alan\b", "She had Alan"),
    (r"\bShe has no slide\b", "She had no slide"),
    (r"\bShe has no confession\b", "She had no confession"),
    (r"\bwho already know she is blind\b", "who already knew she was blind"),
]

OLD_STEER = (
    "You've been steering me toward Halveston since before I found the coupon. "
    "You came to Petra's office without being asked. You pushed me to question "
    "Halveston, and now you're pushing me to drop the internal trace. Every time "
    "I get close to something inside this building, you redirect."
)
NEW_STEER = (
    "You keep pointing me at Halveston. You showed up at Petra's office. "
    "Now you want me to drop the internal trace. I will verify Torvik myself — "
    "and I will still check the fund."
)


def main() -> None:
    raw = PATH.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    for a, b in PAIRS:
        body = re.sub(a, b, body)
    body = body.replace(OLD_STEER, NEW_STEER)
    # leftover present after conversion of dialogue-adjacent lines
    body = body.replace("You've been steering me", "You keep pointing me")
    meta["word_count"] = len(re.findall(r"\S+", body))
    PATH.write_text(
        "---\n"
        + yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n"
        + body.lstrip("\n"),
        encoding="utf-8",
    )
    print("ch5 ok words", meta["word_count"])


if __name__ == "__main__":
    main()
