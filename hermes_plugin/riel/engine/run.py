"""The Riel v2 engine — one stdlib file behind the public verbs.

Public surface (nothing else exists; there is NO converter from riel v1):

    riel [--worktree DIR] shape [PATH] | shape new [--param k=v]
    riel [--worktree DIR] shape fetch URL -o F --sha256 H
    riel [--worktree DIR] run new [--param k=v] [--strict]
    riel [--worktree DIR] run validate [FILE]
    riel [--worktree DIR] run activate
    riel [--worktree DIR] run rebase
    riel [--worktree DIR] run status
    riel [--worktree DIR] run slice PHASE
    riel [--worktree DIR] run fetch URL -o F --sha256 H [--timeout S] [--max-bytes N]
    riel [--worktree DIR] note [--gate G# ...] [--claim P# ...] --command CMD
                        --covering WHAT [--confidence N]
                        [--core "name -- fact"] [--core-slot N]
                        [--open Q --settled-by TEST] [--close N --evidence N]
    riel [--worktree DIR] todo
    riel [--worktree DIR] clean [--all] [--purge]
    riel [--worktree DIR] check FILE [--mermaid]

State is ONE file, `.riel/run.md`, format `riel-run/v1`, plus a separate
frozen `.riel/shaping.md`. The plan (the title plus eight sections, ending at
`## DO NOT`) is authored by hand — `run new` only renders the template to
stdout; an editor or write_file is the editing path. `run activate` freezes
it: it computes plan_sha256 over the plan-before-Metadata (including the
frozen Basis copied from the referenced shaping findings) and shaping_sha256
over the shaping bytes, then appends Metadata + Execution state + Core + Open
+ Evidence. `note` is the ONLY writer of that state. If the plan or the
shaping changes underneath, note refuses as stale until `run rebase` reserves
the old evidence (retained, not counted) under a new revision.

Every output goes to explicit sinks: `run_verb(argv, worktree, out, err)`
never touches process-global stdout/stderr, and every error is clean text —
never a traceback.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

VERSION = "2.0.0"
RUN_FORMAT = "riel-run/v1"

RIEL_DIR = ".riel"
RUN_MD = "run.md"
SHAPING_MD = "shaping.md"
LOCK_NAME = ".run.lock"
LEGACY_STATE_FILES = ("contract.md", "ledger.md")
MARKER_LINE = "<!-- {} -->".format(RUN_FORMAT)

# The plan: the level-1 title plus these eight level-2 sections, in order.
# Activation appends five more (Metadata, Execution state, Core, Open,
# Evidence).
PLAN_TITLES = (
    "Objective", "Context", "Constraints", "Claims", "Graph",
    "Gates", "Deliverable", "DO NOT",
)
CLOSED_VERBS = ("READ", "EDIT", "CREATE", "RUN", "VERIFY", "ASK")
DENSE_RE = re.compile(r"[✓?]\d+|↔|⇒|⊕|λ|Σ")
VERIFY_CMD = os.environ.get("RIEL_MMDC", "mmdc")
MMDC_TIMEOUT = float(os.environ.get("RIEL_MMDC_TIMEOUT", "20"))
NOTE_TIMEOUT = float(os.environ.get("RIEL_NOTE_TIMEOUT", "120"))
NOTE_SNIPPET_CHARS = 240
MAX_BACKUPS = 3
CONFIDENCE_PASS = 12


class EngineError(Exception):
    """A clean, user-facing failure. `.code` is the process exit code."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------- markdown ----

def _strip_comments(text):
    """Remove `<!-- ... -->` blocks (multi-line included)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _section(text, name):
    """Body of '## <name>' up to the next '## ' heading (or EOF)."""
    m = re.search(
        r"^##\s+" + re.escape(name) + r"[^\n]*\n(.*?)(?=^##\s|\Z)",
        text, re.S | re.M,
    )
    return m.group(1).strip() if m else ""


def _subsection(text, section, sub):
    """Body of '### <sub>' inside '## <section>'."""
    body = _section(text, section)
    m = re.search(
        r"^###\s+" + re.escape(sub) + r"[^\n]*\n(.*?)(?=^###\s|^##\s|\Z)",
        body, re.S | re.M,
    )
    return m.group(1).strip() if m else ""


def _bullets(body):
    """List items of a body, in order; `-`, `*` and `1.` all count.

    HTML comments are stripped first so a commented-out example never
    becomes data (the audit fix for Findings and bullets).
    """
    items = []
    for raw in _strip_comments(body).splitlines():
        line = raw.strip()
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", line)
        if m:
            items.append(m.group(1).strip())
    return items


def _first_line(text):
    """First non-empty, non-comment line of a section body."""
    for raw in _strip_comments(text).splitlines():
        line = raw.strip()
        if line:
            return line
    return ""


def _clauses(text):
    """Split 'a — b: c — d' on em-dashes into clause strings."""
    return [c.strip() for c in re.split(r"\s+—\s+", text) if c.strip()]


def context_keywords(text):
    """[{term, source}] from '### Context keywords' under '## Context'."""
    found = []
    for item in _bullets(_subsection(text, "Context", "Context keywords")):
        term, _, source = item.partition("→")
        term = term.strip().strip("`").strip()
        if term and not term.startswith("{{"):
            found.append({"term": term,
                          "source": source.strip().strip("`").strip()})
    return found


# --------------------------------------------------------------- graph ----
# The plan's graph lives ONLY in `## Graph` (the audit fix: no fallback to
# the first mermaid block anywhere in a run file). Two registers parse into
# the same shape: nodes {id: (opener, label)}, edges [(src, label, dst)].

NODE_ANCHOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PHASE_ID_RE = re.compile(r"^[FW]\d+$")
GATE_REF_RE = re.compile(r"^G\d+$")


def mermaid_graph(block):
    """Parse a mermaid flowchart block → (nodes, edges); quote-aware."""
    nodes, i, n = {}, 0, len(block)
    opener = {"[": "]", "(": ")", "{": "}"}
    while i < n:
        ch = block[i]
        if ch == '"':
            nxt = block.find('"', i + 1)
            i = n if nxt == -1 else nxt + 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (block[j].isalnum() or block[j] == "_"):
                j += 1
            ident = block[i:j]
            k = j
            while k < n and block[k] == " ":
                k += 1
            if k < n and block[k] in opener:
                closer = opener[block[k]]
                buf, m = [], k + 1
                while m < n:
                    c2 = block[m]
                    if c2 == '"':
                        end = block.find('"', m + 1)
                        if end == -1:
                            m = n
                            break
                        buf.append(block[m + 1:end])
                        m = end + 1
                        continue
                    if c2 == closer:
                        break
                    buf.append(c2)
                    m += 1
                label = "".join(buf).strip()
                nodes.setdefault(ident, (block[k], label))
                i = m + 1
                continue
            i = j
            continue
        i += 1
    edges = []
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith(("flowchart", "graph", "%%", "style ",
                                  "classDef", "class ", "subgraph", "end")):
            continue
        for m in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\]|\{[^}]*\}|\([^)]*\))?"
            r"\s*--+>?\s*(?:\|([^|]*)\|\s*)?([A-Za-z_][A-Za-z0-9_]*)",
            s,
        ):
            lbl = (m.group(2) or "").strip().strip('"').strip()
            edges.append((m.group(1), lbl, m.group(3)))
    return nodes, edges


_LIST_ITEM_RE = re.compile(r"^(?:[-*]|\d+\.)\s+(.+)$")


def list_graph(body):
    """Parse the plain phase-list register → (nodes, edges).

        - F1: phase label
          - READ what for
          - RUN make test
        - F2: next phase

    A phase carries exactly ONE outgoing edge — to its FIRST step (the audit
    fix: the old parser fanned the phase out to every step). Steps chain
    linearly; the last step of a phase edges to the next phase. `-`, `*`
    and `1.` are all accepted as bullets; comments are stripped first.
    """
    nodes, edges = {}, []
    current = None
    last_step = None
    step_no = 0
    for raw in _strip_comments(body).splitlines():
        stripped = raw.strip()
        item = _LIST_ITEM_RE.match(stripped)
        if not item:
            continue
        if not raw.startswith((" ", "\t")):
            m = re.match(r"^(F\d+|W\d+)\s*[:：]\s*(.+)$", item.group(1))
            if not m:
                continue
            current = m.group(1)
            nodes[current] = ("[", m.group(2).strip())
            last_step = None
            continue
        if current is None:
            continue
        step_no += 1
        sid = "S{}".format(step_no)
        nodes[sid] = ("[", item.group(1).strip())
        if last_step is None:
            edges.append((current, "", sid))     # phase → its first step
        else:
            edges.append((last_step, "", sid))   # ...or the step chain
        last_step = sid
    phase_ids = [nid for nid in nodes if PHASE_ID_RE.match(nid)]
    for a, b in zip(phase_ids, phase_ids[1:]):
        outs = [v for u, _l, v in edges if u == a]
        edges.append(((outs[-1] if outs else a), "", b))
    return nodes, edges


def graph_any(text, strict_section=False):
    """The file's graph → (nodes, edges, register); ({}, [], '') when absent.

    strict_section (run files): ONLY `## Graph` counts. Otherwise (external
    files under `check`) a first-mermaid fallback keeps riel_check's reach.
    """
    body = _section(text, "Graph")
    block = _first_mermaid(body)
    if block is not None:
        nodes, edges = mermaid_graph(block)
        if nodes:
            return nodes, edges, "mermaid"
    if not strict_section:
        block = _first_mermaid(text)
        if block is not None:
            nodes, edges = mermaid_graph(block)
            if nodes:
                return nodes, edges, "mermaid"
    nodes, edges = list_graph(body)
    if nodes:
        return nodes, edges, "list"
    return {}, [], ""


def _first_mermaid(text):
    i = text.find("```mermaid")
    if i == -1:
        return None
    i += len("```mermaid")
    j = text.find("```", i)
    return text[i:j].strip() if j != -1 else None


def graph_back_edges(edges):
    """Edges closing a cycle — ITERATIVE, so deep graphs never RecursionError."""
    adj = {}
    for u, _l, v in edges:
        adj.setdefault(u, []).append(v)
    color, backs = {}, []
    for root in sorted({u for u, _l, _v in edges} | {v for _u, _l, v in edges}):
        if color.get(root):
            continue
        color[root] = 1
        stack = [(root, iter(adj.get(root, ())))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                c = color.get(nxt, 0)
                if c == 1:
                    backs.append((node, "", nxt))
                elif c == 0:
                    color[nxt] = 1
                    stack.append((nxt, iter(adj.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = 2
                stack.pop()
    return list(dict.fromkeys(backs))


def _phase_subgraph(nodes, edges, start):
    """Node ids reachable from `start` without entering another phase."""
    phase_ids = {nid for nid in nodes if PHASE_ID_RE.match(nid)}
    adj = {}
    for u, _l, v in edges:
        adj.setdefault(u, []).append(v)
    keep, stack = set(), [start]
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        for v in adj.get(nid, ()):
            if v in phase_ids and v != start:
                continue
            if v not in keep:
                stack.append(v)
    return keep


def _phase_order(nodes):
    """Phase ids in authored order."""
    return [nid for nid in nodes if PHASE_ID_RE.match(nid)]


def _phase_steps(nodes, edges, phase_id):
    """Work-step ids of a phase, authored order (not phases/gates/milestones)."""
    sub = _phase_subgraph(nodes, edges, phase_id)
    steps = []
    for member in nodes:
        if member not in sub or member == phase_id:
            continue
        if PHASE_ID_RE.match(member) or GATE_REF_RE.match(member):
            continue
        if member.upper() in ("START", "END", "DONE"):
            continue
        if (nodes.get(member, ("", ""))[1] or "").strip():
            steps.append(member)
    return steps


def mmdc_issues(blocks, timeout=None):
    """Parse each block with mmdc; [] when clean or mmdc is absent."""
    if not blocks or not shutil.which(VERIFY_CMD):
        return []
    cap = MMDC_TIMEOUT if timeout is None else timeout
    issues = []
    out_dir = tempfile.mkdtemp(prefix="riel-mmdc-")
    try:
        for idx, block in enumerate(blocks):
            src = os.path.join(out_dir, "block{}.mmd".format(idx))
            out = os.path.join(out_dir, "block{}.svg".format(idx))
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(block)
            try:
                res = subprocess.run(
                    [VERIFY_CMD, "-i", src, "-o", out, "--quiet"],
                    capture_output=True, timeout=cap)
            except subprocess.TimeoutExpired:
                issues.append(
                    "mermaid block {} timed out after {}s".format(idx, cap))
                continue
            if res.returncode != 0:
                issues.append("mermaid block {} fails mmdc: {}".format(
                    idx, res.stderr.decode("utf-8", "replace")[:200]))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return issues


# ------------------------------------------------------ run.md parsing ----

EVIDENCE_RE = re.compile(
    r"^E(?P<n>\d+)\s+gate:(?P<gate>G\d+(?:,G\d+)*)\s+claims:(?P<claims>[\w,]*)\s+"
    r"revision:(?P<rev>\S+)\s+command_b64:(?P<cmd>[A-Za-z0-9+/=]+)\s+exit_code:(?P<exit>\d+)\s+"
    r"covering:(?P<covering>.*?)(?:\s+confidence:(?P<conf>\d+))?\s*$"
)
FROZEN_RE = re.compile(r"^shaping:F(\d+)$", re.I)
SECTION_ANCHOR_RE = re.compile(r"^§\s*([^#]+?)\s*(?:#(\d+))?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _split_plan(text):
    """(plan_text, state_text): the plan is everything before `## Metadata`.

    The plan is CANONICALIZED here (exactly one trailing newline) because the
    hash is computed over these bytes: the blank line the renderer adds before
    `## Metadata` must never count as a plan change.
    """
    m = re.search(r"^## Metadata\s*$", text, re.M)
    if m is None:
        return text.rstrip("\n") + "\n", ""
    return text[:m.start()].rstrip("\n") + "\n", text[m.start():]


def plan_sha256(plan_text):
    return hashlib.sha256(plan_text.encode("utf-8")).hexdigest()


def marker_present(text):
    """The format marker must be its own line before the first `## ` heading."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            return False
        if s == MARKER_LINE:
            return True
    return False


