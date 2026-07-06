"""Discovery + retrieval over the lab's published DOCUMENTS — the other
half of the reference desk (published capsules being the first half).

Covers README.md, FAQ.md, and docs/*.md — including the generated
experiment catalog (docs/experiments.md, produced by
scripts/tools/gen_experiment_catalog.py: the lab's cataloguing feature).

Progressive disclosure, as everywhere: `list_lab_docs` returns names +
titles + sizes (small); `get_lab_doc` returns one document's text,
size-capped so a single call can't flood the context window.
"""
import os
from typing import List, Optional

from ...constants import ROOT_DIR

DOC_CHAR_CAP = 20_000  # per-fetch cap; caller is told when truncated


def _doc_paths() -> dict:
    """name -> absolute path for every published markdown document."""
    out = {}
    for top in ("README.md", "FAQ.md"):
        p = os.path.join(ROOT_DIR, top)
        if os.path.isfile(p):
            out[top] = p
    docs_dir = os.path.join(ROOT_DIR, "docs")
    if os.path.isdir(docs_dir):
        for fn in sorted(os.listdir(docs_dir)):
            if fn.endswith(".md"):
                out[f"docs/{fn}"] = os.path.join(docs_dir, fn)
    return out


def _title_of(path: str) -> str:
    """First `# ` heading, else the filename."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
                if line.strip() and not line.startswith("#"):
                    break
    except OSError:
        pass
    return os.path.basename(path)


def list_lab_docs() -> List[dict]:
    """Names + titles + sizes of every published document. Small payload."""
    out = []
    for name, path in _doc_paths().items():
        out.append({
            "name": name,
            "title": _title_of(path),
            "bytes": os.path.getsize(path),
        })
    return out


def get_lab_doc(name: str) -> Optional[dict]:
    """One document's text, capped at DOC_CHAR_CAP chars (truncation is
    stated, never silent). None if the name isn't in the published set —
    names come from list_lab_docs, no path traversal surface."""
    path = _doc_paths().get(name)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    truncated = len(text) > DOC_CHAR_CAP
    return {
        "name": name,
        "content": text[:DOC_CHAR_CAP],
        "truncated": truncated,
        "total_chars": len(text),
    }
