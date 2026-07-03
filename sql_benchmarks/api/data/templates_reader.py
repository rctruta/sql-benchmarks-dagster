"""Discovery layer for curated experiment templates.

The agent doesn't know what dataset shape each SQL suite expects. `list_suites`
gives it the SQL, but reverse-engineering a valid dataset from that SQL is
what humans have always used docstrings and examples for. This module exposes
the curated example configs (`experiments/templates/` + `experiments/queue/`)
as browsable templates so the agent can `get_template(name)` and adapt rather
than construct from scratch.

Curation filter: files whose stem looks like an 8-char experiment_id
(`^[0-9a-f]{8}$`) are runtime queue entries produced by the coordinator,
NOT human-curated examples. They're excluded.
"""
import os
import re
from typing import List, Optional

import yaml

from ...constants import EXPERIMENTS_DIR
from ..models.catalog import TemplateSummary


# Directories scanned. Order matters only for tie-breaking (first hit wins if
# two files have identical stems — currently no collision, and the filter
# below limits us to human-named files anyway).
_TEMPLATE_DIRS = ["templates", "queue"]

# Runtime queue entries look like `<8-hex>.yaml`. Not curated content.
_RUNTIME_ID_RE = re.compile(r"^[0-9a-f]{8}$")


def _is_curated(stem: str) -> bool:
    return not _RUNTIME_ID_RE.match(stem)


class TemplatesReader:
    """Stateless — walks the filesystem on every call so a new file added to
    templates/ or queue/ is visible immediately without restarting the API."""

    def _files(self) -> List[str]:
        paths: List[str] = []
        for sub in _TEMPLATE_DIRS:
            d = os.path.join(EXPERIMENTS_DIR, sub)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".yaml"):
                    continue
                stem = fn[:-5]
                if not _is_curated(stem):
                    continue
                paths.append(os.path.join(d, fn))
        return paths

    def list_templates(self) -> List[TemplateSummary]:
        out: List[TemplateSummary] = []
        for path in self._files():
            stem = os.path.splitext(os.path.basename(path))[0]
            desc = _describe(path)
            out.append(TemplateSummary(name=stem, description=desc, path=_relpath(path)))
        return out

    def get_template(self, name: str) -> Optional[str]:
        """Return the raw YAML text of the named template. None if not found.
        The agent adapts this text and submits it back via `submit_experiment`."""
        for path in self._files():
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem == name:
                try:
                    with open(path, "r") as f:
                        return f.read()
                except OSError:
                    return None
        return None


def _relpath(path: str) -> str:
    """Path relative to EXPERIMENTS_DIR — stable identifier a reader can find."""
    return os.path.relpath(path, EXPERIMENTS_DIR)


def _describe(path: str) -> str:
    """Best-effort one-line description. Priority:
       meta.description → meta.name → first non-blank comment line → filename."""
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        return os.path.basename(path)

    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        data = {}

    meta = data.get("meta") or {}
    if isinstance(meta, dict):
        if meta.get("description"):
            return _first_line(str(meta["description"]))
        if meta.get("name"):
            return _first_line(str(meta["name"]))

    # Fall back to the first non-blank comment line at the top of the file.
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") and len(s) > 1:
            return s.lstrip("#").strip()
        if s and not s.startswith("#"):
            break

    return os.path.basename(path)


def _first_line(s: str, max_chars: int = 200) -> str:
    line = s.splitlines()[0].strip() if s else ""
    return line[:max_chars]
