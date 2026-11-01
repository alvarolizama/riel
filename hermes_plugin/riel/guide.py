"""Riel's prose, served as a tool — the only door.

`guide/<topic>.md` ships inside the package (the tree IS the source — there is
no build step); each file opens with frontmatter carrying `topic`,
`trigger` and `version`. `entries()` gives the index, `read()` gives one
`## section` of it.

**Reading is sectioned by default.** A whole guide is 5–23 KB; the section a
task needs is usually 300–800 bytes. So `read(topic)` answers with the
*outline* — every `##` heading, its first line and its size, which is the
information the model needs to choose — and only `full=True` pays for the whole
body. Before this, `riel_guide(topic="delegate")` cost ~6k tokens on the first
call and the `section=` argument was undiscoverable, so nobody used it.

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
_DEFAULT_SUMMARY_CHARS = 120


def _frontmatter(path: Path) -> Dict[str, str]:
    """`key: value` pairs of the file's frontmatter, or `{}` — no YAML dependency."""
    text = _text(path)
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


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _body(path: Path) -> str:
    """The file without its frontmatter."""
    text = _text(path)
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

    An exact heading wins over a substring, and a heading that *starts* with the
    name beats one that merely contains it — so `section="DISPATCH"` opens
    `## DISPATCH — the operational rules…`, never `## Step 6: Write the dispatch
    prompt`. Every other case stays a case-insensitive substring, so
    `section="Claim anchors"` still finds `## Claim anchors (Spec 2 + Spec 7)`.
    """
    lines = text.splitlines()
    wanted = name.strip().lower()
    if not wanted:
        return None
    tiers = (
        lambda heading: heading == wanted,
        lambda heading: heading.startswith(wanted),
        lambda heading: wanted in heading,
    )
    headings_at = []
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            headings_at.append((index, match.group(1).strip().lower()))
    start = None
    for tier in tiers:
        start = next((index for index, heading in headings_at if tier(heading)), None)
        if start is not None:
            break
    if start is None:
        return None
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if _HEADING_RE.match(line):
            break
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _summary(lines: List[str], limit: int = _DEFAULT_SUMMARY_CHARS) -> str:
    """The first informative line of a section — prose, or a table's first row.

    Fences are skipped whole: a section that opens with a mermaid diagram is
    described by the sentence under it, never by `flowchart TD`. Markdown
    emphasis is stripped so the row reads as prose, not as source.
    """
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or stripped.startswith("#"):
            continue
        text = " ".join(stripped.split())
        if text.startswith("|"):
            cells = [cell.strip() for cell in text.strip("|").split("|") if cell.strip()]
            text = " · ".join(cells)
        text = text.replace("**", "").replace("__", "")
        text = text.lstrip("-*+> ").strip()
        if not text:
            continue
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return ""


def sections(text: str) -> List[Tuple[str, str, int]]:
    """`[(heading, first_line, body_bytes)]` — the outline's rows, in order."""
    out: List[Tuple[str, str, int]] = []
    current: Optional[str] = None
    buf: List[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if current is not None:
                out.append((current, _summary(buf), len("\n".join(buf))))
            current = match.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out.append((current, _summary(buf), len("\n".join(buf))))
    return out


def _size(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else f"{n}B"


def outline(topic: str, text: str) -> str:
    """The guide's sections — what to read next, without paying for the body."""
    rows = sections(text)
    meta: Dict[str, str] = {}
    for name, path, _trigger in entries():
        if name == topic:
            meta = _frontmatter(path)
            break
    version = meta.get("version") or ""
    head = f"# {topic} guide — {len(rows)} sections" + (f" (v{version})" if version else "")
    if not rows:
        return head + "\n\nThis guide has no `## sections` — read it whole with full=true.\n"
    lines = [
        head,
        "",
        f'Read one: riel_guide(topic="{topic}", section="<name>"). '
        "full=true reads the whole body — only when the task needs it.",
        "",
    ]
    for name, summary, size in rows:
        row = f"- {name} [{_size(size)}]"
        lines.append(f"{row} — {summary}" if summary else row)
    return "\n".join(lines) + "\n"


def read(topic: str, section: Optional[str] = None,
         full: bool = False) -> Tuple[Optional[str], Optional[dict]]:
    """The prose for *topic*: its outline, one *section*, or — with *full* — the body.

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
    if section:
        chunk = slice_section(text, section)
        if chunk is None:
            return None, {
                "error": f"no section matching {section!r} in the {clean} guide",
                "sections": headings(text),
                "hint": "pass one of the sections above, or full=true for the whole guide",
            }
        return chunk, None
    if full:
        return text, None
    return outline(clean, text), None