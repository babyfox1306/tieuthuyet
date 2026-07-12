
import json
from factory.engine.paths import workspace_dir, book_workspace_dir

ws = workspace_dir("improved-build-test")
bwd = book_workspace_dir(ws, 1)

master_plan = {
    "title": "The Lighthouse Keeper's Secret",
    "chapter_plans": [
        {
            "chapter": 1,
            "title": "Arrival at Blackrock Point",
            "one_line_summary": "Elinor arrives at the lighthouse she inherited from her grandmother.",
            "beat_summary": "Elinor drives to the coast, arrives at the old lighthouse, meets neighbor Martha who gives her the keys, and explores the empty, dusty house.",
            "opens_with": "Elinor pulls up to the lighthouse in her beat-up sedan, the salt wind whipping her hair.",
            "cliffhanger": "That night, she finds a locked trunk in the attic with her grandmother's initials on it.",
            "chapter_task": "Introduce Elinor and the setting; show her curiosity about her grandmother's past.",
            "must_happen": ["Elinor arrives at the lighthouse", "Meets Martha", "Finds the locked trunk"],
            "must_not": ["No mention of Thomas yet", "No explicit scenes"],
            "spice_note": "Sweet, no spice.",
            "carries_to_next": "The locked trunk in the attic."
        },
        {
            "chapter": 2,
            "title": "The First Key",
            "one_line_summary": "Elinor searches for the trunk key and finds an old journal instead.",
            "beat_summary": "Elinor searches the house for the trunk key; instead finds her grandmother's journal from 1957; meets Thomas when he comes to check the lighthouse foghorn.",
            "opens_with": "Morning light streams through the lighthouse windows as Elinor makes coffee.",
            "cliffhanger": "Thomas mentions his grandfather was a French sailor who disappeared in 1958.",
            "chapter_task": "Introduce Thomas; show initial connection between Elinor and Thomas; start the mystery.",
            "must_happen": ["Finds grandmother's journal", "Meets Thomas Hale", "Thomas mentions his grandfather"],
            "must_not": ["No romance yet, just tension"],
            "spice_note": "Sweet, no spice.",
            "carries_to_next": "Thomas's grandfather's connection to 1957."
        }
    ],
    "total_chapters": 12
}

mp_path = bwd / "master_plan.json"
mp_path.write_text(json.dumps(master_plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Created master_plan.json at {mp_path}")
