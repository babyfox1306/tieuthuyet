"""Seed the-ninth-bell concept + direction from locked operator concept."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "factory" / "workspaces" / "the-ninth-bell"


CONCEPT = {
    "concept_status": "ready",
    "target_language": "en",
    "title": "The Ninth Bell",
    "format": {
        "type": "standalone novella",
        "total_chapters": 10,
        "target_words_per_chapter": "1600-1900",
        "sequel_hook": "none",
    },
    "genre": {
        "primary": "gothic psychological horror",
        "secondary": ["acoustic mystery", "family conspiracy"],
        "romance": "none",
        "spice": 0,
    },
    "setting": {
        "location": "isolated English coastal village",
        "primary_location": "condemned medieval bell tower",
        "period": "late 1990s",
        "atmosphere": [
            "damp stone",
            "oxidized bronze",
            "magnetic tape",
            "salt air",
            "mechanical resonance",
            "psychological isolation",
        ],
    },
    "pov": {
        "character": "Clara Vale",
        "mode": "first_person",
        "tense": "past",
        "single_pov": True,
    },
    "logline": (
        "Forensic audio specialist Clara Vale inherits the condemned bell tower where "
        "her sister Elin died. Inside, she discovers recordings said to preserve the "
        "voices of the dead—including a recording in Clara's own voice confessing that "
        "she knowingly left Elin to die. To prove whether the confession is memory, "
        "prophecy, or fabrication, Clara must reconstruct the tower's hidden acoustic "
        "system and reopen a chamber her family sealed eighteen years earlier."
    ),
    "characters": [
        {
            "name": "Clara Vale",
            "age": 38,
            "role": "protagonist and sole POV",
            "occupation": "forensic audio specialist",
            "traits": [
                "analytical",
                "precise",
                "skeptical",
                "emotionally guarded",
                "distrusts her own memory",
            ],
            "wound": (
                "Clara believes her final argument with Elin may have caused Elin's death. "
                "Her fragmented memory and years of repeated questioning have turned guilt "
                "into something she trusts more than evidence."
            ),
            "arc": (
                "She moves from treating guilt as proof to treating evidence as proof, "
                "finally rejecting the false responsibility imposed on her."
            ),
        },
        {
            "name": "Gabriel Rook",
            "age": 61,
            "role": "tower caretaker and compromised witness",
            "traits": ["soft-spoken", "weary", "loyal", "evasive"],
            "secret": (
                "Gabriel helped Thomas Vale conceal the acoustic system and seal the "
                "chamber after Elin's death."
            ),
            "arc": "He moves from passive concealment to openly corroborating the truth.",
            "romance_with_clara": False,
        },
        {
            "name": "Thomas Vale",
            "role": "Clara and Elin's father; human antagonist",
            "status": "alive",
            "secret": (
                "Thomas created an illegal acoustic surveillance system connected to the "
                "tower bells. He fabricated Clara's apparent confession from fragments of "
                "her archived speech to force her back toward the sealed chamber."
            ),
            "final_outcome": [
                "publicly confesses",
                "surrenders the archive",
                "survives",
                "receives no forgiveness or absolution",
            ],
        },
        {
            "name": "Mara Venn",
            "role": "Clara's childhood friend",
            "secret": (
                "Mara knew Clara's memories after the accident were fragmented and that "
                "Thomas repeatedly shaped Clara's reconstruction of the event."
            ),
            "romance_with_clara": False,
        },
        {
            "name": "Elin Vale",
            "role": "Clara's deceased sister",
            "status": "deceased",
            "secret": (
                "Elin discovered Thomas's surveillance system and confronted him before "
                "the maintenance platform collapsed."
            ),
        },
    ],
    "surface_mystery": (
        "Villagers believe the tower's bells preserve the final words of the dead. "
        "Eight recordings appear connected to village deaths. The silent ninth bell "
        "produces a recording in Clara's voice saying: "
        '"I knew she would fall. I left her there anyway."'
    ),
    "true_plot": (
        "The bells are connected to a late-1990s acoustic surveillance system that "
        "captures and reconstructs conversations through vibration in bronze, stone, "
        "pipes, cables, and connected structures.\n\n"
        "Thomas Vale built the system for illegal surveillance. The supposed voices of "
        "the dead were manipulated recordings. The ninth-bell confession was assembled "
        "from fragments of Clara's real archived speech.\n\n"
        "Elin discovered the system and confronted Thomas. During the confrontation, "
        "the maintenance platform collapsed. Thomas was close enough to save her but "
        "froze instead of taking her hand. Clara did not knowingly leave Elin in "
        "immediate danger."
    ),
    "final_supernatural_residue": (
        "After the human mystery is fully explained and the archive has been surrendered "
        "as evidence, a visibly disconnected machine plays Elin's voice from a blank "
        'tape, saying: "You came back." This final event must remain unexplained.'
    ),
    "reveal_ladder": {
        "surface_event": {
            "chapter": 3,
            "exact_text": "I knew she would fall. I left her there anyway.",
            "meaning": (
                "Clara hears the apparent future confession in her own voice but does not "
                "yet know whether it is memory, prophecy, or fabrication."
            ),
        },
        "binding_reveal": {
            "chapter": 4,
            "exact_text": (
                "Thomas constructed Clara’s apparent confession from fragments of her "
                "recorded speech; Clara did not knowingly leave Elin in immediate danger."
            ),
            "rule": (
                "Chapter 4 may prove that the confession was assembled, but Thomas's full "
                "motive, Elin's death and the complete chamber truth remain unresolved."
            ),
        },
        "full_human_answer": {
            "chapter": 10,
            "meaning": (
                "Thomas built the system, fabricated the confession, allowed Clara to carry "
                "false guilt, and froze instead of saving Elin."
            ),
        },
    },
    "chapter_map": {
        1: {
            "title": "The Bell Before Arrival",
            "required_beats": [
                "Gabriel tells Clara the ninth bell rang before she crossed the causeway.",
                "Clara enters the condemned tower she has inherited.",
                "The village legend says the bells preserve the voices of the dead.",
                "Clara hears a damaged recording containing Elin's voice.",
                "Clara detects a faint metallic double pulse beneath the recording.",
            ],
            "must_not_reveal": [
                "origin of the recordings",
                "acoustic mechanism",
                "Thomas's involvement",
                "truth of Elin's fall",
            ],
            "ending": (
                "On the second playback, Elin's damaged voice clearly addresses Clara "
                "before the metallic double pulse cuts the recording dead."
            ),
        },
        2: {
            "title": "Eight Dead Voices",
            "required_beats": [
                "Clara examines eight archived recordings associated with village deaths.",
                "Her forensic confidence begins to return.",
                "She finds repeated editing artifacts.",
                "She detects the same unexplained resonance across the recordings.",
                "She concludes there may be physical manipulation but not how or by whom.",
            ],
            "ending": "Clara isolates an anomaly shared by all eight recordings and Elin's tape.",
        },
        3: {
            "title": "The Voice That Has Not Spoken Yet",
            "required_beats": [
                "Clara proves the metallic double pulse marks edit seams.",
                "The silent ninth bell produces Clara's apparent confession.",
                "The exact confession is heard in Clara's own voice.",
                "Clara considers suppressed memory, prediction and fabrication.",
                "No final explanation is permitted.",
            ],
            "ending": (
                "Clara identifies the first sign that the confession contains pieces from "
                "different recordings."
            ),
        },
        4: {
            "title": "The Confession in Pieces",
            "required_beats": [
                "Clara magnifies and analyzes the micro-splices.",
                "She matches stolen syllables to family recordings.",
                "She finds additional fragments taken from her professional interviews.",
                "She proves the confession was deliberately assembled.",
                "The maker and motive remain unknown.",
            ],
            "ending": (
                "The final word is traced to an interview recorded hundreds of miles from "
                "the tower, proving the maker reached beyond the family archive."
            ),
        },
        5: {
            "title": "The Memory They Gave Me",
            "required_beats": [
                "Mara reveals Clara's memory after Elin's death was fragmented.",
                "Thomas repeatedly questioned Clara and shaped her recollection.",
                "Clara recognizes that guilt may have been taught rather than remembered.",
                "The investigation remains evidence-based; no perfect recovered memory.",
            ],
            "ending": (
                "Clara realizes Thomas's version of the past contains language that first "
                "appeared only after he began questioning her."
            ),
        },
        6: {
            "title": "The Space Behind the Wall",
            "required_beats": [
                "Clara confronts inconsistencies in Thomas's account.",
                "Physical evidence indicates a concealed section of the tower.",
                "Clara finds infrastructure inconsistent with the public tower layout.",
                "She suspects a sealed room but does not yet know its full purpose.",
            ],
            "must_not_reveal": [
                "complete chamber contents",
                "full truth of Elin's death",
            ],
            "ending": "Clara proves that an apparently solid section of wall conceals an entrance.",
        },
        7: {
            "title": "What Gabriel Helped Hide",
            "required_beats": [
                "Gabriel admits helping conceal part of the acoustic system.",
                "Thomas's role in building the system becomes substantially established.",
                "Evidence shows someone inside the tower heard Elin's final confrontation.",
                "Gabriel still withholds the complete chamber truth.",
            ],
            "ending": (
                "The resonance pattern proves a witness was positioned where Thomas claimed "
                "no one had been standing."
            ),
        },
        8: {
            "title": "Behind the West Wall",
            "required_beats": [
                "Gabriel gives Clara the chamber key.",
                "Clara opens the concealed entrance.",
                "Clara enters the sealed chamber.",
                "She finds Elin's damaged tape.",
                "She finds editing equipment and the illegal archive.",
                "Physical details show the chamber has been accessed recently.",
            ],
            "ending": (
                "Clara discovers evidence that Thomas has recently entered the supposedly "
                "sealed chamber."
            ),
        },
        9: {
            "title": "The Hand She Was Waiting For",
            "required_beats": [
                "Clara reconstructs Elin's decisive recording.",
                "The recording proves Elin confronted Thomas about the surveillance system.",
                "Clara hears evidence that Thomas was close enough to save Elin.",
                "Thomas enters or attempts to access the chamber to remove or destroy evidence.",
                "Clara and Gabriel stop him before the decisive tape is lost.",
            ],
            "ending": "The inner lock turns while Thomas is on the other side with Elin's tape.",
        },
        10: {
            "title": "What the Ninth Bell Kept",
            "required_beats": [
                "Clara prevents Thomas from removing or destroying Elin's tape.",
                "Physical and acoustic evidence reconstructs Elin's final moments.",
                "Gabriel publicly admits his complicity.",
                "Thomas publicly confesses.",
                "Thomas surrenders the archive as evidence.",
                "Clara rejects the guilt imposed on her.",
                "Clara does not forgive or absolve Thomas.",
                "The human mystery is completely resolved.",
                "Afterward, the disconnected machine plays Elin's unexplained voice.",
            ],
            "final_line": "You came back.",
        },
    },
    "must_include": [
        "Nine bells, with the ninth believed to be silent.",
        'The exact confession: "I knew she would fall. I left her there anyway."',
        "Forensic audio analysis that materially advances the mystery.",
        "Physical evidence supporting every major conclusion.",
        "Metallic double pulse as an early recurring clue.",
        "Micro-splices made from Clara's archived speech.",
        "Concealed chamber behind the west wall.",
        "Elin's original damaged tape.",
        "Illegal acoustic surveillance equipment.",
        "Gabriel's complicity and eventual corroboration.",
        "Thomas's public confession and surrender of evidence.",
        "Clara rejects false guilt.",
        'Final unexplained recording: "You came back."',
    ],
    "must_avoid": [
        "Romance",
        "Sexual content",
        "Graphic gore",
        "Multiple POV",
        "Third-person narration",
        "Present-tense narration",
        "Clara murdering or pushing Elin",
        "Clara knowingly leaving Elin in immediate danger",
        "Gabriel as mastermind",
        "Mara causing Elin's death",
        "Elin secretly alive",
        "Thomas wanting Clara dead",
        "Thomas dying",
        "Clara forgiving Thomas",
        "Cults",
        "Demons",
        "Ghost villains",
        "Secret societies",
        "Government programs",
        "Additional murderers",
        "Artificial intelligence",
        "Futuristic or magical technology",
        "Confirmed afterlife",
        "Perfect recovered memory without evidence",
        "Dream revelations",
        "Hallucinations replacing evidence",
        "Villain monologue explaining everything",
        "New characters solving the mystery",
        "Changing the number of bells",
        "Changing the period or coastal English setting",
        "Fully explaining the final supernatural recording",
    ],
    "ending_book1": (
        "Thomas publicly confesses and surrenders the illegal archive. Clara accepts "
        "that her guilt was constructed and refuses to forgive or absolve him. Gabriel's "
        "complicity becomes public. The human mystery is closed. Later, with the machine "
        "visibly disconnected and the tape apparently blank, Clara hears Elin whisper: "
        '"You came back."'
    ),
    "hook_book2": "none",
    "operator_notes": (
        "Ch3 = confession appears; Ch4 = prove micro-splice; Ch8 = enter chamber and find tape; "
        "Ch9 = reconstruct + stop Thomas; Ch10 = public confession + supernatural coda."
    ),
}

DIRECTION = {
    "book": 1,
    "total_chapters": 10,
    "target_language": "en",
    "spice_max": 0,
    "spice_default": 0,
    "min_word_count": 1600,
    "max_word_count": 1900,
    "narrative_profile": "gothic_psychological_horror",
    "publish_strategy": "standalone",
    "intent_status": "draft",
    "plan_status": "draft",
    "bible_status": "draft",
    "narrative_status": "draft",
}

MANIFEST = {
    "workspace_id": "the-ninth-bell",
    "title": "The Ninth Bell",
    "created_from": "operator_concept_seed",
}


def main() -> None:
    WS.mkdir(parents=True, exist_ok=True)
    (WS / "bible" / "narrative").mkdir(parents=True, exist_ok=True)
    for bucket in ("draft", "needs_fix", "needs_review", "ready"):
        (WS / "books" / "01" / "pipeline" / bucket).mkdir(parents=True, exist_ok=True)

    (WS / "concept.yaml").write_text(
        yaml.dump(CONCEPT, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    (WS / "direction.yaml").write_text(
        yaml.dump(DIRECTION, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    (WS / "manifest.yaml").write_text(
        yaml.dump(MANIFEST, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print("seeded", WS)


if __name__ == "__main__":
    main()
