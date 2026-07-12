
from pathlib import Path
import yaml
from factory.engine.lib.workspace_init import init_blank_workspace
from factory.engine.paths import workspace_dir

print("Creating workspace 'improved-build-test'...")
ws = init_blank_workspace(
    "improved-build-test", 
    title="The Lighthouse Keeper's Secret", 
    target_language="en",
    total_chapters=12
)
print(f"Workspace created at: {ws}")

# Now let's write a valid concept.yaml using yaml.dump
concept = {
    "concept_status": "ready",
    "target_language": "en",
    "title": "The Lighthouse Keeper's Secret",
    "logline": "A young woman inherits a remote lighthouse and uncovers her grandmother's hidden journals — revealing a decades-old mystery about a lost ship and a forbidden romance.",
    "author_directive": "This is a sweet, atmospheric gothic romance (spice level 1). Focus on the moody coastal setting, the slow-burn tension between the protagonist and the local historian, and the gradual unravelling of the grandmother's secrets. Dialogue must keep quotation marks; no auto-invented male lead — the love interest is the local historian, Thomas Hale, who is curious, kind, and has his own connection to the lighthouse's history.",
    "surface_plot": "Elinor arrives at Blackrock Point Lighthouse to settle her grandmother's estate. She meets Thomas, who helps her go through old documents. Strange occurrences make her question if the lighthouse is haunted.",
    "true_plot": "Elinor's grandmother was hiding a secret: she helped a French sailor escape persecution in the 1950s, and they fell in love. Thomas is the sailor's grandson. The 'hauntings' are actually Thomas checking up on the lighthouse, and clues left by the grandmother to guide Elinor to the truth.",
    "must_include": ["Lighthouse setting", "old journals", "coastal storm", "hidden love letters", "family secrets", "slow-burn romance"],
    "must_avoid": ["Explicit content", "jump scares", "love triangles", "clichéd 'curse' plot"],
    "ending_book1": "Elinor and Thomas find the grandmother's final letter, which confirms their families' connection. They decide to restore the lighthouse together, and the story ends with them watching a storm roll in from the lantern room, knowing they're meant to be here.",
    "hook_book2": "While restoring the lighthouse, they find a hidden compartment with a map leading to treasure the sailor buried — but someone else is looking for it too.",
    "notes": "12 chapters total, spice level 1 (sweet, no explicit content). Focus on atmosphere, character chemistry, and gradual mystery reveals."
}
concept_path = ws / "concept.yaml"
concept_path.write_text(yaml.dump(concept, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
print(f"Concept written at: {concept_path}")

print("Done!")