def _parse_metadata(text):
    meta = {}
    for item in _bullets(_section(text, "Metadata")):
        key, sep, value = item.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta


def _parse_claims(text):
    """[{id, text, anchor}] from `## Claims` (anchor = last em-dash clause)."""
    out = []
    for item in _bullets(_section(text, "Claims")):
        clauses = _clauses(item)
        anchor, prose = "", []
        for i, clause in enumerate(clauses):
            if clause.lower().startswith("anchor:") and i == len(clauses) - 1:
                anchor = clause[len("anchor:"):].strip().strip("`")
            else:
                prose.append(clause)
        m = re.match(r"^(P\d+)\s*[:：]\s*(.*)$", " — ".join(prose))
        if m:
            out.append({"id": m.group(1), "text": m.group(2).strip(),
                        "anchor": anchor})
    return out


def _parse_gates(text):
    """[{id, label, phase}] from `## Gates` (`— phase: F#` optional)."""
    out = []
    for item in _bullets(_section(text, "Gates")):
        clauses = _clauses(item)
        phase, prose = "", []
        for i, clause in enumerate(clauses):
            m = re.match(r"^phase:\s*(\S+)$", clause)
            if m and i == len(clauses) - 1:
                phase = m.group(1)
            else:
                prose.append(clause)
        m = re.match(r"^(G\d+)\s*[:：]\s*(.*)$", " — ".join(prose))
        if m:
            out.append({"id": m.group(1), "label": m.group(2).strip(),
                        "phase": phase})
    return out


def _decode_command(value):
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise EngineError("invalid encoded evidence command: {}".format(exc))


def _parse_evidence(text):
    """Evidence records from `## Evidence` (see _render_state_sections)."""
    out = []
    body = _section(_strip_comments(text), "Evidence")
    cur = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        item = _LIST_ITEM_RE.match(line.strip())
        if item and not line.startswith((" ", "\t")):
            m = EVIDENCE_RE.match(item.group(1))
            if m:
                cur = {
                    "id": "E{}".format(m.group("n")),
                    "gates": [g for g in m.group("gate").split(",") if g],
                    "claims": [c for c in m.group("claims").split(",")
                               if c and c != "none"],
                    "revision": m.group("rev"),
                    "command": _decode_command(m.group("cmd")),
                    "exit_code": int(m.group("exit")),
                    "covering": m.group("covering").strip(),
                    "confidence": (int(m.group("conf"))
                                   if m.group("conf") else None),
                    "out": "",
                }
                out.append(cur)
            else:
                cur = None
        elif cur is not None and line.startswith((" ", "\t")):
            cont = re.match(r"^\s*(?:out|snippet)\s*:\s*(.*)$", line)
            if cont:
                cur["out"] = cont.group(1).strip()
    return out


def _parse_core(text):
    """[(slot, 'name — fact')] from `## Core` — 1-BASED slots."""
    out = []
    for i, item in enumerate(_bullets(_section(text, "Core")), 1):
        m = re.match(r"^(\d+)\.\s+(.*)$", item)
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
        else:
            out.append((i, item))
    return out


def _parse_open(text):
    """[{id, text, settled_by, closed_by}] from `## Open`."""
    out = []
    for item in _bullets(_section(text, "Open")):
        m = re.match(r"^(Q\d+)\s*[:：]\s*(.*)$", item)
        if not m:
            continue
        qid, rest = m.group(1), m.group(2)
        closed_by = ""
        mc = re.search(r"—\s*closed by:\s*(\S+)", rest)
        if mc:
            closed_by = mc.group(1)
            rest = rest[:mc.start()].strip()
        settled = ""
        ms = re.search(r"—\s*settled[- ]by:\s*(.*)$", rest)
        if ms:
            settled = ms.group(1).strip()
            rest = rest[:ms.start()].strip()
        out.append({"id": qid, "text": rest.strip(" —").strip(),
                    "settled_by": settled, "closed_by": closed_by})
    return out


def _parse_basis(text):
    """[{id, text, source, confidence}] from the frozen `### Basis`."""
    out = []
    for item in _bullets(_subsection(text, "Context", "Basis")):
        m = re.match(r"^(F\d+)\s*[:：]\s*(.*)$", item)
        if not m:
            continue
        fid, rest = m.group(1), m.group(2)
        source, confidence = "", ""
        ms = re.search(r"—\s*source:\s*(.*?)(?=\s+—\s*confidence:|$)", rest)
        if ms:
            source = ms.group(1).strip()
            rest = rest[:ms.start()].strip()
        mc = re.search(r"—\s*confidence:\s*(\S+)", rest)
        if mc:
            confidence = mc.group(1).strip()
            rest = rest[:mc.start()].strip()
        out.append({"id": fid, "text": rest.strip(" —").strip(),
                    "source": source, "confidence": confidence})
    return out


# ------------------------------------------------------ shaping parse ----

def shaping_findings(text):
    """[{id, text, source, confidence}] from `## Findings` (unique F# ids)."""
    out, seen = [], set()
    for item in _bullets(_section(text, "Findings")):
        m = re.match(r"^(F\d+)\s*[:：]\s*(.*)$", item)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        fid, rest = m.group(1), m.group(2)
        source, confidence = "", ""
        ms = re.search(r"—\s*source:\s*(.*?)(?=,\s*confidence\s|$)", rest)
        if ms:
            source = ms.group(1).strip().rstrip(",")
            rest = rest[:ms.start()].strip()
        mc = re.search(r",?\s*confidence\s*[:：]?\s*(\S+)", rest)
        if mc:
            confidence = mc.group(1).strip()
            rest = rest[:mc.start()].strip().rstrip(",")
        out.append({"id": fid, "text": rest.strip(" —").strip(),
                    "source": source, "confidence": confidence})
    return out


