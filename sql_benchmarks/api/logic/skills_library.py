"""Progressive disclosure over the lab's Agent Skills (agentskills.io).

The spec loads skills in three stages; this module implements the first
two for any consumer (monolith prompt, tool dispatch, REST, humans):

  1. Discovery  — `list_skills()`: ONLY the frontmatter `name` and
                  `description` of each skill. Tens of tokens per skill.
  2. Activation — `get_skill(name)`: the full SKILL.md instruction body,
                  fetched when a task matches the description.

Why this exists (and why the loader can't just concatenate bodies):
the original loader inlined full skill bodies into the system prompt
every run — always-loaded prose, re-read every turn. That both violates
the spec's design and confounded the guidance-ablation studies: the
"+skills" condition measured the bloat of a non-compliant loader, not
the cost of spec-compliant skills. Ramona caught it 2026-07-14; PR #160
fixed the FILE format (folders + frontmatter); this module fixes the
LOADING behavior.

Skills live at `skills/<skill-name>/SKILL.md` with YAML frontmatter
(`name`, `description` at minimum), per the spec.
"""
import os
from typing import List, Optional

import yaml

from ...constants import ROOT_DIR

SKILLS_DIR = os.path.join(ROOT_DIR, "skills")


def _parse_frontmatter(text: str) -> dict:
    """YAML frontmatter between leading '---' fences. {} if absent/broken —
    a skill without metadata is invisible to discovery (spec requires it)."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _skill_paths() -> dict:
    """name -> SKILL.md path, name taken from the frontmatter (falling back
    to the directory name so a metadata typo is findable, not invisible)."""
    out = {}
    if not os.path.isdir(SKILLS_DIR):
        return out
    for item in sorted(os.listdir(SKILLS_DIR)):
        path = os.path.join(SKILLS_DIR, item, "SKILL.md")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            fm = _parse_frontmatter(f.read())
        out[str(fm.get("name") or item)] = path
    return out


def list_skills() -> List[dict]:
    """Discovery stage: name + description per skill. Small by design —
    this is ALL that belongs in a system prompt."""
    out = []
    for name, path in _skill_paths().items():
        with open(path, encoding="utf-8") as f:
            fm = _parse_frontmatter(f.read())
        out.append({
            "name": name,
            "description": str(fm.get("description") or "").strip(),
        })
    return out


def get_skill(name: str) -> Optional[dict]:
    """Activation stage: the full instruction body (frontmatter stripped —
    the caller already has the metadata). None for unknown names; names
    come from list_skills, so there is no path-traversal surface."""
    path = _skill_paths().get(name)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")
    return {"name": name, "instructions": body}
