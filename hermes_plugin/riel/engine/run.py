"""The Riel v2 engine — one stdlib file behind the public verbs.

Public surface (nothing else exists; there is NO converter from riel v1):

    riel [--worktree DIR] shape [PATH] | shape new [--param k=v]
    riel [--worktree DIR] run new [--param k=v] [--strict]
    riel [--worktree DIR] run validate [FILE]
    riel [--worktree DIR] run activate
    riel [--worktree DIR] run rebase
    riel [--worktree DIR] run status
    riel [--worktree DIR] run slice PHASE
    riel [--worktree DIR] note [--gate G# ...] [--claim P# ...] --command CMD
                        --covering WHAT [--confidence N]
                        [--core "name -- fact"] [--core-slot N]
                        [--open Q --settled-by TEST] [--close N --evidence N]
    riel [--worktree DIR] todo
    riel [--worktree DIR] project [FILE] | project new | project status
    riel [--worktree DIR] run archive
    riel [--worktree DIR] clean [--archive]
    riel [--worktree DIR] check FILE [--mermaid]

State is ONE file, `.riel/run.md`, format `riel-run/v1`. It executes ONE
shaping from `.riel/shapings/<slug>.md` (`riel-shaping/v3`: one question, one
answer, a uid in its marker), optionally ordered by `.riel/project.md` (`riel-project/v1`),
whose progress is derived from the runs archived in `.riel/runs/`. The
Definition (the title plus eight sections, ending at `## DO NOT`) is authored by
hand —
`run new` only renders the template to stdout; an editor, a project system or a
copy-paste is the writing path. `run activate` freezes it: it computes
definition_sha256 over the Definition-before-Metadata (including the frozen Basis
copied from the bound shaping's referenced findings) and shaping_sha256 over that
shaping's bytes, records its path and uid, then appends Metadata + Execution
state + Core + Open + Evidence. `note` is the ONLY writer of that state. If the
Definition or the BOUND shaping changes underneath, note refuses as stale until
`run rebase` reserves the old evidence (retained, not counted) under a new
revision. `run archive` moves a finished run to `.riel/runs/<slug>.md` (never
pruned); `clean` wipes everything inside `.riel/`, archiving only when asked.

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
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

VERSION = "3.0.0"
RUN_FORMAT = "riel-run/v1"

RIEL_DIR = ".riel"
RUN_MD = "run.md"
PROJECT_MD = "project.md"
SHAPINGS_DIR = "shapings"
RUNS_DIR = "runs"
LOCK_NAME = ".run.lock"
SHAPING_FORMAT = "riel-shaping/v3"
SHAPING_ID_RE = re.compile(r"^shp_[0-9a-f]{8}$")
SHAPING_MARKER_RE = re.compile(
    r"^<!--\s*" + re.escape(SHAPING_FORMAT) + r"\s+id:(shp_[0-9a-f]{8})\s*-->\s*$", re.M)
# The section order. Open is LAST: it is the residue — what the shaping could
# not close after the answer, the evidence and the commission.
SHAPING_SECTIONS = ("Question", "Answer", "Findings", "Facts",
                    "Not wanted", "What we want", "Open")
ANSWER_SUPPORT_RE = re.compile(r"supported by\s+(F\d+)", re.I)
ANSWER_OWNER_RE = re.compile(r"decided by:\s*owner", re.I)
LEGACY_STATE_FILES = ("contract.md", "ledger.md")
MARKER_LINE = "<!-- {} -->".format(RUN_FORMAT)

# The Definition: the level-1 title plus these eight level-2 sections, in order.
# Activation appends five more (Metadata, Execution state, Core, Open,
# Evidence).
DEFINITION_TITLES = (
    "Objective", "Context", "Constraints", "Phases", "Deliverable", "DO NOT",
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
# Shared graph shape: nodes {id: (opener, label)}, edges [(src, label, dst)].
# A Contract's graph is parsed by contract_graph() from `## Phases`; graph_any()
# below serves project.md (`## Graph` with `- S#:` lists) and external files
# under `check`, where a first-mermaid fallback keeps riel_check's reach.

NODE_ANCHOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PHASE_ID_PATTERN = r"F\d+|W\d+"
PHASE_ID_RE = re.compile(r"^(?:" + PHASE_ID_PATTERN + r")$")
PROJECT_NODE_PATTERN = r"S\d+"
PROJECT_NODE_RE = re.compile(r"^(?:" + PROJECT_NODE_PATTERN + r")$")
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


def list_graph(body, phase_pattern=PHASE_ID_PATTERN):
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
            m = re.match(r"^(" + phase_pattern + r")\s*[:：]\s*(.+)$",
                         item.group(1))
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
    phase_re = re.compile(r"^(?:" + phase_pattern + r")$")
    phase_ids = [nid for nid in nodes if phase_re.match(nid)]
    for a, b in zip(phase_ids, phase_ids[1:]):
        outs = [v for u, _l, v in edges if u == a]
        edges.append(((outs[-1] if outs else a), "", b))
    return nodes, edges


def graph_any(text, strict_section=False, phase_pattern=PHASE_ID_PATTERN):
    """A project/external file's graph → (nodes, edges, register).

    NOT for Contracts: those parse through contract_graph() from `## Phases`.
    strict_section (project.md): ONLY `## Graph` counts. Otherwise (external
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
    nodes, edges = list_graph(body, phase_pattern)
    if nodes:
        return nodes, edges, "list"
    return {}, [], ""


# ------------------------------------------------------- phase outline ----
# The Contract's execution structure lives in `## Phases`: the general DAG in
# the preamble, then one `### F#: <title>` per phase carrying its own steps and
# its `#### Claims`, `#### Gates` and `#### Deliverable`. Phase membership is
# STRUCTURAL — a gate no longer names its phase in a text suffix.

PHASE_HEADING_RE = re.compile(
    r"^###\s+(" + PHASE_ID_PATTERN + r")\s*[:：]\s*(.+)$", re.M)
PHASE_SUBSECTIONS = ("Claims", "Gates", "Deliverable")


def phase_blocks(text):
    """[(id, title, body)] for each `### F#: <title>` under `## Phases`."""
    body = _section(text, "Phases")
    marks = list(PHASE_HEADING_RE.finditer(body))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out.append((m.group(1), m.group(2).strip(), body[m.end():end].strip()))
    return out


def phases_preamble(text):
    """The general-DAG area of `## Phases`, before the first phase heading."""
    body = _section(text, "Phases")
    m = PHASE_HEADING_RE.search(body)
    return (body[:m.start()] if m else body).strip()


def phase_steps_body(body):
    """A phase's step bullets: everything before its first `#### `."""
    return re.split(r"^####\s", body, maxsplit=1, flags=re.M)[0].strip()


def phase_sub(body, name):
    """Body of `#### <name>` inside one phase block."""
    m = re.search(r"^####\s+" + re.escape(name) + r"[^\n]*\n(.*?)"
                  r"(?=^####\s|^###\s|^##\s|\Z)", body, re.S | re.M)
    return m.group(1).strip() if m else ""


def _preamble_edges(pre):
    """`- F1 → F2 → F3` bullets in the preamble → linear phase edges."""
    edges = []
    for item in _bullets(pre):
        parts = [p.strip() for p in re.split(r"\s*(?:→|->|-->)\s*", item)]
        ids = [p for p in parts if PHASE_ID_RE.match(p)]
        edges += [(a, "", b) for a, b in zip(ids, ids[1:])]
    return edges


def contract_graph(text):
    """The Contract's two-level graph → (nodes, edges, register).

    Level 1 — the general DAG between phases: a mermaid block in the preamble,
    an arrow list, or the authored order of the `### F#` headings.
    Level 2 — each phase's step bullets, chained linearly and numbered PER
    PHASE (`F1S1`, `F1S2`, …) so inserting a step never renumbers another
    phase's anchors. Decisions and loops belong to the general DAG.
    """
    blocks = phase_blocks(text)
    if not blocks:
        return {}, [], ""
    nodes, edges, tails = {}, [], {}
    pre = phases_preamble(text)
    block = _first_mermaid(pre)
    register, general = "outline", []
    if block is not None:
        gn, ge = mermaid_graph(block)
        nodes.update(gn)
        general, register = ge, "mermaid"
    else:
        general = _preamble_edges(pre)
    order = []
    for pid, title, body in blocks:
        nodes[pid] = ("[", title)
        order.append(pid)
        last = None
        for n, item in enumerate(_bullets(phase_steps_body(body)), 1):
            sid = "{}S{}".format(pid, n)
            nodes[sid] = ("[", item)
            edges.append((pid if last is None else last, "", sid))
            last = sid
        tails[pid] = last or pid
    if not general:
        general = [(a, "", b) for a, b in zip(order, order[1:])]
    for u, lbl, v in general:
        edges.append((tails.get(u, u), lbl, v))
    return nodes, edges, register


def _anchor_target(text, name):
    """(body, items) for a `§` anchor: a `## Section`, or a phase's steps."""
    if PHASE_ID_RE.match(name):
        for pid, _title, body in phase_blocks(text):
            if pid == name:
                steps = phase_steps_body(body)
                return steps, _bullets(steps)
        return "", []
    body = _section(text, name)
    return body, _bullets(body)


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


def _split_definition(text):
    """(definition_text, state_text): the Definition is everything before `## Metadata`.

    The Definition is CANONICALIZED here (exactly one trailing newline) because the
    hash is computed over these bytes: the blank line the renderer adds before
    `## Metadata` must never count as a definition change.
    """
    m = re.search(r"^## Metadata\s*$", text, re.M)
    if m is None:
        return text.rstrip("\n") + "\n", ""
    return text[:m.start()].rstrip("\n") + "\n", text[m.start():]


def definition_sha256(definition_text):
    return hashlib.sha256(definition_text.encode("utf-8")).hexdigest()


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
    """[{id, text, anchor, phase}] from each phase's `#### Claims`."""
    out = []
    for pid, _title, body in phase_blocks(text):
        for item in _bullets(phase_sub(body, "Claims")):
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
                            "anchor": anchor, "phase": pid})
    return out