def validate_shaping(text):
    """(issues, warnings) for one versioned shaping source."""
    issues, warnings = [], []
    if text.lstrip().startswith("---"):
        issues.append("frontmatter is not part of riel-shaping/v1; use a marker line")
    if "<!-- riel-shaping/v1 -->" not in text.split("\n## ", 1)[0]:
        issues.append("missing <!-- riel-shaping/v1 --> after the title")
    if not re.match(r"^#\s*Shaping:", text.lstrip()):
        issues.append("title must be `# Shaping: <name>`")
    if not _first_line(_section(text, "Question")):
        issues.append("## Question is empty")
    findings = shaping_findings(text)
    raw_ids = re.findall(r"^[-*]\s*(F\d+)\s*[:：]",
                         _strip_comments(_section(text, "Findings")), re.M)
    dupes = sorted({i for i in raw_ids if raw_ids.count(i) > 1})
    if dupes:
        issues.append("duplicate finding id(s): {}".format(", ".join(dupes)))
    if not findings:
        issues.append("## Findings has no F# entries")
    for f in findings:
        if not f["source"]:
            issues.append("{} has no `— source:` — a finding without a "
                          "source is a hypothesis".format(f["id"]))
    if not _section(text, "Verdict"):
        warnings.append("no ## Verdict — the run's Objective has no seed")
    return issues, warnings


# ------------------------------------------------------ file plumbing ----

def _worktree_paths(worktree):
    riel_dir = os.path.join(worktree, RIEL_DIR)
    return {
        "dir": riel_dir,
        "run": os.path.join(riel_dir, RUN_MD),
        "shaping": os.path.join(riel_dir, SHAPING_MD),
        "lock": os.path.join(riel_dir, LOCK_NAME),
    }


def _refuse_legacy(worktree):
    """riel v1 state files are never read as state — refuse, loudly."""
    found = [name for name in LEGACY_STATE_FILES
             if os.path.exists(os.path.join(worktree, RIEL_DIR, name))]
    if found:
        raise EngineError(
            "legacy riel v1 state found in .riel/ ({}) — riel {} reads only "
            ".riel/run.md (format {}); archive or delete the legacy files "
            "(there is no converter)".format(
                ", ".join(".riel/" + f for f in found), VERSION, RUN_FORMAT))


def _read_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise EngineError("cannot read {}: {}".format(path, exc))


def _confine(path, worktree):
    """Reject ANY symlink on the path from worktree down to `path` itself.

    A state path that jumps outside the worktree through a symlink would let
    a write clobber an unrelated file — every component is checked, and the
    real parent must resolve back inside the worktree.
    """
    base = os.path.abspath(worktree)
    full = os.path.abspath(path)
    # Containment is decided on REAL paths: the worktree itself may sit under
    # a symlinked ancestor (macOS /var -> /private/var), which must not read
    # as an escape.
    real_base = os.path.realpath(base)
    real_full = os.path.realpath(full)
    rel = os.path.relpath(real_full, real_base)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise EngineError("path escapes the worktree: {}".format(path))
    # Defense in depth: when the UNRESOLVED path sits under the unresolved
    # worktree, walk its components and refuse any symlink — a symlinked
    # .riel/ or run.md never becomes a write target. (Mixed unresolved/
    # resolved spellings of the same directory skip the walk; the realpath
    # containment above is already decisive.)
    rel_raw = os.path.relpath(full, base)
    if not (rel_raw == os.pardir or rel_raw.startswith(os.pardir + os.sep)):
        cur = base
        for part in rel_raw.split(os.sep):
            cur = os.path.join(cur, part)
            if os.path.islink(cur):
                raise EngineError(
                    "refusing symlinked state path component: {}".format(cur))
    real_parent = os.path.dirname(real_full)
    if real_parent != real_base \
            and not real_parent.startswith(real_base + os.sep):
        raise EngineError(
            "state path resolves outside the worktree: {}".format(path))


def _atomic_write(path, text, worktree):
    """Write `text` to `path` atomically (tmp + fsync + rename), confined."""
    _confine(path, worktree)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".riel-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path, keep=MAX_BACKUPS):
    """Timestamped flat backup beside the file; at most `keep` are kept."""
    try:
        if not os.path.isfile(path) or os.path.islink(path):
            return
        directory = os.path.dirname(path) or "."
        base = os.path.basename(path)
        stem = base[:-3] if base.endswith(".md") else base
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = os.path.join(directory, "{}-{}.bak.md".format(stem, stamp))
        n = 1
        while os.path.exists(target):
            target = os.path.join(
                directory, "{}-{}-{}.bak.md".format(stem, stamp, n))
            n += 1
        shutil.copy2(path, target)
        backups = sorted(
            os.path.join(directory, f) for f in os.listdir(directory)
            if re.fullmatch(re.escape(stem) + r"-\d{8}-\d{6}(-\d+)?\.bak\.md",
                            f))
        for old in backups[:-keep]:
            try:
                os.unlink(old)
            except OSError:
                pass
    except OSError:
        pass


class _Locked:
    """Cross-process exclusive flock held for a whole write transaction."""

    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.fh = None

    def __enter__(self):
        root = os.path.dirname(os.path.dirname(self.lock_path))
        _confine(self.lock_path, root)
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        self.fh = open(self.lock_path, "a+")
        if fcntl is not None:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self.fh is not None:
            if fcntl is not None:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None
        return False


# ---------------------------------------------------- state derivation ----

def evidence_passes(ev):
    """exit 0 AND (confidence omitted or >= 12) — an explicit low score vetoes."""
    return ev["exit_code"] == 0 and (
        ev["confidence"] is None or ev["confidence"] >= CONFIDENCE_PASS)


def load_state(worktree, require_active=False, require_exists=True):
    """Read + parse .riel/run.md → dict; clean EngineError on every refusal."""
    paths = _worktree_paths(worktree)
    _refuse_legacy(worktree)
    if not os.path.exists(paths["run"]):
        if require_exists:
            raise EngineError(
                "no run state at {} — render one with `run new`, edit it, "
                "then `run activate`".format(paths["run"]))
        return None
    _confine(paths["run"], worktree)
    text = _read_file(paths["run"])
    if not marker_present(text):
        raise EngineError(
            "{} is not a {} file (missing {} after the title)".format(
                paths["run"], RUN_FORMAT, MARKER_LINE))
    plan_text, _ = _split_plan(text)
    meta = _parse_metadata(text)
    active = bool(meta.get("revision"))
    if require_active and not active:
        raise EngineError(
            "run at {} is a draft — `run activate` first".format(paths["run"]))
    graph_nodes, graph_edges, register = graph_any(plan_text,
                                                   strict_section=True)
    shaping_hash = None
    if active and meta.get("shaping_sha256") not in (None, "none"):
        shaping_hash = meta["shaping_sha256"]
    st = {
        "path": paths["run"],
        "text": text,
        "plan_text": plan_text,
        "active": active,
        "meta": meta,
        "revision": meta.get("revision") if active else None,
        "plan_hash": meta.get("plan_sha256") if active else None,
        "shaping_hash": shaping_hash,
        "claims": _parse_claims(plan_text),
        "gates": _parse_gates(plan_text),
        "evidence": _parse_evidence(text),
        "core": _parse_core(text),
        "open": _parse_open(text),
        "basis": _parse_basis(plan_text),
        "nodes": graph_nodes,
        "edges": graph_edges,
        "register": register,
    }
    st["counted_evidence"] = [e for e in st["evidence"]
                              if active and e["revision"] == st["revision"]]
    st["passed_gates"] = {g for e in st["counted_evidence"]
                          if evidence_passes(e) for g in e["gates"]}
    st["covered_claims"] = {c for e in st["counted_evidence"]
                            if evidence_passes(e) and st["active"]
                            for c in e["claims"]}
    st["done"] = (
        bool(st["claims"])
        and all(c["id"] in st["covered_claims"] for c in st["claims"])
        and all(g["id"] in st["passed_gates"] for g in st["gates"])
    )
    st["current_phase"], st["next"] = _derive_phase(st)
    return st


def _phase_gate_ids(st, phase_id):
    """A gate bound to a phase, or the run-global obligation set."""
    mapped = [gate["id"] for gate in st["gates"]
              if gate.get("phase") == phase_id]
    return mapped or [gate["id"] for gate in st["gates"]]


def _derive_phase(st):
    """(current_phase, next) — gates drive the phase, the DAG drives next.

    A phase is complete when every gate mapped to it has passing evidence
    AND every earlier phase is complete; a phase with no gate completes
    automatically once its predecessors do. `next` is the first work step
    of the current phase (its label), falling back to the phase label.
    """
    nodes, edges = st["nodes"], st["edges"]
    if not nodes:
        return None, None
    gates_by_phase = {
        pid: _phase_gate_ids(st, pid) for pid in _phase_order(nodes)
    }
    order = _phase_order(nodes)
    done_phases = set()
    current = None
    for pid in order:
        if all(gid in st["passed_gates"] for gid in gates_by_phase.get(pid, [])):
            done_phases.add(pid)
        else:
            current = pid
            break
    if current is None:
        return None, ("done" if st["done"] else None)
    steps = _phase_steps(nodes, edges, current)
    if steps:
        nxt = nodes[steps[0]][1] or steps[0]
    else:
        nxt = nodes[current][1] or current
    return current, nxt


# ---------------------------------------------------------- validation ----

