"""Riel's prose, served as a tool — the only door.

`guide/<topic>.md` ships inside the package (built from the repo's `guide/` by
`make plugin-build`); each file opens with frontmatter carrying `topic`,
`trigger` and `version`. `entries()` gives the index, `read()` gives one body or
one `## section` of it.

Nothing here is a Hermes skill: the prose reaches the model through the
`riel_guide` tool and through the `riel` prompt section, and both read these
same files — one source of truth, no copy to drift.

Stdlib only, and importable outside Hermes: the repo suite exercises this
module directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GUIDE_DIR = Path(__file__).resolve().parent / "guide"

_TOPIC_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_HEADING_RE = re.compile(r"^##\s+(.*)$")


def _frontmatter(path: Path) -> Dict[str, str]:
    """`key: value` pairs of the file's frontmatter, or `{}` — no YAML dependency."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: Dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if key.strip() and value:
            fields[key.strip()] = value.strip('"').strip("'")
    return fields


def _body(path: Path) -> str:
    """The file without its frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4 :].lstrip("\n") if end != -1 else text


def entries() -> List[Tuple[str, Path, str]]:
    """`[(topic, path, trigger)]`, ordered by topic — the index's rows."""
    rows: List[Tuple[str, Path, str]] = []
    if not GUIDE_DIR.is_dir():
        return rows
    for path in sorted(GUIDE_DIR.glob("*.md")):
        fields = _frontmatter(path)
        rows.append((fields.get("topic") or path.stem, path, fields.get("trigger", "")))
    return rows


def topics() -> List[str]:
    return [topic for topic, _path, _trigger in entries()]


def index_text() -> str:
    """The index as the model reads it: one line per topic, trigger included."""
    return "\n".join(f"- {topic} — {trigger}" for topic, _path, trigger in entries())


def headings(text: str) -> List[str]:
    return [match.group(1).strip() for match in (_HEADING_RE.match(line) for line in text.splitlines()) if match]


def slice_section(text: str, name: str) -> Optional[str]:
    """`## <name>` through the line before the next `## ` — `None` when absent.

    The match is a case-insensitive substring, so `section="Claim anchors"`
    finds `## Claim anchors (Spec 2 + Spec 7)`.
    """
    lines = text.splitlines()
    wanted = name.strip().lower()
    start = None
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and wanted in match.group(1).lower():
            start = index
            break
    if start is None:
        return None
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if _HEADING_RE.match(line):
            break
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def read(topic: str, section: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
    """The prose for *topic* (or its *section*): `(text, None)`, or `(None, error)`.

    The errors are structured and carry the way back: the known topics when the
    topic is unknown, the section names when the section is.
    """
    clean = (topic or "").strip().lower()
    if not _TOPIC_RE.match(clean):
        return None, {
            "error": f"invalid topic: {topic!r}",
            "topics": topics(),
            "hint": "topics are slugs like 'contract'; call riel_guide() with no arguments",
        }
    path = GUIDE_DIR / f"{clean}.md"
    if not path.is_file():
        return None, {
            "error": f"unknown topic: {clean}",
            "topics": topics(),
            "hint": "call riel_guide() with no arguments for the index",
        }
    text = _body(path)
    if not section:
        return text, None
    chunk = slice_section(text, section)
    if chunk is None:
        return None, {
            "error": f"no section matching {section!r} in the {clean} guide",
            "sections": headings(text),
            "hint": "pass one of the sections above, or drop 'section' for the whole guide",
        }
    return chunk, None
