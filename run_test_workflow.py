
from pathlib import Path
import json
import yaml
from factory.engine.paths import workspace_dir, bible_path
from factory.engine.lib.concept_cli import concept_mark_ready
from factory.engine.lib.narrative_developer import develop_narrative
from factory.engine.lib.master_plan import plan_book
from factory.engine.lib.canon_registry import scaffold_canon_registry
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.lib.bible_schema import validate_bible, bible_is_approved


def save_direction(ws: Path, direction: dict):
    """Save direction dict to ws/direction.yaml."""
    dp = ws / "direction.yaml"
    dp.write_text(
        yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def create_and_approve_bible(ws: Path):
    """Create a simple valid series bible and approve it."""
    bible = {
        "meta": {
            "series_id": "improved-build-test",
            "genre": "gothic romance",
            "target_language": "en"
        },
        "leads": {
            "female": {
                "name": "Elinor Hale",
                "age": 26,
                "voice": "Thoughtful, quiet, curious, with a dry sense of humor.",
                "tics": ["Twists a strand of hair when thinking", "Traces the edges of old books", "Bites her lower lip when nervous"],
                "boundary": "Hates being lied to; will withdraw if someone is dishonest."
            },
            "male": {
                "name": "Thomas Hale",
                "age": 30,
                "voice": "Warm, steady, gentle, with a hint of melancholy.",
                "tics": ["Runs a hand through his dark hair", "Adjusts his glasses when focused", "Stares out the window when thinking"],
                "boundary": "Will not talk about his family's past without trust."
            }
        },
        "supporting_cast": [
            {
                "name": "Martha Higgins",
                "relation_to": "Elinor Hale",
                "relation_type": "neighbor",
                "alive": True,
                "secret": "She knows more about Elinor's grandmother than she admits."
            },
            {
                "name": "Old Lighthouse Keeper",
                "relation_to": "Elinor Hale",
                "relation_type": "distant relative",
                "alive": False
            }
        ],
        "central_mystery": {
            "question": "What happened to the French sailor Elinor's grandmother helped?",
            "answer": "He was her secret love; he died in a storm, but they had a child together — Thomas's grandfather.",
            "reveal_chapter": 10
        },
        "bloodline": {
            "description": "Elinor and Thomas share a distant connection through the lighthouse keeper's family, but no direct blood relation.",
            "hard_rules": [
                "No time travel",
                "The lighthouse is always a central setting",
                "The mystery must be resolved through old letters and journals"
            ],
            "lead_relation": "distant relative"
        },
        "world_rules": [
            "The lighthouse fog whispers secrets only those with Hale blood can hear",
            "Old letters in the attic glow faintly when touched by a Hale",
            "The lighthouse keeper's journal can only be read by candlelight"
        ]
    }
    bp = bible_path(ws)
    bp.write_text(json.dumps(bible, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Created series bible at {bp}")
    errors = validate_bible(bible)
    print(f"Validate bible errors: {errors}")
    if not errors:
        direction = load_direction(ws)
        direction["bible_status"] = "approved"
        direction["narrative_status"] = "approved"
        save_direction(ws, direction)
        print("Approved bible and narrative in direction.yaml")


def main():
    ws = workspace_dir("improved-build-test")
    print(f"Using workspace: {ws}")

    print("\n=== Step 1: Mark concept as ready ===")
    ok, issues = concept_mark_ready(ws)
    print(f"Concept ready? {ok}")
    if issues:
        print(f"Issues: {issues}")

    print("\n=== Step 2: Scaffold canon registry ===")
    result = scaffold_canon_registry(ws)
    print(result)

    print("\n=== Step 3: Create and approve series bible ===")
    create_and_approve_bible(ws)

    print("\n=== Step 4: Develop narrative ===")
    try:
        result = develop_narrative("improved-build-test", pass_name="all")
        print("Develop narrative succeeded!")
        print(f"Created {len(result)} files:")
        for p in result:
            print(f"  {p}")
    except Exception as e:
        print(f"Develop narrative failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n=== Step 5: Plan book ===")
    try:
        plan_path, num_chapters = plan_book(ws, 1)
        print(f"Plan saved to {plan_path}, generated {num_chapters} chapters!")
    except Exception as e:
        print(f"Plan failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