def _check_plan(text, nodes, edges, shaping_path, active, basis, basis_only=False):
    """(issues, warnings) shared by validate / activate / rebase / slice."""
    issues, warnings = [], []

    if not marker_present(text):
        issues.append(
            "missing the {} marker line after the title".format(MARKER_LINE))
    if not re.match(r"^#\s*Run:\s*\S", text.lstrip()):
        issues.append("title must be `# Run: <name>`")

    headings = [t.strip() for _lvl, t in
                re.findall(r"^(#{1,2})\s+(.+)$", text, re.M)]
    wanted = ["Run:"] + list(PLAN_TITLES)
    pos = []
    for w in wanted:
        for i, t in enumerate(headings):
            if t == w or t.startswith(w):
                pos.append(i)
                break
        else:
            issues.append("missing plan section: {}".format(w))
    if pos != sorted(pos):
        issues.append("plan sections out of order")

    if not _first_line(_section(text, "Objective")):
        issues.append("## Objective is empty")
    if not _bullets(_section(text, "Constraints")):
        issues.append("## Constraints has no items")
    if not _bullets(_section(text, "DO NOT")):
        issues.append("## DO NOT has no items (scope enforcement missing)")
    if not _first_line(_section(text, "Deliverable")):
        issues.append("## Deliverable is empty")

    claims = _parse_claims(text)
    if not claims:
        issues.append("## Claims has no P# entries")
    seen = set()
    for c in claims:
        if c["id"] in seen:
            issues.append("duplicate claim id {}".format(c["id"]))
        seen.add(c["id"])

    gates = _parse_gates(text)
    gate_ids = {g["id"] for g in gates}
    if len(gate_ids) != len(gates):
        issues.append("duplicate gate id in ## Gates")
    phase_ids = {nid for nid in nodes if PHASE_ID_RE.match(nid)}
    for g in gates:
        if g["phase"] and g["phase"] not in phase_ids:
            issues.append("gate {} maps to phase {} which is not in the "
                          "graph".format(g["id"], g["phase"]))
        if not g["label"]:
            issues.append("gate {} has no label".format(g["id"]))

    # graph conventions — parsed shapes and parsed edges only
    if not nodes:
        issues.append("no execution graph under ## Graph (a ```mermaid block "
                      "or a plain F#/W# phase list)")
    else:
        if not edges:
            issues.append("execution graph has no edges")
        for nid, (shape, label) in nodes.items():
            lab = label.strip()
            verb_m = re.match(r"[A-Za-z]+", lab)
            verb = verb_m.group(0).upper() if verb_m else ""
            if shape == "[" and not PHASE_ID_RE.match(nid) \
                    and verb not in CLOSED_VERBS:
                issues.append(
                    "node {} {!r} does not start with a closed verb "
                    "(READ/EDIT/CREATE/RUN/VERIFY/ASK)".format(nid, lab[:50]))
            if verb == "ASK" and not re.match(
                    r"ASK\[(irreversible|outside-claims|goal-changing)\]", lab):
                issues.append(
                    "ASK node {} must start with its trigger: "
                    "ASK[irreversible|outside-claims|goal-changing]".format(nid))
        outgoing = {}
        for u, lbl, v in edges:
            outgoing.setdefault(u, []).append((lbl, v))
        for nid, (shape, _label) in nodes.items():
            if shape != "{":
                continue
            outs = outgoing.get(nid, [])
            if not outs or any(not lbl for lbl, _v in outs):
                issues.append(
                    "decision node {} needs a label on every outgoing edge "
                    "(parsed from the edges)".format(nid))
        blocks = re.findall(r"```mermaid\n(.*?)```", _section(text, "Graph"),
                            re.S)
        for block in blocks:
            if "<br" in block:
                issues.append("graph uses <br/> — mermaid v11 breaks on it")
            if any(ln.strip().startswith("style ")
                   for ln in block.splitlines()):
                issues.append(
                    "graph carries `style` — not a parsed-as-spec DAG")
        if graph_back_edges(edges) and not re.search(
                r"< *[0-9]|>= *[0-9]", _section(text, "Graph")):
            warnings.append(
                "graph has a loop but no counter guard (< 3 / >= 3)")
        issues.extend(mmdc_issues(blocks))

    # anchors
    node_ids = set(nodes)
    graph_section = _section(text, "Graph")
    for c in claims:
        if not c["anchor"]:
            warnings.append("{} has no anchor — add '— anchor: §Section#n', "
                            "a node id, or 'shaping:F#'".format(c["id"]))
            continue
        sm = FROZEN_RE.match(c["anchor"])
        am = SECTION_ANCHOR_RE.match(c["anchor"])
        if sm:
            fid = "F{}".format(sm.group(1))
            if active or basis_only:
                if not any(b["id"] == fid for b in basis):
                    issues.append(
                        "{} anchors {} — not present in the frozen Basis "
                        "(activate/rebase re-copies it)".format(
                            c["id"], c["anchor"]))
            elif shaping_path and os.path.isfile(shaping_path):
                stext = _read_file(shaping_path)
                if not any(f["id"] == fid
                           for f in shaping_findings(stext)):
                    issues.append(
                        "{} anchors {} — no such finding in {}".format(
                            c["id"], c["anchor"], shaping_path))
            else:
                warnings.append(
                    "{} anchors {} but no shaping file exists — activation "
                    "will refuse".format(c["id"], c["anchor"]))
        elif am:
            name, idx = am.group(1).strip(), am.group(2)
            body = _section(text, name)
            if not body:
                issues.append("{} anchor {} does not resolve — no such "
                              "section".format(c["id"], c["anchor"]))
            elif idx is not None:
                items = _bullets(body)
                if not 1 <= int(idx) <= len(items):
                    issues.append(
                        "{} anchor {} does not resolve — the section has {} "
                        "bullet(s)".format(c["id"], c["anchor"], len(items)))
        elif NODE_ANCHOR_RE.match(c["anchor"]):
            if c["anchor"] not in node_ids \
                    and c["anchor"] not in graph_section:
                warnings.append(
                    "{} anchor {} is not a node of this graph — on a slice "
                    "it is inherited from the parent".format(
                        c["id"], c["anchor"]))
        else:
            issues.append(
                "{} anchor {!r} is not a valid form: §<Section>[#<n>] | "
                "<NodeId> | shaping:F#".format(c["id"], c["anchor"]))
    return issues, warnings


def _validate_active_hashes(st, shaping_path):
    """The stale check: plan/shaping bytes must match the activated hashes."""
    current_plan = plan_sha256(st["plan_text"])
    if st["plan_hash"] and st["plan_hash"] != current_plan:
        raise EngineError(
            "stale state: the plan changed since {} — run `run rebase` "
            "(old evidence is reserved, not lost)".format(st["revision"]),
            code=3)
    current = None
    if os.path.isfile(shaping_path):
        current = hashlib.sha256(
            _read_file(shaping_path).encode("utf-8")).hexdigest()
    if st["shaping_hash"] != current:
        raise EngineError(
            "stale state: .riel/shaping.md changed since {} — run "
            "`run rebase`".format(st["revision"]), code=3)


# ---------------------------------------------------------- rendering ----

def _render_state_sections(meta, core, open_qs, evidence, current_phase):
    lines = ["## Metadata", ""]
    for key in ("format", "revision", "activated", "plan_sha256",
                "shaping_sha256"):
        if key in meta:
            lines.append("- {}: {}".format(key, meta[key]))
    lines += ["", "## Execution state", "",
              "- current_phase: {}".format(current_phase or "none"),
              "", "## Core", ""]
    if core:
        for slot, entry in sorted(core):
            entry = re.sub(r"\s+", " ", entry).strip()
            lines.append("- {}. {}".format(slot, entry))
    else:
        lines.append("<!-- empty -->")
    lines += ["", "## Open", ""]
    if open_qs:
        for q in open_qs:
            question = re.sub(r"\s+", " ", q["text"]).strip()
            settled_by = re.sub(r"\s+", " ", q.get("settled_by") or "").strip()
            line = "- {}: {}".format(q["id"], question)
            if settled_by:
                line += " — settled-by: {}".format(settled_by)
            if q.get("closed_by"):
                line += " — closed by: {}".format(q["closed_by"])
            lines.append(line)
    else:
        lines.append("<!-- empty -->")
    lines += ["", "## Evidence", ""]
    if evidence:
        for ev in evidence:
            line = ("- {} gate:{} claims:{} revision:{} command_b64:{} "
                    "exit_code:{} covering:{}".format(
                        ev["id"], ",".join(ev["gates"]),
                        ",".join(ev["claims"]) or "none", ev["revision"],
                        base64.b64encode(ev["command"].encode("utf-8")).decode("ascii"),
                        ev["exit_code"], ev["covering"]))
            if ev["confidence"] is not None:
                line += " confidence:{}".format(ev["confidence"])
            lines.append(line)
            if ev.get("out"):
                lines.append("  out: {}".format(ev["out"]))
    else:
        lines.append("<!-- empty -->")
    return "\n".join(lines) + "\n"


def _build_basis(plan_text, findings, shaping_hash):
    """Replace (or insert) the frozen `### Basis` inside `## Context`."""
    entries = ["### Basis",
               "<!-- Frozen from .riel/shaping.md (sha256 {}). Edit the "
               "shaping and run `run rebase` to refresh; the plan is "
               "otherwise frozen. -->".format(shaping_hash)]
    for f in findings:
        line = "- {}: {}".format(f["id"], f["text"])
        if f["source"]:
            line += " — source: {}".format(f["source"])
        if f["confidence"]:
            line += " — confidence: {}".format(f["confidence"])
        entries.append(line)
    block = "\n".join(entries) + "\n\n"
    text = re.sub(r"### Basis\n.*?(?=\n###\s|\n##\s|\Z)", "", plan_text,
                  flags=re.S | re.M)
    kw = re.search(r"### Context keywords\n.*?(?=\n###\s|\n##\s|\Z)",
                   text, re.S | re.M)
    if kw:
        return text[:kw.end()] + "\n" + block + text[kw.end():].lstrip("\n")
    ctx = re.search(r"^## Context[^\n]*\n", text, re.M)
    if ctx:
        return text[:ctx.end()] + "\n" + block + text[ctx.end():]
    raise EngineError("no ## Context section to freeze the Basis into")


def _referenced_finding_ids(plan_text):
    ids = []
    for c in _parse_claims(plan_text):
        m = FROZEN_RE.match(c["anchor"] or "")
        if m:
            ids.append("F{}".format(m.group(1)))
    return ids


# --------------------------------------------------------------- verbs ----

def cmd_shape(args, out, err):
    if args.cmd2 == "new":
        return _shape_new(args, out, err)
    if args.cmd2 == "fetch":
        return _fetch_verb(args, out, err)
    return _shape_validate(args, out, err)


def _shape_validate(args, out, err):
    path = getattr(args, "path", None) or \
        _worktree_paths(args.worktree)["shaping"]
    if not os.path.isfile(path):
        raise EngineError("no shaping file at {}".format(path))
    text = _read_file(path)
    issues, warnings = validate_shaping(text)
    for w in warnings:
        print("WARN: {}".format(w), file=err)
    if issues:
        print("INVALID shaping {}:".format(path), file=out)
        for issue in issues:
            print("  - " + issue, file=out)
        return 1
    print("valid shaping: {} ({} finding(s))".format(
        path, len(shaping_findings(text))), file=out)
    return 0


def _shape_new(args, out, err):
    text, leftover = _render_template("shaping", args.param,
                                      args.template_dir, args.strict, args.worktree)
    for name in sorted(set(leftover)):
        print("note: unfilled placeholder {{{{{}}}}}".format(name), file=err)
    print(text, end="", file=out)
    return 0