def _parse_gates(text):
    """[{id, label, phase}] from each phase's `#### Gates`.

    Membership is structural: the phase is the one whose block holds the gate.
    A leftover `— phase: F#` suffix is stripped and reported when it disagrees.
    """
    out = []
    for pid, _title, body in phase_blocks(text):
        for item in _bullets(phase_sub(body, "Gates")):
            m = re.match(r"^(G\d+)\s*[:：]\s*(.*)$", item)
            if not m:
                continue
            label, declared = m.group(2).strip(), ""
            cm = re.search(r"\s+—\s+phase:\s*(\S+)\s*$", label)
            if cm:
                declared = cm.group(1)
                label = label[:cm.start()].strip()
            out.append({"id": m.group(1), "label": label, "phase": pid,
                        "declared_phase": declared})
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

def _finding_dossiers(body):
    """[{id, head, lines}] from `### F<n>:` dossiers, in authored order.

    A dossier runs until the next `###` heading. `#### Diagram` (four hashes)
    stays INSIDE it, so a finding can carry its own diagram.
    """
    out, current = [], None
    for raw in _strip_comments(body).splitlines():
        stripped = raw.strip()
        m = re.match(r"^###\s+(F\d+)\s*[:：]\s*(.*)$", stripped)
        if m:
            current = {"id": m.group(1), "head": m.group(2).strip(), "lines": []}
            out.append(current)
        elif current is not None:
            if re.match(r"^#{1,3}\s", stripped):
                current = None
            else:
                current["lines"].append(raw)
    return out


def _source_confidence(lines):
    """(source, confidence) from a finding's own lines — never across findings."""
    source = confidence = ""
    for ln in lines:
        ms = re.search(r"—\s*source:\s*(.+)$", ln)
        if ms and not source:
            tail = ms.group(1)
            mc = re.search(r",\s*confidence\s*[:：]?\s*(\S+)", tail)
            if mc:
                confidence = mc.group(1).strip()
                tail = tail[:mc.start()]
            source = tail.strip().rstrip(",")
        if not confidence:
            mc = re.search(r"\bconfidence\s*[:：]?\s*(high|med|medium|low)\b", ln, re.I)
            if mc:
                confidence = mc.group(1)
    return source, confidence


def shaping_findings(text):
    """[{id, text, source, confidence}] from `## Findings` dossiers.

    `### F1: <claim>` — the heading is the citable one-line claim, the body is
    its support. The Basis freezes claim + source + confidence, never the body.
    """
    body = _section(text, "Findings")
    out, seen = [], set()
    for dossier in _finding_dossiers(body):
        fid = dossier["id"]
        if fid in seen:
            continue
        seen.add(fid)
        claim = re.split(r"\s+—\s*source:", dossier["head"])[0].strip()
        source, confidence = _source_confidence([dossier["head"]] + dossier["lines"])
        out.append({"id": fid, "text": claim.strip(" —").strip(),
                    "source": source, "confidence": confidence})
    return out


def shaping_id(text):
    """The shaping's stable uid (`shp_xxxxxxxx`) from its marker line, or ""."""
    m = SHAPING_MARKER_RE.search(text.split("\n## ", 1)[0])
    return m.group(1) if m else ""


def shaping_question(text):
    """The ONE question this shaping answers (first line of ## Question)."""
    return _first_line(_section(text, "Question"))


def shaping_answer(text):
    """The ONE line that answers the Question (v3 `## Answer`)."""
    return _first_line(_section(text, "Answer"))


def shaping_title(text):
    m = re.match(r"^#\s*Shaping:\s*(.+)$", text.lstrip(), re.M)
    return m.group(1).strip() if m else ""


def new_shaping_id():
    """A fresh uid. Riel mints it at RENDER time — it never authors a file."""
    return "shp_" + secrets.token_hex(4)


def slugify(name):
    """A filesystem-safe slug: ascii, lowercase, hyphenated, bounded."""
    folded = unicodedata.normalize("NFKD", str(name or ""))
    ascii_only = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:48].strip("-")
    return slug or "shaping"