def cmd_run(args, out, err):
    return {
        "new": _run_new,
        "validate": _run_validate,
        "activate": _run_activate,
        "rebase": _run_rebase,
        "status": _run_status,
        "slice": _run_slice,
        "fetch": _fetch_verb,
    }[args.cmd2](args, out, err)


def _run_new(args, out, err):
    text, leftover = _render_template("run", args.param,
                                      args.template_dir, args.strict, args.worktree)
    for name in sorted(set(leftover)):
        print("note: unfilled placeholder {{{{{}}}}}".format(name), file=err)
    print(text, end="", file=out)
    return 0


def _run_validate(args, out, err):
    paths = _worktree_paths(args.worktree)
    path = args.file or paths["run"]
    text = _read_file(path)
    if not marker_present(text):
        raise EngineError(
            "{} is not a {} file (missing {} after the title); riel {} "
            "does not read legacy formats".format(
                path, RUN_FORMAT, MARKER_LINE, VERSION))
    plan_text, _ = _split_plan(text)
    meta = _parse_metadata(text)
    active = bool(meta.get("revision"))
    nodes, edges, _reg = graph_any(plan_text, strict_section=True)
    basis = _parse_basis(plan_text)
    issues, warnings = _check_plan(
        text, nodes, edges, paths["shaping"], active, basis,
        basis_only=bool(basis))
    if active:
        try:
            _validate_active_hashes({
                "plan_text": plan_text,
                "revision": meta.get("revision"),
                "plan_hash": meta.get("plan_sha256"),
                "shaping_hash": (None if meta.get("shaping_sha256") == "none"
                                 else meta.get("shaping_sha256")),
            }, paths["shaping"])
        except EngineError as exc:
            issues.append(str(exc))
    for w in warnings:
        print("WARN: {}".format(w), file=err)
    if issues:
        print("INVALID run {}:".format(path), file=out)
        for issue in issues:
            print("  - " + issue, file=out)
        return 1
    print("valid {} run: {}".format("active" if active else "draft", path),
          file=out)
    return 0


def _freeze_from_shaping(paths, plan_text, err):
    """(plan_with_basis, shaping_hash, findings) — or None after refusing.

    Present shaping → validated, referenced findings frozen into Basis.
    Missing shaping → allowed ONLY with NO shaping anchors.
    """
    shaping_hash = "none"
    findings = []
    referenced = _referenced_finding_ids(plan_text)
    if os.path.isfile(paths["shaping"]):
        stext = _read_file(paths["shaping"])
        s_issues, s_warns = validate_shaping(stext)
        for w in s_warns:
            print("WARN: shaping: {}".format(w), file=err)
        if s_issues:
            print("refusing — invalid .riel/shaping.md:", file=err)
            for issue in s_issues:
                print("  - " + issue, file=err)
            return None
        by_id = {f["id"]: f for f in shaping_findings(stext)}
        for fid in referenced:
            if fid not in by_id:
                print("refusing — a claim anchors {} which does not exist "
                      "in .riel/shaping.md".format(fid), file=err)
                return None
            findings.append(by_id[fid])
        shaping_hash = hashlib.sha256(stext.encode("utf-8")).hexdigest()
    elif referenced:
        print("refusing — claims anchor shaping findings ({}) but "
              ".riel/shaping.md does not exist".format(
                  ", ".join(referenced)), file=err)
        return None
    if findings:
        plan_text = _build_basis(plan_text, findings, shaping_hash)
    return plan_text, shaping_hash, findings


def _run_activate(args, out, err):
    paths = _worktree_paths(args.worktree)
    _refuse_legacy(args.worktree)
    with _Locked(paths["lock"]):
        if not os.path.exists(paths["run"]):
            raise EngineError(
                "no run to activate at {} — `run new` renders the template; "
                "an editor writes the file".format(paths["run"]))
        text = _read_file(paths["run"])
        if not marker_present(text):
            raise EngineError("{} is not a {} file (missing {})".format(
                paths["run"], RUN_FORMAT, MARKER_LINE))
        meta = _parse_metadata(text)
        if meta.get("revision"):
            raise EngineError(
                "run at {} is already active (revision {}) — a run "
                "activates once; edit the plan and `run rebase` instead"
                .format(paths["run"], meta["revision"]))
        plan_text, _ = _split_plan(text)
        nodes, edges, _reg = graph_any(plan_text, strict_section=True)
        issues, _warnings = _check_plan(
            text, nodes, edges, paths["shaping"], False, [])
        if issues:
            print("refusing activation — {} issue(s):".format(len(issues)),
                  file=out)
            for issue in issues:
                print("  - " + issue, file=out)
            return 1
        frozen = _freeze_from_shaping(paths, plan_text, err)
        if frozen is None:
            return 1
        plan_text, shaping_hash, _findings = frozen
        meta = {
            "format": RUN_FORMAT,
            "revision": "r1",
            "activated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "plan_sha256": plan_sha256(plan_text),
            "shaping_sha256": shaping_hash,
        }
        body = plan_text + "\n" + _render_state_sections(
            meta, [], [], [], None)
        _backup(paths["run"])
        _atomic_write(paths["run"], body, args.worktree)
    st = load_state(args.worktree, require_active=True)
    print("activated {} revision r1 — current_phase: {}, next: {}".format(
        paths["run"], st["current_phase"] or "(no graph)", st["next"] or "-"),
        file=out)
    return 0


def _run_rebase(args, out, err):
    paths = _worktree_paths(args.worktree)
    with _Locked(paths["lock"]):
        st = load_state(args.worktree, require_active=True)
        old_revision = st["revision"]
        plan_text = st["plan_text"]
        nodes, edges, _reg = graph_any(plan_text, strict_section=True)
        issues, _w = _check_plan(plan_text, nodes, edges, paths["shaping"],
                                 False, [])
        if issues:
            print("refusing rebase — {} issue(s):".format(len(issues)),
                  file=out)
            for issue in issues:
                print("  - " + issue, file=out)
            return 1
        frozen = _freeze_from_shaping(paths, plan_text, err)
        if frozen is None:
            return 1
        plan_text, shaping_hash, _findings = frozen
        new_plan_hash = plan_sha256(plan_text)
        if (new_plan_hash == st["plan_hash"]
                and shaping_hash == (st["shaping_hash"] or "none")):
            print("nothing to rebase — plan and shaping match {}".format(
                old_revision), file=out)
            return 0
        rev_n = int(old_revision[1:]) + 1
        meta = dict(st["meta"])
        meta.update({
            "revision": "r{}".format(rev_n),
            "plan_sha256": new_plan_hash,
            "shaping_sha256": shaping_hash,
            "activated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        # Old evidence is RETAINED verbatim but no longer counted: its
        # revision no longer matches the current one.
        body = plan_text + "\n" + _render_state_sections(
            meta, st["core"], st["open"], st["evidence"], st["current_phase"])
        _backup(paths["run"])
        _atomic_write(paths["run"], body, args.worktree)
    print("rebased to r{} — {} evidence record(s) reserved (retained, not "
          "counted)".format(rev_n, len(st["evidence"])), file=out)
    return 0


def _run_status(args, out, err):
    st = load_state(args.worktree)
    assert st is not None  # require_exists=True rejects the missing run above
    if st["active"]:
        _validate_active_hashes(
            st, os.path.join(args.worktree, RIEL_DIR, SHAPING_MD))
    payload = {
        "format": RUN_FORMAT,
        "revision": st["revision"],
        "status": "active" if st["active"] else "draft",
        "current_phase": st["current_phase"],
        "next": st["next"],
        "claims": {c["id"]: ("covered" if c["id"] in st["covered_claims"]
                             else "open") for c in st["claims"]},
        "gates": {g["id"]: ("passed" if g["id"] in st["passed_gates"]
                            else "pending") for g in st["gates"]},
        "open": {q["id"]: ("closed" if q["closed_by"] else "open")
                 for q in st["open"]},
        "evidence": {"total": len(st["evidence"]),
                     "counted": len(st["counted_evidence"])},
        "done": st["done"],
        "todos": todo_projection(st),
    }
    print(json.dumps(payload, ensure_ascii=False), file=out)
    return 0


def _run_slice(args, out, err):
    paths = _worktree_paths(args.worktree)
    st = load_state(args.worktree, require_active=True)
    nodes, edges = st["nodes"], st["edges"]
    if not nodes:
        raise EngineError("the run has no graph to slice")
    phase = args.phase
    if phase not in nodes:
        raise EngineError(
            "no phase node {!r} in the run's graph (phases: {})".format(
                phase, ", ".join(_phase_order(nodes)) or "none"))
    keep = _phase_subgraph(nodes, edges, phase)
    closers = {"[": "]", "(": ")", "{": "}"}

    claims = [c for c in st["claims"]
              if NODE_ANCHOR_RE.match(c["anchor"] or "")
              and c["anchor"] in keep]
    if not claims:
        claims = st["claims"]
    gates = [g for g in st["gates"] if g["phase"] == phase]

    title_m = re.match(r"^#\s*Run:\s*(.+)$", st["plan_text"], re.M)
    parent_title = title_m.group(1).strip() if title_m else "(task)"
    body = ["# Run: {} — {}".format(parent_title, nodes[phase][1] or phase),
            MARKER_LINE, ""]
    for name in PLAN_TITLES:
        body.append("## " + name)
        if name == "Graph":
            body += ["", "```mermaid", "flowchart TD"]
            for nid, (opener, label) in nodes.items():
                if nid in keep:
                    body.append('  {}{}"{}"{}'.format(
                        nid, opener, (label or nid).replace('"', "'"),
                        closers[opener]))
            for u, lbl, v in edges:
                if u in keep and v in keep:
                    body.append("  {} -->|{}| {}".format(u, lbl, v) if lbl
                                else "  {} --> {}".format(u, v))
            body += ["```"]
        elif name == "Claims":
            body.append("")
            for c in claims:
                line = "- {}: {}".format(c["id"], c["text"])
                if c["anchor"]:
                    line += " — anchor: {}".format(c["anchor"])
                body.append(line)
        elif name == "Gates":
            body.append("")
            for g in gates:
                line = "- {}: {}".format(g["id"], g["label"])
                if g["phase"]:
                    line += " — phase: {}".format(g["phase"])
                body.append(line)
            if not gates:
                body.append(
                    "<!-- no gate mapped to {} in the parent run -->".format(
                        phase))
        elif name == "Context":
            body.append("")
            basis = _subsection(st["plan_text"], "Context", "Basis")
            if basis:
                body += ["### Basis", basis, ""]
            why = _subsection(st["plan_text"], "Context", "Why")
            if why:
                body += ["### Why", why, ""]
            kws = context_keywords(st["plan_text"])
            if kws:
                body += ["### Context keywords"]
                body += ["- {}{}".format(
                    k["term"],
                    " → {}".format(k["source"]) if k["source"] else "")
                    for k in kws]
                body.append("")
        else:
            section = _section(st["plan_text"], name)
            if section:
                body += ["", section]
        body.append("")
    packet = "\n".join(body).rstrip("\n") + "\n"

    # self-validating: the packet must pass the same validator as a draft
    nodes2, edges2, _r = graph_any(packet, strict_section=True)
    issues, _w = _check_plan(packet, nodes2, edges2, paths["shaping"],
                             False, _parse_basis(packet), basis_only=True)
    if issues:
        raise EngineError("slice of {} is not self-validating: {}".format(
            phase, "; ".join(issues)))
    if args.output:
        target = args.output if os.path.isabs(args.output) \
            else os.path.join(args.worktree, args.output)
        _atomic_write(target, packet, args.worktree)
    print(packet, end="", file=out)
    return 0


# --------------------------------------------------------------- note ----

def _note_evidence(st, args):
    """Run --command in the worktree; capture the REAL exit code + snippet.

    There is no way to self-supply an exit code: none exists as a flag.
    """
    plan_claims = {c["id"] for c in st["claims"]}
    plan_gates = {g["id"] for g in st["gates"]}
    for g in args.gate:
        if g not in plan_gates:
            raise EngineError("unknown gate {!r} — ## Gates has {}".format(
                g, ", ".join(sorted(plan_gates)) or "no gates"))
    for c in args.claim:
        if c not in plan_claims:
            raise EngineError("unknown claim {!r} — ## Claims has {}".format(
                c, ", ".join(sorted(plan_claims)) or "no claims"))
    if not args.command:
        raise EngineError(
            "--gate evidence needs --command (the engine runs it and "
            "captures the exit code; self-supplied codes do not exist)")
    if not args.covering:
        raise EngineError(
            "--gate evidence needs --covering (what scope the command "
            "actually covers)")
    if args.confidence is not None and not 1 <= args.confidence <= 20:
        raise EngineError("--confidence must be 1..20")
    command = args.command
    try:
        proc = subprocess.run(
            command, shell=True, cwd=args.worktree,
            capture_output=True, timeout=NOTE_TIMEOUT)
        exit_code = proc.returncode
        raw = (proc.stdout or b"") + (proc.stderr or b"")
        snippet = re.sub(r"\s+", " ",
                         raw.decode("utf-8", "replace")).strip()
    except subprocess.TimeoutExpired as exc:
        exit_code = 124  # conventional: the command was killed on timeout
        raw = (exc.stdout or b"") + (exc.stderr or b"")
        snippet = (re.sub(r"\s+", " ",
                          raw.decode("utf-8", "replace")).strip()
                   + " [timeout after {}s]".format(NOTE_TIMEOUT)).strip()
    except OSError as exc:
        raise EngineError("could not run --command: {}".format(exc))
    snippet = snippet[:NOTE_SNIPPET_CHARS]
    next_n = 1 + max((int(e["id"][1:]) for e in st["evidence"]), default=0)
    records = []
    for i, g in enumerate(args.gate):
        records.append({
            "id": "E{}".format(next_n + i),
            "gates": [g],
            "claims": list(args.claim),
            "revision": st["revision"],
            "command": command,
            "exit_code": exit_code,
            "covering": re.sub(r"\s+", " ", args.covering).strip(),
            "confidence": args.confidence,
            "out": snippet,
        })
    return records


def _note_core(st, args):
    text = re.sub(r"[\r\n]+", " ", args.core).strip()
    if " — " not in text:
        raise EngineError(
            "--core must look like 'name — defining fact' (em-dash)")
    core = list(st["core"])
    if args.core_slot is not None:
        slot = args.core_slot
        if slot < 1 or slot > len(core) + 1:
            raise EngineError(
                "--core-slot must be 1..{} (1-based; {} live entr{})".format(
                    len(core) + 1, len(core),
                    "y" if len(core) == 1 else "ies"))
        core = [(s, e) for s, e in core if s != slot]
        core.append((slot, text))
    else:
        core.append((len(core) + 1, text))
    if len(core) > 2:
        raise EngineError("Core is full (2/2); replace an existing --core-slot")
    return sorted(core)


def cmd_note(args, out, err):
    paths = _worktree_paths(args.worktree)
    gate_mode = bool(args.gate or args.claim or args.command
                     or args.covering)
    if not any((args.gate, args.claim, args.command, args.covering,
                args.core, args.open is not None, args.close is not None)):
        raise EngineError(
            "note writes state: --gate G# --claim P# --command CMD "
            "--covering WHAT | --core 'name — fact' [--core-slot N] | "
            "--open Q --settled-by TEST | --close Q# --evidence E#")
    if gate_mode and not args.gate:
        raise EngineError("--gate evidence needs at least one --gate")
    if args.core_slot is not None and args.core is None:
        raise EngineError("--core-slot needs --core")
    if args.settled_by and args.open is None:
        raise EngineError("--settled-by needs --open")
    if args.open is not None and not args.settled_by:
        raise EngineError("--open requires --settled-by (the cheapest "
                          "refuting test)")
    if args.evidence_ref is not None and args.close is None:
        raise EngineError("--evidence needs --close")
    if args.close is not None:
        if args.evidence_ref is None:
            raise EngineError(
                "--close requires --evidence E# (a question closes against "
                "evidence, never silently)")
        if gate_mode:
            raise EngineError("one note, one kind: question close OR gate "
                              "evidence — not a mix")
    if gate_mode and (args.core is not None or args.open is not None
                      or args.close is not None):
        raise EngineError("one note, one kind: gate evidence OR core OR "
                          "open/close — not a mix")
    with _Locked(paths["lock"]):
        st = load_state(args.worktree, require_active=True)
        _validate_active_hashes(st, paths["shaping"])
        core, open_qs, evidence = st["core"], st["open"], st["evidence"]
        what = ""
        if gate_mode:
            new = _note_evidence(st, args)
            what = ", ".join(e["id"] for e in new)
            evidence = evidence + new
        if args.core is not None:
            core = _note_core(st, args)
            what = "--core"
        if args.open is not None:
            next_q = 1 + max((int(q["id"][1:]) for q in open_qs), default=0)
            open_qs = open_qs + [{
                "id": "Q{}".format(next_q), "text": args.open,
                "settled_by": args.settled_by, "closed_by": ""}]
            what = "Q{}".format(next_q)
        if args.close is not None:
            target = "Q{}".format(args.close)
            hits = [q for q in open_qs if q["id"] == target]
            if not hits:
                raise EngineError("no such open question {}".format(target))
            if hits[0]["closed_by"]:
                raise EngineError("{} is already closed by {}".format(
                    target, hits[0]["closed_by"]))
            ev_ids = {e["id"] for e in st["evidence"]}
            if "E{}".format(args.evidence_ref) not in ev_ids:
                raise EngineError(
                    "--evidence E{} does not exist — ## Evidence has {}".format(
                        args.evidence_ref,
                        ", ".join(sorted(ev_ids)) or "no evidence"))
            open_qs = [dict(q, closed_by="E{}".format(args.evidence_ref))
                       if q["id"] == target else q for q in open_qs]
            what = "closed {}".format(target)
        meta = dict(st["meta"])
        body = st["plan_text"] + "\n" + _render_state_sections(
            meta, core, open_qs, evidence, st["current_phase"])
        _backup(paths["run"])
        _atomic_write(paths["run"], body, args.worktree)
    st2 = load_state(args.worktree, require_active=True)
    print("noted {} — revision {} | phase {} | next: {} | claims {}/{} "
          "covered | gates passed: {} | done: {}".format(
              what, st2["revision"], st2["current_phase"] or "-",
              st2["next"] or "-",
              sum(1 for c in st2["claims"]
                  if c["id"] in st2["covered_claims"]),
              len(st2["claims"]),
              ", ".join(sorted(st2["passed_gates"])) or "none",
              str(st2["done"]).lower()), file=out)
    return 0


# --------------------------------------------------------------- todo ----

def todo_projection(st):
    """Project Plan+Evidence as Hermes checks with their step subchecks.

    A phase is a check; each gate mapped to it is a nested check; each work
    step hangs under the gate that verifies it (or directly under the phase
    when the phase has no explicit gate). Only passing current-revision
    evidence completes a check. A global gate is a top-level check.
    """
    nodes, edges = st["nodes"], st["edges"]
    phase_ids = _phase_order(nodes)
    objective = _first_line(_section(st["plan_text"], "Objective"))
    items = [{
        "id": "riel-goal", "content": "GOAL: " + (objective or "<empty>"),
        "status": "completed" if st["done"] else "pending",
    }]
    completed_phases = set()
    for index, phase_id in enumerate(phase_ids):
        predecessors_done = set(phase_ids[:index]) == completed_phases
        phase_gate_ids = _phase_gate_ids(st, phase_id)
        if predecessors_done and all(
                gate_id in st["passed_gates"] for gate_id in phase_gate_ids):
            completed_phases.add(phase_id)
    work_started = st["done"]
    for phase_id in phase_ids:
        steps = _phase_steps(nodes, edges, phase_id)
        phase_gates = [g for g in st["gates"] if g.get("phase") == phase_id]
        complete = phase_id in completed_phases
        current = phase_id == st["current_phase"] and not complete
        phase_row = "riel-phase-" + phase_id
        items.append({
            "id": phase_row,
            "content": "PHASE {}: {}".format(phase_id, nodes[phase_id][1]),
            "status": "completed" if complete else (
                "in_progress" if current else "pending"),
            "parent": "riel-goal",
        })
        gate_rows = {}
        for gate in phase_gates:
            passed = gate["id"] in st["passed_gates"]
            items.append({
                "id": "riel-gate-" + gate["id"],
                "content": "CHECK {}: {}".format(gate["id"], gate["label"]),
                "status": "completed" if passed else (
                    "in_progress" if current and not work_started else "pending"),
                "parent": phase_row,
            })
            gate_rows[gate["id"]] = "riel-gate-" + gate["id"]
        step_parent = next(iter(gate_rows.values()), phase_row)
        for step_id in steps:
            status = "completed" if complete else "pending"
            if current and not work_started:
                status = "in_progress"
                work_started = True
            items.append({
                "id": "riel-step-{}-{}".format(phase_id, step_id),
                "content": "{}: {}".format(step_id, nodes[step_id][1] or step_id),
                "status": status,
                "parent": step_parent,
            })
    # A gate with no phase is a run-global check: keep it at plan level.
    mapped = {g["id"] for g in st["gates"] if g.get("phase")}
    for gate in st["gates"]:
        if gate["id"] in mapped:
            continue
        items.append({
            "id": "riel-gate-" + gate["id"],
            "content": "GLOBAL CHECK {}: {}".format(gate["id"], gate["label"]),
            "status": "completed" if gate["id"] in st["passed_gates"] else "pending",
            "parent": "riel-goal",
        })
    if st["done"]:
        for row in items:
            row["status"] = "completed"
    return items


def cmd_todo(args, out, err):
    """Compatibility projection for callers that still read `riel todo`."""
    st = load_state(args.worktree)
    assert st is not None  # require_exists=True rejects the missing run above
    print(json.dumps(todo_projection(st), ensure_ascii=False), file=out)
    return 0


# -------------------------------------------------------------- clean ----

def cmd_clean(args, out, err):
    """Snapshot and archive every requested artifact before removing any."""
    paths = _worktree_paths(args.worktree)
    targets = [paths["run"]]
    if args.all:
        targets.append(paths["shaping"])
    with _Locked(paths["lock"]):
        targets = [path for path in targets if os.path.isfile(path)]
        for path in targets:
            _confine(path, args.worktree)
        snapshots = [(path, _read_file(path)) for path in targets]
        if not args.purge:
            for path, _body in snapshots:
                _backup(path, keep=MAX_BACKUPS)
        removed = []
        failing_path = "<requested targets>"
        try:
            for path, _body in snapshots:
                failing_path = path
                os.unlink(path)
                removed.append(os.path.relpath(path, args.worktree))
        except OSError as exc:
            raise EngineError(
                "clean failed at {}: {}; previous originals remain or can be "
                "restored from their .riel backups".format(failing_path, exc))
    if removed:
        print("cleaned: {}{}".format(
            ", ".join(removed),
            "" if args.purge else " (backed up in .riel/)"), file=out)
    else:
        print("nothing to clean", file=out)
    return 0


# -------------------------------------------------------------- check ----

def _dense_report(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return False, "ship: cannot read {}: {}".format(path, exc)
    problems = [(lineno, line) for lineno, line in
                enumerate(text.splitlines(), 1) if DENSE_RE.search(line)]
    if not problems:
        return True, "{}: clean".format(path)
    out = ["{}: dense markers found in outer register:".format(path)]
    out += ["  L{}: {}".format(lineno, line[:120])
            for lineno, line in problems[:20]]
    return False, "\n".join(out)


def _digest_report(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return False, "digest: cannot read {}: {}".format(path, exc)
    nodes, edges, _register = graph_any(text, strict_section=False)
    if not nodes:
        return True, "SKIP: {} (no execution graph)".format(path)
    out = ["Graph digest — explicit structure (the diagram stays for humans)",
           "", "Elements ({}):".format(len(nodes))]
    for nid, (_shape, label) in nodes.items():
        out.append("  {} — {}".format(nid, label))
    out += ["", "Edges, authored order ({}):".format(len(edges))]
    for u, lbl, v in edges:
        out.append("  {} {} {}".format(
            u, "=[{}]=>".format(lbl) if lbl else "->", v))
    outgoing = {}
    for u, lbl, v in edges:
        outgoing.setdefault(u, []).append((lbl, v))
    branches = {u: a for u, a in outgoing.items()
                if len({v for _l, v in a}) > 1}
    if branches:
        out += ["", "Branches (decision → labeled alternatives):"]
        for u, alts in branches.items():
            out.append("  {} → {}".format(
                u, " | ".join("{}: {}".format(l or "?", v)
                              for l, v in alts)))
    incoming = {v for _u, _l, v in edges}
    source = {u for u, _l, _v in edges}
    entries = [nid for nid in nodes if nid not in incoming] or ["(none)"]
    terminals = [nid for nid in nodes if nid not in source] or ["(none)"]
    out += ["", "Entry (no incoming): " + ", ".join(entries),
            "Terminals (no outgoing): " + ", ".join(terminals)]
    backs = graph_back_edges(edges)
    if backs:
        guarded = bool(re.search(r"< *[0-9]|>= *[0-9]", text))
        out.append("Loops (back-edges): " + ", ".join(
            "{}->{}".format(u, v) for u, _l, v in backs)
            + ("  guards: yes" if guarded
               else "  guards: NONE — add a bounded '< 3 / >= 3'"))
    out += ["", "Meaning & limits: a graph proves order, branches and loops "
            "only. It does not prove a command ran, a gate passed, or the "
            "deliverable exists — that lives in the gates and the evidence."]
    return True, "\n".join(out)


def _mermaid_report(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return False, "MISSING: {}".format(path), 0
    try:
        with open(path, encoding="utf-8") as fh:
            blocks = re.findall(r"```mermaid\n(.*?)```", fh.read(), re.S)
    except OSError as exc:
        return False, "mermaid: cannot read {}: {}".format(path, exc), 0
    if not blocks:
        return True, "SKIP: {} (no mermaid block)".format(path), 0
    if not shutil.which(VERIFY_CMD):
        return True, "SKIP: {} ({} block(s), mmdc not installed)".format(
            path, len(blocks)), len(blocks)
    issues = mmdc_issues(blocks)
    if issues:
        return False, "\n".join(
            "FAIL: {} -> {}".format(path, issue.replace("\n", " ")[:200])
            for issue in issues), len(blocks)
    return True, "PASS: {} -> {} block(s)".format(
        path, len(blocks)), len(blocks)


def cmd_check(args, out, err):
    path = os.path.expanduser(args.file)
    halves, ok = {}, True
    for name, fn in (("ship", _dense_report), ("digest", _digest_report)):
        passed, text = fn(path)
        halves[name] = {"passed": passed, "stdout": text}
        ok = ok and passed
    if args.mermaid:
        passed, text, _blocks = _mermaid_report(path)
        halves["mermaid"] = {"passed": passed, "stdout": text}
        ok = ok and passed
    print(json.dumps({"file": path, "passed": ok, "halves": halves},
                     ensure_ascii=False), file=out)
    return 0 if ok else 1


# -------------------------------------------------------------- fetch ----
# ONE secure fetch implementation, shared by `run fetch` and `shape fetch`:
# sha256 MANDATORY, scheme policy applied to EVERY redirect hop,
# Authorization/Cookie stripped when the origin changes, incomplete
# Content-Length bodies rejected, atomic confined write, NO auto activation,
# and URLs are never printed with their path/query (credentials live there).

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _redact_url(url):
    """scheme://host — path and query stripped (they can carry secrets)."""
    parts = urllib.parse.urlsplit(url)
    hostname = parts.hostname or ""
    if ":" in hostname:
        hostname = "[{}]".format(hostname)
    try:
        netloc = hostname if parts.port is None else "{}:{}".format(hostname, parts.port)
    except ValueError:
        netloc = hostname
    return urllib.parse.urlunsplit((parts.scheme, netloc, "", "", ""))


def _origin(url):
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme, (parts.hostname or "").lower(),
            parts.port or (443 if parts.scheme == "https" else 80))


def _scheme_allowed(url, allow_http):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https":
        return True, ""
    if parts.scheme == "http" and (allow_http or host in (
            "localhost", "127.0.0.1", "::1")):
        return True, ""
    return False, ("refusing plain http to non-local host {!r} — use https "
                   "or --allow-http (trusted transport)".format(host))


def _next_redirect(current, location, headers):
    """Resolve one hop without caller headers leaking or HTTPS downgrading."""
    target = urllib.parse.urljoin(current, location)
    if (urllib.parse.urlsplit(current).scheme == "https"
            and urllib.parse.urlsplit(target).scheme != "https"):
        raise EngineError("fetch refuses an https redirect downgrade to http")
    if _origin(target) != _origin(current):
        headers = {}
    return target, headers


def _secure_fetch(url, output, sha256, worktree, allow_http=False,
                  timeout=30.0, max_bytes=5 * 1024 * 1024, headers=None):
    """Fetch URL → output. Returns (bytes, digest). Raises EngineError."""
    if not sha256 or not SHA256_RE.match(sha256.strip().lower()):
        raise EngineError(
            "fetch requires --sha256 (a 64-hex digest) — integrity is "
            "mandatory, not optional")
    if not output:
        raise EngineError("fetch requires -o FILE (kind=out)")
    current, headers = url, dict(headers or {})
    resp = None
    for _hop in range(6):
        ok, why = _scheme_allowed(current, allow_http)
        if not ok:
            raise EngineError(why)
        req = urllib.request.Request(current)
        for name, value in headers.items():
            req.add_header(name, value)
        req.add_header("User-Agent", "riel/{}".format(VERSION))
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=timeout)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get("Location")
                if not loc:
                    raise EngineError(
                        "fetch: redirect without Location from {}".format(
                            _redact_url(current)))
                current, headers = _next_redirect(current, loc, headers)
                continue
            raise EngineError("fetch: HTTP {} for {}".format(
                exc.code, _redact_url(current)))
        except (urllib.error.URLError, OSError) as exc:
            raise EngineError("fetch: {} for {}".format(
                exc, _redact_url(current)))
    else:
        raise EngineError("fetch: too many redirects (last: {})".format(
            _redact_url(current)))
    try:
        want_len = resp.headers.get("Content-Length")
        want = int(want_len) if want_len is not None else None
    except ValueError:
        want = None
    chunks, total = [], 0
    try:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total > max_bytes:
                raise EngineError(
                    "fetch: body exceeds {} bytes — aborted".format(max_bytes))
            chunks.append(chunk)
    finally:
        resp.close()
    if want is not None and total != want:
        raise EngineError(
            "fetch: incomplete body from {} — Content-Length {} but got {} "
            "bytes".format(_redact_url(current), want, total))
    data = b"".join(chunks)
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256.strip().lower():
        raise EngineError("fetch: sha256 mismatch\n  want {}\n  got  {}"
                          .format(sha256.strip().lower(), digest))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise EngineError("fetch: the artifact is not valid UTF-8 Markdown; nothing written")
    _backup(output)
    _atomic_write(output, text, worktree)
    return data, digest


def _fetch_verb(args, out, err):
    headers = {}
    for raw in args.header or []:
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            raise EngineError(
                "bad --header {!r} (want 'Name: value')".format(raw))
        headers[name.strip()] = value.strip()
    target = args.output if os.path.isabs(args.output) \
        else os.path.join(args.worktree, args.output)
    paths = _worktree_paths(args.worktree)
    with _Locked(paths["lock"]):
        _confine(target, args.worktree)
        for canonical in (paths["run"], paths["shaping"]):
            if os.path.realpath(target) != os.path.realpath(canonical):
                continue
            if os.path.isfile(paths["run"]):
                current_metadata = _parse_metadata(_read_file(paths["run"]))
                if current_metadata.get("revision"):
                    raise EngineError(
                        "fetch refuses to replace {} while a run is active; "
                        "archive it or write elsewhere and rebase explicitly".format(
                            os.path.relpath(canonical, args.worktree)))
        data, digest = _secure_fetch(
            args.url, target, args.sha256, args.worktree,
            allow_http=args.allow_http, timeout=args.timeout,
            max_bytes=args.max_bytes, headers=headers)
    print("fetched {} bytes -> {} (sha256 {}) — materialized as a draft; "
          "activation is never automatic".format(
              len(data), os.path.relpath(target, args.worktree), digest),
          file=out)
    return 0


# ---------------------------------------------------------- templates ----

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _template_dirs(worktree):
    return [
        os.path.expanduser("~/.hermes/riel/templates"),
        os.path.join(worktree, RIEL_DIR, "templates"),
        os.path.join(PKG_ROOT, "templates"),
    ]


_PARAM_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _render_template(name, params, extra_dirs, strict, worktree):
    dirs = list(extra_dirs or []) + _template_dirs(worktree)
    path = None
    for d in dirs:
        candidate = os.path.join(d, name + ".md")
        if os.path.exists(candidate):
            path = candidate
            break
    if path is None:
        raise EngineError("no template for {!r}; searched: {}".format(
            name, ", ".join(dirs)))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    mapping = {}
    for raw in params or []:
        key, sep, value = raw.partition("=")
        if not sep or not key:
            raise EngineError("bad --param {!r} (want key=value)".format(raw))
        mapping[key] = value

    def repl(match):
        key = match.group(1)
        if key in mapping:
            return mapping[key]
        if strict:
            raise EngineError("missing --param {}=".format(key))
        return match.group(0)

    result = _PARAM_RE.sub(repl, text)
    return result, _PARAM_RE.findall(result)


# --------------------------------------------------------------- main ----

_NOTE_PARAMS = None


def _note_params():
    """`engine/params.py` beside this file — the one declaration of note's
    flags. Loaded by path so both the script and package routes find it."""
    global _NOTE_PARAMS
    if _NOTE_PARAMS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "params.py")
        spec = importlib.util.spec_from_file_location("riel_engine_params",
                                                      path)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise RuntimeError("engine/params.py is missing from the package")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _NOTE_PARAMS = module
    return _NOTE_PARAMS


def _add_fetch_flags(parser):
    parser.add_argument("url")
    parser.add_argument("--output", "-o", required=True,
                        help="destination path (written atomically; kind=out)")
    parser.add_argument("--sha256", required=True,
                        help="expected sha256 of the body (MANDATORY)")
    parser.add_argument("--header", action="append", default=[],
                        help="extra request header 'Name: value' (repeatable)")
    parser.add_argument("--allow-http", action="store_true",
                        help="permit plain http to any host (trusted "
                             "transport, e.g. a VPN)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="socket timeout in seconds (optional)")
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024,
                        help="abort if the body exceeds this many bytes "
                             "(optional; default 5MB)")


class _ArgumentParser(argparse.ArgumentParser):
    """Argparse variant that cannot divert errors or help to global streams."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._out = None
        self._err = None

    def _print_message(self, message, file=None):
        if message:
            print(message, end="", file=self._out or file or sys.stdout)

    def error(self, message):
        raise EngineError("invalid arguments: {}".format(message), code=2)


def build_parser(out=None, err=None):
    p = _ArgumentParser(prog="riel", description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument(
        "--worktree", default=None,
        help="directory whose .riel/ holds the state (default: the cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sh = sub.add_parser(
        "shape", help="validate .riel/shaping.md, render its template, "
                      "or fetch one")
    shsub = sh.add_subparsers(dest="cmd2")
    shv = shsub.add_parser("validate", help="validate a shaping file")
    shv.add_argument("path", nargs="?", default=None)
    shv.set_defaults(fn=cmd_shape, cmd2="validate")
    shn = shsub.add_parser("new", help="render the shaping template (stdout)")
    shn.add_argument("--param", action="append", default=[])
    shn.add_argument("--template-dir", action="append", default=None)
    shn.add_argument("--strict", action="store_true")
    shn.set_defaults(fn=cmd_shape, cmd2="new")
    shf = shsub.add_parser("fetch", help="fetch a shaping over https")
    _add_fetch_flags(shf)
    shf.set_defaults(fn=cmd_shape, cmd2="fetch")
    sh.set_defaults(fn=cmd_shape, cmd2="validate", path=None)

    r = sub.add_parser("run", help="work with .riel/run.md (riel-run/v1)")
    rsub = r.add_subparsers(dest="cmd2", required=True)
    rn = rsub.add_parser(
        "new", help="render the run template (stdout; an editor is the "
                    "writing path)")
    rn.add_argument("--template", default="run", choices=("run",),
                    help="the only Plan template (run)")
    rn.add_argument("--param", action="append", default=[])
    rn.add_argument("--template-dir", action="append", default=None)
    rn.add_argument("--strict", action="store_true")
    rn.set_defaults(fn=cmd_run, cmd2="new")
    rv = rsub.add_parser("validate", help="validate the draft or active run")
    rv.add_argument("file", nargs="?", default=None)
    rv.set_defaults(fn=cmd_run, cmd2="validate")
    ra = rsub.add_parser(
        "activate", help="freeze the plan, compute the hashes, open r1")
    ra.set_defaults(fn=cmd_run, cmd2="activate")
    rb = rsub.add_parser(
        "rebase", help="re-freeze hashes after a plan/shaping edit; "
                       "reserves old evidence")
    rb.set_defaults(fn=cmd_run, cmd2="rebase")
    rs = rsub.add_parser("status", help="concise JSON state + derivation")
    rs.set_defaults(fn=cmd_run, cmd2="status")
    rsl = rsub.add_parser("slice", help="emit a self-validating phase packet")
    rsl.add_argument("phase", help="phase node id (e.g. F1)")
    rsl.add_argument("--output", "-o", default=None)
    rsl.set_defaults(fn=cmd_run, cmd2="slice")
    rf = rsub.add_parser("fetch", help="fetch a run file over https")
    _add_fetch_flags(rf)
    rf.set_defaults(fn=cmd_run, cmd2="fetch")

    n = sub.add_parser("note", help="the ONLY writer of run state")
    params = _note_params()
    for param in params.NOTE_PARAMS:
        kwargs = {"help": param["help"]}
        if param["kind"] == "int":
            kwargs["type"] = int
        if param.get("repeat"):
            kwargs["action"] = "append"
            kwargs["default"] = []
        if param["name"] == "evidence":
            kwargs["dest"] = "evidence_ref"
        n.add_argument(param["flag"], **kwargs)
    n.set_defaults(fn=cmd_note)

    t = sub.add_parser("todo", help="the session-todo mirror (JSON)")
    t.set_defaults(fn=cmd_todo)

    cl = sub.add_parser(
        "clean", help="clear .riel/ state (flat backups, max 3 kept)")
    cl.add_argument("--all", action="store_true", help="also clean shaping.md")
    cl.add_argument("--purge", action="store_true",
                    help="remove without backing up")
    cl.set_defaults(fn=cmd_clean)

    ck = sub.add_parser(
        "check", help="dense markers + graph digest (+mmdc) as JSON")
    ck.add_argument("file")
    ck.add_argument("--mermaid", action="store_true",
                    help="also parse every mermaid block with mmdc")
    ck.set_defaults(fn=cmd_check)

    parsers = [p]
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            parsers.extend(action.choices.values())
    for parser in parsers:
        for child_action in parser._actions:
            if isinstance(child_action, argparse._SubParsersAction):
                parsers.extend(child_action.choices.values())
        parser._out, parser._err = out, err
    return p


# --------------------------------------------------------- in-process ----

def run_verb(argv, worktree=None, out=None, err=None):
    """Run one verb with per-call sinks, including parser failures and help."""
    captured = out is None and err is None
    out = out if out is not None else io.StringIO()
    err = err if err is not None else io.StringIO()
    try:
        args = build_parser(out=out, err=err).parse_args(argv)
        root = os.path.abspath(os.path.expanduser(
            args.worktree or worktree or os.getcwd()))
        if not os.path.isdir(root):
            raise EngineError("worktree is not a directory: {}".format(root))
        args.worktree = root
        for key in ("file", "path"):
            value = getattr(args, key, None)
            if isinstance(value, str) and value and not os.path.isabs(value):
                setattr(args, key, os.path.join(root, value))
        code = args.fn(args, out, err)
    except SystemExit as exc:  # argparse help/version, now bound to our sinks
        code = exc.code if isinstance(exc.code, int) else 0
    except EngineError as exc:
        print(str(exc), file=err)
        code = exc.code
    if captured:
        return code, out.getvalue(), err.getvalue()
    return code


def main(argv=None):
    # Explicit sinks (the CLI's own stdout/stderr): run_verb returns the code.
    return run_verb(argv if argv is not None else sys.argv[1:],
                    out=sys.stdout, err=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