def validate_shaping(text):
    """(issues, warnings) for one versioned shaping source.

    A shaping answers ONE question: that is the unit a run binds and a PR
    delivers. The ANSWER is a first-class line and the section order is fixed
    (Open last, because it is the residue). Only riel-shaping/v3 is read.
    """
    issues, warnings = [], []
    head = text.split("\n## ", 1)[0]
    if text.lstrip().startswith("---"):
        issues.append("frontmatter is not part of {}; use a marker line".format(
            SHAPING_FORMAT))
    if not shaping_id(text):
        issues.append(
            "missing <!-- {} id:shp_xxxxxxxx --> after the title".format(
                SHAPING_FORMAT))
    if not re.match(r"^#\s*Shaping:", text.lstrip()):
        issues.append("title must be `# Shaping: <name>`")

    # An unfilled skeleton is not research. Same guard as the Definition: a
    # shaping whose Facts or Open are still `{{…}}` must not back a run.
    left = sorted(set(re.findall(r"\{\{([^}]+)\}\}", _strip_comments(text))))
    if left:
        issues.append(
            "unfilled placeholder(s) in the shaping: {} — author them before "
            "binding a run to it".format(
                ", ".join("{{" + name + "}}" for name in left)))

    # ONE question, on ONE line.
    q_lines = [ln.strip() for ln in
               _strip_comments(_section(text, "Question")).splitlines()
               if ln.strip()]
    if not q_lines:
        issues.append("## Question is empty")
    elif len(q_lines) > 1:
        issues.append(
            "## Question must be ONE line — one shaping answers one question; "
            "split the rest into their own shapings")
    else:
        question = re.sub(r"^[-*]\s+", "", q_lines[0])
        if question.count("?") != 1:
            issues.append(
                "## Question must ask exactly ONE question (one '?'): {!r}".format(
                    question[:80]))

    # Findings: unique ids, each with a source.
    findings = shaping_findings(text)
    raw_ids = re.findall(r"^(?:[-*]|###)\s*(F\d+)\s*[:：]",
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

    # The ANSWER is mandatory, one line, and backed.
    a_lines = [ln.strip() for ln in
               _strip_comments(_section(text, "Answer")).splitlines()
               if ln.strip()]
    if not a_lines:
        issues.append("## Answer is empty — the Question must be answered")
    elif len(a_lines) > 1:
        issues.append("## Answer must be ONE line — the resolution, not an essay")
    else:
        answer = re.sub(r"^[-*]\s+", "", a_lines[0])
        if "?" in answer:
            issues.append("## Answer must not be a question (no '?')")
        cited = ANSWER_SUPPORT_RE.findall(answer)
        if not cited and not ANSWER_OWNER_RE.search(answer):
            issues.append(
                "## Answer needs evidence: '— supported by F#' or "
                "'— decided by: owner'")
        known = {f["id"] for f in findings}
        for fid in cited:
            if fid not in known:
                issues.append(
                    "## Answer cites {} which is not a finding".format(fid))

    # The seven sections, in order, Open last.
    lvl2 = [title.strip() for lvl, title in
            re.findall(r"^(#{1,2})\s+(.+)$", text, re.M) if lvl == "##"]
    pos = []
    for want in SHAPING_SECTIONS:
        for i, title in enumerate(lvl2):
            if title == want or title.startswith(want):
                pos.append(i)
                break
        else:
            issues.append("missing shaping section: {}".format(want))
    if pos != sorted(pos):
        issues.append(
            "shaping sections out of order — expected {}; Open goes last".format(
                " · ".join(SHAPING_SECTIONS)))
    return issues, warnings


# ------------------------------------------------------ file plumbing ----

def _worktree_paths(worktree):
    riel_dir = os.path.join(worktree, RIEL_DIR)
    return {
        "dir": riel_dir,
        "run": os.path.join(riel_dir, RUN_MD),
        "project": os.path.join(riel_dir, PROJECT_MD),
        "shapings": os.path.join(riel_dir, SHAPINGS_DIR),
        "runs": os.path.join(riel_dir, RUNS_DIR),
        "lock": os.path.join(riel_dir, LOCK_NAME),
    }


def _shaping_files(directory):
    """Every shaping in shapings/, sorted. Backups and symlinks are not shapings."""
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name.endswith(".bak.md"):
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path) and not os.path.islink(path):
            out.append(path)
    return out


def shapings_index(worktree):
    """[{path, rel, slug, id, question, findings, issues, warnings}] per shaping.

    The one place that reads the whole shapings/ directory: project validation,
    project status, uid uniqueness and the run's binding all consult this.
    """
    out = []
    for path in _shaping_files(_worktree_paths(worktree)["shapings"]):
        text = _read_file(path)
        issues, warnings = validate_shaping(text)
        out.append({
            "path": path,
            "rel": os.path.relpath(path, worktree),
            "slug": os.path.basename(path)[:-3],
            "id": shaping_id(text),
            "question": shaping_question(text),
            "findings": shaping_findings(text),
            "issues": issues,
            "warnings": warnings,
        })
    return out


def _shaping_declaration(definition_text):
    """The run's `### Shaping` declaration under ## Context: a path or a uid."""
    for item in _bullets(_subsection(definition_text, "Context", "Shaping")):
        m = re.match(r"^shaping:\s*(.+)$", item)
        value = (m.group(1) if m else item).strip().strip("`").strip()
        if value and not value.startswith("{{"):
            return value
    return ""


def _declare_shaping(definition_text, rel):
    """Write (or repoint) the `### Shaping` declaration inside ## Context."""
    block = "### Shaping\n- shaping: {}\n\n".format(rel)
    text = re.sub(r"### Shaping\n.*?(?=\n###\s|\n##\s|\Z)", "", definition_text,
                  flags=re.S | re.M)
    kw = re.search(r"### Context keywords\n.*?(?=\n###\s|\n##\s|\Z)",
                   text, re.S | re.M)
    if kw:
        return text[:kw.end()] + "\n" + block + text[kw.end():].lstrip("\n")
    ctx = re.search(r"^## Context[^\n]*\n", text, re.M)
    if ctx:
        return text[:ctx.end()] + "\n" + block + text[ctx.end():]
    raise EngineError("no ## Context section to declare the shaping into")


def _bound_shaping(worktree, definition_text=None, meta=None):
    """(rel, id, abs_path) of the shaping this run belongs to; ("", "", "") if none.

    Identity first: an activated run binds by uid, so renaming the file keeps
    the binding. The Definition's `### Shaping` declaration is the authoring path.
    However the file was found, its uid must identify ONE shaping in the
    directory.
    """
    meta = meta or {}
    want_id = str(meta.get("shaping_id") or "").strip()
    want_path = str(meta.get("shaping") or "").strip()
    if not want_id and not want_path and definition_text:
        decl = _shaping_declaration(definition_text)
        if SHAPING_ID_RE.match(decl):
            want_id = decl
        elif decl:
            want_path = decl
    rel = uid = abs_path = ""
    if want_id:
        hits = [s for s in shapings_index(worktree) if s["id"] == want_id]
        if hits:
            rel, uid, abs_path = hits[0]["rel"], hits[0]["id"], hits[0]["path"]
    if not rel and want_path:
        candidate = want_path if os.path.isabs(want_path) \
            else os.path.join(worktree, want_path)
        if os.path.isfile(candidate):
            rel = os.path.relpath(candidate, worktree)
            abs_path = candidate
            uid = shaping_id(_read_file(candidate))
        else:
            raise EngineError(
                "the bound shaping {} does not exist — fix the ### Shaping "
                "declaration or run rebase".format(want_path))
    if not rel:
        if want_id:
            raise EngineError(
                "no shaping with id {} in .riel/shapings/".format(want_id))
        return "", "", ""
    if uid:
        same = [s["rel"] for s in shapings_index(worktree) if s["id"] == uid]
        if len(same) > 1:
            raise EngineError(
                "shaping id {} is not unique ({}) — one id identifies one "
                "question".format(uid, ", ".join(same)))
    return rel, uid, abs_path


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


def load_state(worktree, require_active=False, require_exists=True, path=None):
    """Read + parse a run file → dict; clean EngineError on every refusal.

    `path` reads an ARCHIVED run (.riel/runs/<slug>.md) instead of the live
    one: that is how a project derives a shaping's progress from real evidence.
    """
    paths = _worktree_paths(worktree)
    run_path = path or paths["run"]
    _refuse_legacy(worktree)
    if not os.path.exists(run_path):
        if require_exists:
            raise EngineError(
                "no run state at {} — render one with `run new`, edit it, "
                "then `run activate`".format(run_path))
        return None
    _confine(run_path, worktree)
    text = _read_file(run_path)
    if not marker_present(text):
        raise EngineError(
            "{} is not a {} file (missing {} after the title)".format(
                run_path, RUN_FORMAT, MARKER_LINE))
    definition_text, _ = _split_definition(text)
    meta = _parse_metadata(text)
    active = bool(meta.get("revision"))
    if require_active and not active:
        raise EngineError(
            "run at {} is a draft — `run activate` first".format(run_path))
    graph_nodes, graph_edges, register = contract_graph(definition_text)
    shaping_hash = None
    if active and meta.get("shaping_sha256") not in (None, "none"):
        shaping_hash = meta["shaping_sha256"]
    st = {
        "path": run_path,
        "text": text,
        "definition_text": definition_text,
        "active": active,
        "meta": meta,
        "revision": meta.get("revision") if active else None,
        "definition_hash": meta.get("definition_sha256") if active else None,
        "shaping_hash": shaping_hash,
        "claims": _parse_claims(definition_text),
        "gates": _parse_gates(definition_text),
        "evidence": _parse_evidence(text),
        "core": _parse_core(text),
        "open": _parse_open(text),
        "basis": _parse_basis(definition_text),
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
    """The gates structurally inside a phase. There is no run-global fallback."""
    return [gate["id"] for gate in st["gates"]
            if gate.get("phase") == phase_id]


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

def _check_definition(text, nodes, edges, shaping_path, active, basis, basis_only=False):
    """(issues, warnings) shared by validate / activate / rebase / slice."""
    issues, warnings = [], []

    if not marker_present(text):
        issues.append(
            "missing the {} marker line after the title".format(MARKER_LINE))
    if not re.match(r"^#\s*Run:\s*\S", text.lstrip()):
        issues.append("title must be `# Run: <name>`")

    # An unfilled template is NOT an authored Contract. Every section being
    # non-empty is not authoring: `{{objective}}` is non-empty text, and without
    # this guard definition_sha256 freezes the skeleton as if it were a decision.
    left = sorted(set(re.findall(r"\{\{([^}]+)\}\}", _strip_comments(text))))
    if left:
        issues.append(
            "unfilled placeholder(s) in the Definition: {} — author them "
            "before activating".format(
                ", ".join("{{" + name + "}}" for name in left)))

    headings = [t.strip() for _lvl, t in
                re.findall(r"^(#{1,2})\s+(.+)$", text, re.M)]
    wanted = ["Run:"] + list(DEFINITION_TITLES)
    pos = []
    for w in wanted:
        for i, t in enumerate(headings):
            if t == w or t.startswith(w):
                pos.append(i)
                break
        else:
            issues.append("missing definition section: {}".format(w))
    if pos != sorted(pos):
        issues.append("definition sections out of order")

    if not _first_line(_section(text, "Objective")):
        issues.append("## Objective is empty")
    if not _bullets(_section(text, "Constraints")):
        issues.append("## Constraints has no items")
    if not _bullets(_section(text, "DO NOT")):
        issues.append("## DO NOT has no items (scope enforcement missing)")
    if not _first_line(_section(text, "Deliverable")):
        issues.append("## Deliverable is empty")

    # The flat pre-Phases Definition is refused, not read.
    for old in ("Claims", "Graph", "Gates"):
        if re.search(r"^##\s+" + old + r"\s*$", text, re.M):
            issues.append(
                "## {} is no longer part of the Contract — claims, gates and "
                "the execution DAG live inside ## Phases".format(old))

    blocks = phase_blocks(text)
    if not blocks:
        issues.append("## Phases has no `### F#: <title>` phase")
    for pid, title, body in blocks:
        if not title:
            issues.append("phase {} has no title".format(pid))
        if not _bullets(phase_steps_body(body)):
            issues.append("phase {} has no steps".format(pid))
        for sub in PHASE_SUBSECTIONS:
            if not _bullets(phase_sub(body, sub)):
                issues.append(
                    "phase {} has no #### {} items".format(pid, sub))

    claims = _parse_claims(text)
    if not claims:
        issues.append("no P# claims under the phases' #### Claims")
    seen = set()
    for c in claims:
        if c["id"] in seen:
            issues.append("duplicate claim id {}".format(c["id"]))
        seen.add(c["id"])

    gates = _parse_gates(text)
    if not gates:
        issues.append("no G# gates under the phases' #### Gates")
    gate_ids = {g["id"] for g in gates}
    if len(gate_ids) != len(gates):
        issues.append("duplicate gate id across phases")
    for g in gates:
        if not g["label"]:
            issues.append("gate {} has no label".format(g["id"]))
        if g.get("declared_phase") and g["declared_phase"] != g["phase"]:
            issues.append(
                "gate {} declares phase {} but lives in {} — membership is "
                "structural, drop the suffix".format(
                    g["id"], g["declared_phase"], g["phase"]))

    # graph conventions — parsed shapes and parsed edges only
    if not nodes:
        issues.append("no execution graph under ## Phases (a general DAG in "
                      "the preamble plus `### F#: <title>` phases)")
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
        blocks = re.findall(r"```mermaid\n(.*?)```", _section(text, "Phases"),
                            re.S)
        for block in blocks:
            if "<br" in block:
                issues.append("graph uses <br/> — mermaid v11 breaks on it")
            if any(ln.strip().startswith("style ")
                   for ln in block.splitlines()):
                issues.append(
                    "graph carries `style` — not a parsed-as-spec DAG")
        if graph_back_edges(edges) and not re.search(
                r"< *[0-9]|>= *[0-9]", _section(text, "Phases")):
            warnings.append(
                "graph has a loop but no counter guard (< 3 / >= 3)")
        issues.extend(mmdc_issues(blocks))

    # anchors
    node_ids = set(nodes)
    graph_section = _section(text, "Phases")
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
            body, items = _anchor_target(text, name)
            if not body:
                issues.append("{} anchor {} does not resolve — no such "
                              "section or phase".format(c["id"], c["anchor"]))
            elif idx is not None:
                if not 1 <= int(idx) <= len(items):
                    issues.append(
                        "{} anchor {} does not resolve — {} has {} "
                        "item(s)".format(c["id"], c["anchor"], name, len(items)))
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
    """The stale check: definition/shaping bytes must match the activated hashes."""
    current_definition = definition_sha256(st["definition_text"])
    if not st["definition_hash"]:
        raise EngineError(
            "stale state: the run has no definition_sha256 — it was not "
            "activated by this engine; re-author the Definition and activate "
            "again", code=3)
    if st["definition_hash"] != current_definition:
        raise EngineError(
            "stale state: the definition changed since {} — run `run rebase` "
            "(old evidence is reserved, not lost)".format(st["revision"]),
            code=3)
    current = None
    if os.path.isfile(shaping_path):
        current = hashlib.sha256(
            _read_file(shaping_path).encode("utf-8")).hexdigest()
    if st["shaping_hash"] != current:
        raise EngineError(
            "stale state: {} changed since {} — run `run rebase`".format(
                shaping_path or "the bound shaping", st["revision"]), code=3)


# ---------------------------------------------------------- rendering ----

def _render_state_sections(meta, core, open_qs, evidence, current_phase):
    lines = ["## Metadata", ""]
    for key in ("format", "revision", "activated", "definition_sha256",
                "shaping", "shaping_id", "shaping_sha256"):
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


def _build_basis(definition_text, findings, shaping_hash, shaping_rel="", shaping_uid=""):
    """Replace (or insert) the frozen `### Basis` inside `## Context`."""
    origin = shaping_rel or "the shaping"
    if shaping_uid:
        origin += " (id {})".format(shaping_uid)
    entries = ["### Basis",
               "<!-- Frozen from {} sha256 {}. Edit the shaping and run "
               "`run rebase` to refresh; the definition is otherwise frozen. -->"
               .format(origin, shaping_hash)]
    for f in findings:
        line = "- {}: {}".format(f["id"], f["text"])
        if f["source"]:
            line += " — source: {}".format(f["source"])
        if f["confidence"]:
            line += " — confidence: {}".format(f["confidence"])
        entries.append(line)
    block = "\n".join(entries) + "\n\n"
    text = re.sub(r"### Basis\n.*?(?=\n###\s|\n##\s|\Z)", "", definition_text,
                  flags=re.S | re.M)
    kw = re.search(r"### Context keywords\n.*?(?=\n###\s|\n##\s|\Z)",
                   text, re.S | re.M)
    if kw:
        return text[:kw.end()] + "\n" + block + text[kw.end():].lstrip("\n")
    ctx = re.search(r"^## Context[^\n]*\n", text, re.M)
    if ctx:
        return text[:ctx.end()] + "\n" + block + text[ctx.end():]
    raise EngineError("no ## Context section to freeze the Basis into")


def _referenced_finding_ids(definition_text):
    ids = []
    for c in _parse_claims(definition_text):
        m = FROZEN_RE.match(c["anchor"] or "")
        if m:
            ids.append("F{}".format(m.group(1)))
    return ids


# --------------------------------------------------------------- verbs ----

def cmd_shape(args, out, err):
    if args.cmd2 == "new":
        return _shape_new(args, out, err)
    return _shape_validate(args, out, err)


def _default_shaping_path(worktree):
    """The shaping `shape validate` answers for when no path is given.

    One file in shapings/ -> that one. Several -> the caller must choose.
    """
    paths = _worktree_paths(worktree)
    found = _shaping_files(paths["shapings"])
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise EngineError(
            "{} shapings in .riel/shapings/ — pass the file to validate "
            "({})".format(len(found), ", ".join(
                os.path.relpath(f, worktree) for f in found)))
    raise EngineError(
        "no shaping file in {} — write one (shape new renders the "
        "template) or pass a path".format(os.path.relpath(paths["shapings"], worktree)))


def _shape_validate(args, out, err):
    path = getattr(args, "path", None) or _default_shaping_path(args.worktree)
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
    # The uid is minted here, at RENDER time: the tool still writes nothing.
    # An explicit --param id=shp_xxxxxxxx wins (a project system may mint its own).
    params = ["id=" + new_shaping_id()] + list(args.param or [])
    text, leftover = _render_template("shaping", params,
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
        "archive": _run_archive,
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
    definition_text, _ = _split_definition(text)
    meta = _parse_metadata(text)
    active = bool(meta.get("revision"))
    nodes, edges, _reg = contract_graph(definition_text)
    basis = _parse_basis(definition_text)
    issues, warnings = [], []
    try:
        _rel, _sid, shaping_path = _bound_shaping(args.worktree, definition_text, meta)
    except EngineError as exc:
        shaping_path = ""
        issues.append(str(exc))
    definition_issues, definition_warnings = _check_definition(
        text, nodes, edges, shaping_path, active, basis,
        basis_only=bool(basis))
    issues += definition_issues
    warnings += definition_warnings
    if active:
        try:
            _validate_active_hashes({
                "definition_text": definition_text,
                "revision": meta.get("revision"),
                "definition_hash": meta.get("definition_sha256"),
                "shaping_hash": (None if meta.get("shaping_sha256") == "none"
                                 else meta.get("shaping_sha256")),
            }, shaping_path)
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


def _freeze_from_shaping(worktree, paths, definition_text, err, meta=None):
    """(definition, shaping_hash, findings, rel, uid) — or None after refusing.

    The run binds ONE shaping: its declaration (or its activated uid) resolves
    the file, the file is validated, and the referenced findings are frozen
    into the Basis. No shaping is allowed ONLY when no claim anchors into one.
    """
    rel, sid, abs_path = _bound_shaping(worktree, definition_text, meta)
    shaping_hash = "none"
    findings = []
    referenced = _referenced_finding_ids(definition_text)
    if rel:
        stext = _read_file(abs_path)
        s_issues, s_warns = validate_shaping(stext)
        for w in s_warns:
            print("WARN: shaping: {}".format(w), file=err)
        if s_issues:
            print("refusing — invalid {}:".format(rel), file=err)
            for issue in s_issues:
                print("  - " + issue, file=err)
            return None
        by_id = {f["id"]: f for f in shaping_findings(stext)}
        for fid in referenced:
            if fid not in by_id:
                print("refusing — a claim anchors {} which does not exist "
                      "in {}".format(fid, rel), file=err)
                return None
            findings.append(by_id[fid])
        shaping_hash = hashlib.sha256(stext.encode("utf-8")).hexdigest()
    elif referenced:
        print("refusing — claims anchor shaping findings ({}) but the run "
              "binds no shaping: declare one under ## Context as "
              "`### Shaping` / `- shaping: .riel/shapings/<slug>.md`".format(
                  ", ".join(referenced)), file=err)
        return None
    if findings:
        definition_text = _build_basis(definition_text, findings, shaping_hash, rel, sid)
    return definition_text, shaping_hash, findings, rel, sid


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
                "activates once; edit the definition and `run rebase` instead"
                .format(paths["run"], meta["revision"]))
        definition_text, _ = _split_definition(text)
        nodes, edges, _reg = contract_graph(definition_text)
        try:
            _rel, _sid, shaping_path = _bound_shaping(args.worktree, definition_text)
        except EngineError as exc:
            shaping_path = ""
            print("refusing activation — {}".format(exc), file=out)
            return 1
        issues, _warnings = _check_definition(
            text, nodes, edges, shaping_path, False, [])
        if issues:
            print("refusing activation — {} issue(s):".format(len(issues)),
                  file=out)
            for issue in issues:
                print("  - " + issue, file=out)
            return 1
        frozen = _freeze_from_shaping(args.worktree, paths, definition_text, err)
        if frozen is None:
            return 1
        definition_text, shaping_hash, _findings, shaping_rel, shaping_uid = frozen
        meta = {
            "format": RUN_FORMAT,
            "revision": "r1",
            "activated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "definition_sha256": definition_sha256(definition_text),
            "shaping_sha256": shaping_hash,
        }
        if shaping_rel:
            meta["shaping"] = shaping_rel
            meta["shaping_id"] = shaping_uid
        body = definition_text + "\n" + _render_state_sections(
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
        definition_text = st["definition_text"]
        nodes, edges, _reg = contract_graph(definition_text)
        try:
            _rel, _sid, shaping_path = _bound_shaping(
                args.worktree, definition_text, st["meta"])
        except EngineError as exc:
            shaping_path = ""
            print("refusing rebase — {}".format(exc), file=out)
            return 1
        issues, _w = _check_definition(definition_text, nodes, edges, shaping_path,
                                 False, [])
        if issues:
            print("refusing rebase — {} issue(s):".format(len(issues)),
                  file=out)
            for issue in issues:
                print("  - " + issue, file=out)
            return 1
        frozen = _freeze_from_shaping(args.worktree, paths, definition_text, err,
                                      meta=st["meta"])
        if frozen is None:
            return 1
        definition_text, shaping_hash, _findings, shaping_rel, shaping_uid = frozen
        new_definition_hash = definition_sha256(definition_text)
        if (new_definition_hash == st["definition_hash"]
                and shaping_hash == (st["shaping_hash"] or "none")):
            print("nothing to rebase — definition and shaping match {}".format(
                old_revision), file=out)
            return 0
        rev_n = int(old_revision[1:]) + 1
        meta = dict(st["meta"])
        meta.update({
            "revision": "r{}".format(rev_n),
            "definition_sha256": new_definition_hash,
            "shaping_sha256": shaping_hash,
            "activated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if shaping_rel:
            meta["shaping"] = shaping_rel
            meta["shaping_id"] = shaping_uid
        else:
            meta.pop("shaping", None)
            meta.pop("shaping_id", None)
        # Old evidence is RETAINED verbatim but no longer counted: its
        # revision no longer matches the current one.
        body = definition_text + "\n" + _render_state_sections(
            meta, st["core"], st["open"], st["evidence"], st["current_phase"])
        _backup(paths["run"])
        _atomic_write(paths["run"], body, args.worktree)
    print("rebased to r{} — {} evidence record(s) reserved (retained, not "
          "counted)".format(rev_n, len(st["evidence"])), file=out)
    return 0


def _run_status(args, out, err):
    st = load_state(args.worktree)
    assert st is not None  # require_exists=True rejects the missing run above
    shaping_rel, shaping_uid, shaping_path = _bound_shaping(
        args.worktree, st["definition_text"], st["meta"])
    if st["active"]:
        _validate_active_hashes(st, shaping_path)
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
        "shaping": ({"path": shaping_rel, "id": shaping_uid,
                     "sha256": st["shaping_hash"]} if shaping_rel else None),
        "todos": todo_projection(st),
    }
    print(json.dumps(payload, ensure_ascii=False), file=out)
    return 0


def _run_slice(args, out, err):
    """Emit ONE phase as a self-contained Contract packet.

    The phase's block travels verbatim (steps, Claims, Gates, Deliverable) with
    the global sections and the frozen Basis, so its anchors resolve exactly as
    in the parent and the child never reads the parent's shaping file.
    """
    paths = _worktree_paths(args.worktree)
    st = load_state(args.worktree, require_active=True)
    definition = st["definition_text"]
    by_id = {pid: (title, body) for pid, title, body in phase_blocks(definition)}
    if not by_id:
        raise EngineError("the run has no phases to slice")
    phase = args.phase
    if phase not in by_id:
        raise EngineError(
            "no phase {!r} under ## Phases (phases: {})".format(
                phase, ", ".join(by_id) or "none"))
    title, body = by_id[phase]
    title_m = re.match(r"^#\s*Run:\s*(.+)$", definition, re.M)
    parent_title = title_m.group(1).strip() if title_m else "(task)"

    parts = ["# Run: {} — {}".format(parent_title, title or phase),
             MARKER_LINE, ""]
    for name in ("Objective", "Context", "Constraints"):
        parts.append("## " + name)
        if name == "Context":
            parts.append("")
            for sub in ("Basis", "Why"):
                content = _subsection(definition, "Context", sub)
                if content:
                    parts += ["### " + sub, content, ""]
            kws = context_keywords(definition)
            if kws:
                parts.append("### Context keywords")
                parts += ["- {}{}".format(
                    k["term"],
                    " → {}".format(k["source"]) if k["source"] else "")
                    for k in kws]
                parts.append("")
        else:
            content = _section(definition, name)
            parts += ["", content, ""] if content else [""]
    parts += ["## Phases", "", "### {}: {}".format(phase, title), "", body, ""]
    for name in ("Deliverable", "DO NOT"):
        parts += ["## " + name, "", _section(definition, name), ""]
    packet = "\n".join(parts).rstrip("\n") + "\n"

    # self-validating: the packet passes the same validator as a draft
    nodes2, edges2, _r = contract_graph(packet)
    issues, _w = _check_definition(packet, nodes2, edges2, "", False,
                                   _parse_basis(packet), basis_only=True)
    if issues:
        raise EngineError("slice of {} is not self-validating: {}".format(
            phase, "; ".join(issues)))
    if args.output:
        target = args.output if os.path.isabs(args.output) \
            else os.path.join(args.worktree, args.output)
        _atomic_write(target, packet, args.worktree)
    print(packet, end="", file=out)
    return 0


def _note_evidence(st, args):
    """Run --command in the worktree; capture the REAL exit code + snippet.

    There is no way to self-supply an exit code: none exists as a flag.
    """
    definition_claims = {c["id"] for c in st["claims"]}
    definition_gates = {g["id"] for g in st["gates"]}
    for g in args.gate:
        if g not in definition_gates:
            raise EngineError("unknown gate {!r} — ## Gates has {}".format(
                g, ", ".join(sorted(definition_gates)) or "no gates"))
    for c in args.claim:
        if c not in definition_claims:
            raise EngineError("unknown claim {!r} — ## Claims has {}".format(
                c, ", ".join(sorted(definition_claims)) or "no claims"))
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
        _rel, _sid, shaping_path = _bound_shaping(
            args.worktree, st["definition_text"], st["meta"])
        _validate_active_hashes(st, shaping_path)
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
        body = st["definition_text"] + "\n" + _render_state_sections(
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
    """Project Definition+Evidence as Hermes checks with their step subchecks.

    A phase is a check; each gate mapped to it is a nested check; each work
    step hangs under the gate that verifies it (or directly under the phase
    when the phase has no explicit gate). Only passing current-revision
    evidence completes a check. A global gate is a top-level check.
    """
    nodes, edges = st["nodes"], st["edges"]
    phase_ids = _phase_order(nodes)
    objective = _first_line(_section(st["definition_text"], "Objective"))
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
                "id": "riel-step-" + step_id,
                "content": "{}: {}".format(step_id, nodes[step_id][1] or step_id),
                "status": status,
                "parent": step_parent,
            })
    # A gate with no phase is a run-global check: keep it at contract level.
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


# ------------------------------------------------------------- project ----
# A project is an ORDERING of shapings, not another execution engine: each node
# is one shaping (one question), each shaping runs once and delivers one PR.
# Progress is DERIVED from the runs' own evidence — the live run plus the
# archived ones in .riel/runs/. Nothing here writes state.

PROJECT_FORMAT = "riel-project/v1"
PROJECT_MARKER = "<!-- {} -->".format(PROJECT_FORMAT)


def parse_project(text, worktree):
    """(nodes, edges, bindings, issues, warnings) for one project source.

    bindings maps each node id to its shaping entry (path, uid, slug, question).
    A node label is the shaping's path, its uid or its slug.
    """
    issues, warnings = [], []
    head = text.split("\n## ", 1)[0]
    if PROJECT_MARKER not in head:
        issues.append("missing {} after the title".format(PROJECT_MARKER))
    if not re.match(r"^#\s*Project:", text.lstrip()):
        issues.append("title must be `# Project: <name>`")
    if not _first_line(_section(text, "Objective")):
        issues.append("## Objective is empty")
    nodes, edges, _register = graph_any(
        text, strict_section=True, phase_pattern=PROJECT_NODE_PATTERN)
    if not nodes:
        issues.append(
            "no shaping graph under ## Graph (a list of "
            "`- S1: .riel/shapings/<slug>.md` or a mermaid flowchart)")
    index = shapings_index(worktree)
    by_rel = {s["rel"]: s for s in index}
    by_uid = {s["id"]: s for s in index if s["id"]}
    by_slug = {s["slug"]: s for s in index}
    bindings, seen = {}, {}
    for nid, (_shape, label) in nodes.items():
        if not PROJECT_NODE_RE.match(nid):
            issues.append(
                "node {} is not a shaping node (project ids are S1, S2, …)"
                .format(nid))
            continue
        ref = (label or "").strip().strip("`").strip()
        # A label may be the worktree-relative path, a bare filename, the uid
        # or the slug — a project system writes whichever it has.
        stem = os.path.basename(ref)[:-3] if ref.endswith(".md") else ref
        entry = (by_uid.get(ref) or by_rel.get(ref) or by_slug.get(ref)
                 or by_slug.get(stem))
        if entry is None:
            issues.append(
                "node {} references {!r} — no such shaping in .riel/shapings/"
                .format(nid, ref[:60]))
            continue
        for issue in entry["issues"]:
            issues.append("{} ({}): {}".format(nid, entry["rel"], issue))
        for warning in entry["warnings"]:
            warnings.append("{} ({}): {}".format(nid, entry["rel"], warning))
        if entry["rel"] in seen:
            issues.append(
                "{} and {} bind the same shaping {} — one shaping is one run "
                "and one PR".format(seen[entry["rel"]], nid, entry["rel"]))
        seen[entry["rel"]] = nid
        bindings[nid] = entry
    for u, _lbl, v in edges:
        if u not in nodes or v not in nodes:
            issues.append("edge {} --> {} names an unknown node".format(u, v))
    if graph_back_edges(edges):
        issues.append(
            "the project graph has a cycle — a project orders shapings, "
            "it does not loop")
    return nodes, edges, bindings, issues, warnings


def _project_order(nodes, edges):
    """Node ids in dependency order, authored order breaking ties (Kahn)."""
    indeg = {nid: 0 for nid in nodes}
    adj = {nid: [] for nid in nodes}
    for u, _lbl, v in edges:
        if u in indeg and v in indeg and u != v:
            adj[u].append(v)
            indeg[v] += 1
    ready = [nid for nid in nodes if indeg[nid] == 0]
    order = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=list(nodes).index)
    return order


def project_derive(worktree, text):
    """The project's state, derived from the runs' evidence — never declared."""
    nodes, edges, bindings, issues, warnings = parse_project(text, worktree)
    if issues:
        return None, issues, warnings
    paths = _worktree_paths(worktree)
    preds = {nid: set() for nid in nodes}
    for u, _lbl, v in edges:
        if u in preds and v in preds and u != v:
            preds[v].add(u)
    live, live_rel = None, ""
    if os.path.isfile(paths["run"]):
        try:
            live = load_state(worktree)
            live_rel, _uid, _p = _bound_shaping(
                worktree, live["definition_text"], live["meta"])
        except EngineError:
            live, live_rel = None, ""
    order = _project_order(nodes, edges)
    rows, done_ids = {}, set()
    for nid in order:
        entry = bindings.get(nid)
        if entry is None:
            continue
        archived = os.path.join(paths["runs"], entry["slug"] + ".md")
        proof, proof_rel = None, ""
        if os.path.isfile(archived):
            try:
                proof = load_state(worktree, path=archived)
                proof_rel = os.path.relpath(archived, worktree)
            except EngineError:
                proof = None
        is_done = bool(proof and proof["done"])
        is_live = bool(live_rel) and live_rel == entry["rel"]
        if is_done:
            status = "done"
            done_ids.add(nid)
        elif is_live:
            status = "active"
        elif not preds[nid] <= done_ids:
            status = "blocked"
        else:
            status = "pending"
        rows[nid] = {
            "shaping": entry["rel"], "id": entry["id"], "slug": entry["slug"],
            "question": entry["question"], "status": status,
            "run": proof_rel or (os.path.relpath(paths["run"], worktree)
                                 if is_live else ""),
            "revision": (proof or live or {}).get("revision") if (is_done or is_live) else None,
        }
    nxt = next((nid for nid in order
                if rows.get(nid, {}).get("status") == "pending"), None)
    payload = {
        "format": PROJECT_FORMAT,
        "project": _project_title(text),
        "objective": _first_line(_section(text, "Objective")),
        "order": order,
        "nodes": rows,
        "next": nxt,
        "done": bool(rows) and all(r["status"] == "done" for r in rows.values()),
        "shapings": len(rows),
    }
    return payload, [], warnings


def _project_title(text):
    m = re.match(r"^#\s*Project:\s*(.+)$", text.lstrip(), re.M)
    return m.group(1).strip() if m else ""


def _project_path(args):
    return getattr(args, "file", None) or _worktree_paths(args.worktree)["project"]


def cmd_project(args, out, err):
    if args.cmd2 == "new":
        text, leftover = _render_template("project", args.param,
                                          args.template_dir, args.strict,
                                          args.worktree)
        for name in sorted(set(leftover)):
            print("note: unfilled placeholder {{{{{}}}}}".format(name), file=err)
        print(text, end="", file=out)
        return 0
    path = _project_path(args)
    if not os.path.isfile(path):
        raise EngineError(
            "no project file at {} — `project new` renders the template; an "
            "editor writes the file".format(path))
    text = _read_file(path)
    if args.cmd2 == "status":
        payload, issues, warnings = project_derive(args.worktree, text)
        for w in warnings:
            print("WARN: {}".format(w), file=err)
        if payload is None:
            print("INVALID project {}:".format(path), file=out)
            for issue in issues:
                print("  - " + issue, file=out)
            return 1
        print(json.dumps(payload, ensure_ascii=False), file=out)
        return 0
    _nodes, _edges, _bindings, issues, warnings = parse_project(text, args.worktree)
    for w in warnings:
        print("WARN: {}".format(w), file=err)
    if issues:
        print("INVALID project {}:".format(path), file=out)
        for issue in issues:
            print("  - " + issue, file=out)
        return 1
    print("valid project: {} ({} shaping(s))".format(path, len(_nodes)), file=out)
    return 0


# -------------------------------------------------------------- clean ----

def _archive_root(worktree):
    """Where an opt-in clean archive lands: OUTSIDE .riel/, which clean wipes."""
    real = os.path.realpath(worktree)
    tag = "{}-{}".format(os.path.basename(real) or "worktree",
                         hashlib.sha256(real.encode("utf-8")).hexdigest()[:8])
    return os.path.join(os.path.expanduser("~/.hermes/riel/archive"), tag)


def _copy_verified(src_dir, dest_dir):
    """Copy every file under src_dir to dest_dir, verifying sha256 per file.

    Nothing is removed until every byte is confirmed at the destination.
    Symlinks are not followed (clean unlinks them, it never reads through).
    """
    copied = []
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in sorted(files):
            src = os.path.join(root, name)
            if os.path.islink(src):
                continue
            rel = os.path.relpath(src, src_dir)
            dst = os.path.join(dest_dir, rel)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(src, dst)
            with open(src, "rb") as fh:
                want = hashlib.sha256(fh.read()).hexdigest()
            with open(dst, "rb") as fh:
                got = hashlib.sha256(fh.read()).hexdigest()
            if want != got:
                raise EngineError(
                    "archive verification failed for {} — nothing was removed"
                    .format(rel))
            copied.append(rel)
    return copied


def cmd_clean(args, out, err):
    """Remove EVERYTHING inside .riel/. Archiving is opt-in, never the default.

    run.md, project.md, shapings/, runs/, v1 state
    and every backup go. The lock file stays (it is coordination, not state,
    and unlinking a held flock would let two writers in). Without --archive
    there is no way back: .riel/ is gitignored local state.
    """
    paths = _worktree_paths(args.worktree)
    riel_dir = paths["dir"]
    if not os.path.isdir(riel_dir):
        print("nothing to clean", file=out)
        return 0
    copied, archive_dest = [], ""
    with _Locked(paths["lock"]):
        entries = [e for e in sorted(os.listdir(riel_dir)) if e != LOCK_NAME]
        if not entries:
            print("nothing to clean", file=out)
            return 0
        if args.archive:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archive_dest = os.path.join(_archive_root(args.worktree), stamp)
            n = 1
            while os.path.exists(archive_dest):
                archive_dest = os.path.join(_archive_root(args.worktree),
                                            "{}-{}".format(stamp, n))
                n += 1
            copied = _copy_verified(riel_dir, archive_dest)
        removed = []
        for name in entries:
            path = os.path.join(riel_dir, name)
            if os.path.islink(path):
                os.unlink(path)          # removing a link never follows it
            else:
                _confine(path, args.worktree)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)
            removed.append(name)
    if archive_dest:
        print("cleaned {} entry(ies) from .riel/ — archived {} file(s) to {}"
              .format(len(removed), len(copied), archive_dest), file=out)
        print("restore: cp -R '{}/.' '{}'".format(archive_dest, riel_dir), file=out)
    else:
        print("cleaned {} entry(ies) from .riel/ — no archive (ask for "
              "archive=true to keep a verified copy)".format(len(removed)), file=out)
    return 0


def _run_archive(args, out, err):
    """Move the active run to .riel/runs/<slug>.md — the project's per-shaping proof.

    Never pruned: project status derives each shaping's progress from these
    files, so deleting one would silently reopen a finished track.
    """
    paths = _worktree_paths(args.worktree)
    with _Locked(paths["lock"]):
        st = load_state(args.worktree, require_active=True)
        rel, _uid, _spath = _bound_shaping(args.worktree, st["definition_text"], st["meta"])
        if rel:
            slug = os.path.basename(rel)[:-3]
        else:
            m = re.match(r"^#\s*Run:\s*(.+)$", st["definition_text"], re.M)
            slug = slugify(m.group(1) if m else "run")
        target = os.path.join(paths["runs"], slug + ".md")
        rel_target = os.path.relpath(target, args.worktree)
        if os.path.exists(target):
            raise EngineError(
                "{} already exists — one shaping archives one run; rename the "
                "old file or keep working the live run".format(rel_target))
        text = st["text"]
        _atomic_write(target, text, args.worktree)
        if _read_file(target) != text:
            os.unlink(target)
            raise EngineError("archive verification failed — the run was left in place")
        os.unlink(paths["run"])
    suffix = "" if st["done"] else " (run is NOT done — its shaping stays pending)"
    print("archived .riel/run.md -> {}{}".format(rel_target, suffix), file=out)
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
        "shape", help="validate a shaping file or render its template")
    shsub = sh.add_subparsers(dest="cmd2")
    shv = shsub.add_parser("validate", help="validate a shaping file")
    shv.add_argument("path", nargs="?", default=None)
    shv.set_defaults(fn=cmd_shape, cmd2="validate")
    shn = shsub.add_parser("new", help="render the shaping template (stdout)")
    shn.add_argument("--param", action="append", default=[])
    shn.add_argument("--template-dir", action="append", default=None)
    shn.add_argument("--strict", action="store_true")
    shn.set_defaults(fn=cmd_shape, cmd2="new")
    sh.set_defaults(fn=cmd_shape, cmd2="validate", path=None)

    r = sub.add_parser("run", help="work with .riel/run.md (riel-run/v1)")
    rsub = r.add_subparsers(dest="cmd2", required=True)
    rn = rsub.add_parser(
        "new", help="render the run template (stdout; an editor is the "
                    "writing path)")
    rn.add_argument("--template", default="run", choices=("run",),
                    help="the only contract template (run)")
    rn.add_argument("--param", action="append", default=[])
    rn.add_argument("--template-dir", action="append", default=None)
    rn.add_argument("--strict", action="store_true")
    rn.set_defaults(fn=cmd_run, cmd2="new")
    rv = rsub.add_parser("validate", help="validate the draft or active run")
    rv.add_argument("file", nargs="?", default=None)
    rv.set_defaults(fn=cmd_run, cmd2="validate")
    ra = rsub.add_parser(
        "activate", help="freeze the definition, compute the hashes, open r1")
    ra.set_defaults(fn=cmd_run, cmd2="activate")
    rb = rsub.add_parser(
        "rebase", help="re-freeze hashes after a definition/shaping edit; "
                       "reserves old evidence")
    rb.set_defaults(fn=cmd_run, cmd2="rebase")
    rs = rsub.add_parser("status", help="concise JSON state + derivation")
    rs.set_defaults(fn=cmd_run, cmd2="status")
    rsl = rsub.add_parser("slice", help="emit a self-validating phase packet")
    rsl.add_argument("phase", help="phase node id (e.g. F1)")
    rsl.add_argument("--output", "-o", default=None)
    rsl.set_defaults(fn=cmd_run, cmd2="slice")
    rar = rsub.add_parser(
        "archive", help="move the run to .riel/runs/<slug>.md (never pruned)")
    rar.set_defaults(fn=cmd_run, cmd2="archive")

    pj = sub.add_parser(
        "project", help="the ordering of shapings (.riel/project.md)")
    pjsub = pj.add_subparsers(dest="cmd2")
    pjv = pjsub.add_parser("validate", help="validate a project file")
    pjv.add_argument("file", nargs="?", default=None)
    pjv.set_defaults(fn=cmd_project, cmd2="validate")
    pjn = pjsub.add_parser("new", help="render the project template (stdout)")
    pjn.add_argument("--param", action="append", default=[])
    pjn.add_argument("--template-dir", action="append", default=None)
    pjn.add_argument("--strict", action="store_true")
    pjn.set_defaults(fn=cmd_project, cmd2="new")
    pjs = pjsub.add_parser("status", help="derived progress from the runs' evidence")
    pjs.add_argument("file", nargs="?", default=None)
    pjs.set_defaults(fn=cmd_project, cmd2="status")
    pj.set_defaults(fn=cmd_project, cmd2="validate", file=None)

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
        "clean", help="remove EVERYTHING inside .riel/ (archiving is opt-in)")
    cl.add_argument("--archive", action="store_true",
                    help="copy .riel/ outside the worktree and verify every "
                         "sha256 BEFORE removing anything")
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
