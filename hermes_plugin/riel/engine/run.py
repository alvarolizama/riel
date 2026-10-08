#!/usr/bin/env python3
"""The engine behind Riel's tools — one stdlib file, no user surface.

Every subcommand below is reached through a TOOL (`riel_note`, `riel_contract`,
`riel_seam`, …); nothing here is typed into a shell, and no flag travels as
data. The tools pass named parameters, this file owns the formats and decides
nothing semantic.
Usage:
    note    [--goal G] [--next N] [--core "name — fact"]
                    [--core-slot N] [--claim C --verify-with CMD]
                    [--check WHAT --by CMD --covering SCOPE [--confidence N]]
                    [--open Q --settled-by TEST]
                    [--close N --check WHAT --by CMD [--covering SCOPE]]
                    [--from-contract [PATH]]   # seed from .riel/contract.md
    seam
    resume
    todo
    context [--contract PATH] [-o OUT]   # keywords de contexto (JSON)
    clean   [--all] [--purge]            # limpia .riel/ con backup plano
    ship    FILE...
    digest  FILE [-o OUT]
    mermaid FILE...                              # parsea cada bloque con mmdc
    anchor  [P#] [--contract PATH] [--shaping PATH]  # claim + su región
    shaping validate [PATH]              # valida .riel/shaping.md (Spec 7)
    shaping new [-o PATH] [--force] [--param k=v ...]
    contract new [--type T] [--param k=v ...] [--list]
    contract validate FILE
    contract digest FILE [-o OUT]
    contract slice  FILE [--phase F#] [-o OUT]
    fetch   URL -o FILE [--sha256 H] [--header 'Name: v'] [--allow-http] [--timeout S] [--max-bytes N]
"""
import argparse
import hashlib
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

VERSION = "1.7.0"
LEDGER_DIR = ".riel"
LEDGER_PATH = os.path.join(LEDGER_DIR, "ledger.md")
CONTRACT_PATH = os.path.join(LEDGER_DIR, "contract.md")
SHAPING_PATH = os.path.join(LEDGER_DIR, "shaping.md")
VERIFY_CMD = os.environ.get("RIEL_MMDC", "mmdc")
# A wedged mermaid-cli must not wedge the caller: every mmdc call is bounded.
MMDC_TIMEOUT = float(os.environ.get("RIEL_MMDC_TIMEOUT", "20"))

DENSE_RE = re.compile(r"[✓?]\d+|↔|⇒|⊕|λ|Σ")


# ---------------------------------------------------------------- ledger ----

DEFAULT_TEMPLATE = """# Riel ledger

## Goal
{goal}

{source_section}{phase_section}## Claims
{claims}

## Core
{core}

## Verified
{verified}

## Open
{open}

## Next
{next}
"""


def read_ledger(path):
    """Parse .riel/ledger.md into a dict of sections. Empty strings -> []."""
    out = {
        "goal": "", "source": "", "phase": "", "claims": [], "core": [],
        "verified": [], "open": [], "next": "",
    }
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return out
    cur = None
    headers = {
        "## Goal": "goal", "## Source": "source", "## Phase": "phase",
        "## Claims": "claims", "## Core": "core", "## Verified": "verified",
        "## Open": "open", "## Next": "next",
    }
    for line in text.splitlines():
        if line.strip() in headers:
            cur = headers[line.strip()]
        elif line.startswith("#"):
            cur = None
        elif cur in ("goal", "source", "phase", "next"):
            if line.strip():
                if out[cur]:
                    out[cur] += "\n"
                out[cur] += line
        elif cur in ("claims", "core", "verified", "open"):
            if line.strip().startswith("- "):
                out[cur].append(line.strip()[2:])
    # "<empty>" is a rendering placeholder, not data (write_ledger re-adds it)
    for key in ("goal", "next"):
        if out[key] == "<empty>":
            out[key] = ""
    return out


def _backup_before_write(path):
    """Best-effort backup of an existing file before the engine overwrites it.

    Same flat convention as `clean` — `name-<ts>.bak.md` beside the original,
    never a subdirectory — so one recovery story covers both. A ledger is the
    only state that cannot be re-derived: a concurrent writer clobbering it
    must always leave the previous version reachable. Failure is SILENT: a
    backup that blocks the write is worse than no backup (same rule as the
    gate).
    """
    try:
        if not os.path.isfile(path):
            return
        directory = os.path.dirname(path) or "."
        base = os.path.basename(path)
        if base.endswith(".md"):
            base = base[:-len(".md")]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(directory, "{}-{}.bak.md".format(base, stamp))
        n = 1
        while os.path.exists(backup):
            backup = os.path.join(directory, "{}-{}-{}.bak.md".format(base, stamp, n))
            n += 1
        shutil.copy2(path, backup)
    except OSError:
        pass


def write_ledger(path, st):
    source_section = (
        "## Source\n{}\n\n".format(st["source"]) if st["source"] else ""
    )
    phase_section = (
        "## Phase\n{}\n\n".format(st["phase"]) if st["phase"] else ""
    )
    body = DEFAULT_TEMPLATE.format(
        goal=st["goal"] or "<empty>",
        source_section=source_section,
        phase_section=phase_section,
        claims="\n".join("- " + c for c in st["claims"]) or "<none>",
        core="\n".join("- " + c for c in st["core"]) or "<none>",
        verified="\n".join("- " + c for c in st["verified"]) or "<none>",
        open="\n".join("- " + q for q in st["open"]) or "<none>",
        next=st["next"] or "<empty>",
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def entry_number(prefix, seq):
    escaped = re.escape(prefix)
    nums = [
        int(m.group(1))
        for entry in seq
        for m in re.finditer(r"{}(\d+)".format(escaped), entry)
    ]
    return max(nums, default=0) + 1


def _section(text, name):
    """Body of '## <name>' up to the next '## ' heading (or EOF)."""
    m = re.search(
        r"^##\s+" + re.escape(name) + r"[^\n]*\n(.*?)(?=^##\s|\Z)",
        text, re.S | re.M,
    )
    return m.group(1).strip() if m else ""


def _first_paragraph(body):
    """First non-empty paragraph of a section, collapsed to one line."""
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if para:
            return " ".join(l.strip() for l in para.splitlines() if l.strip())
    return ""


def _subsection(text, section, sub):
    """Body of '### <sub>' inside '## <section>' (up to the next ###/## heading)."""
    body = _section(text, section)
    m = re.search(
        r"^###\s+" + re.escape(sub) + r"[^\n]*\n(.*?)(?=^###\s|^##\s|\Z)",
        body, re.S | re.M,
    )
    return m.group(1).strip() if m else ""


def _sentence_count(body):
    """Sentences in a section body: comments stripped, lines joined.

    Best-effort — a wrapped single sentence counts as one (fixtures wrap),
    several paragraphs count as multi. Used for the Objective one-sentence
    WARN, never as a hard gate.
    """
    text = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    paras = [p for p in (re.sub(r"\s+", " ", chunk).strip()
                         for chunk in re.split(r"\n\s*\n", text)) if p]
    if not paras:
        return 0
    if len(paras) > 1:
        return len(paras) + 1  # more than one paragraph: already multi
    parts = [s for s in re.split(r"(?<=[.!?])\s+", paras[0]) if s.strip()]
    return max(len(parts), 1)


def context_keywords(text):
    """Context-fetch keywords from '### Context keywords' inside '## Context'.

    One bullet per term, with an optional source hint after an arrow
    (`- login flow → dran`). Unfilled `{{placeholders}}` and comments are
    skipped, so an untouched template yields no keywords instead of junk.
    """
    body = _subsection(text, "Context", "Context keywords")
    found = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        m = re.match(r"^[-*]\s+(.+)$", line)
        if not m:
            continue
        term, _, source = m.group(1).partition("→")
        term = term.strip().strip("`").strip()
        if not term or term.startswith("{{"):
            continue
        found.append({"term": term, "source": source.strip().strip("`").lower()})
    return found


# ------------------------------------------------- anchors / shaping ----

CLAUSE_RE = re.compile(r"\s+—\s+")
CLAIM_LINE_RE = re.compile(r"^-+\s*(P\d+)\s*:?\s*(.*)$")
SECTION_ANCHOR_RE = re.compile(r"^§\s*([^#]+?)\s*(?:#(\d+))?$")
SHAPING_ANCHOR_RE = re.compile(r"^shaping:F(\d+)$", re.I)
NODE_ANCHOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SHAPING_SECTIONS = [
    "Question", "Findings", "Facts", "Alternatives bounced", "Open", "Verdict",
]


def claim_anchors(text):
    """[{id, claim, verify_with, anchor}] from '## Pre-registered claims'.

    One claim per LINE (the rule the seed already follows), parsed by em-dash
    CLAUSES: the anchor is the line's LAST clause (`— anchor: …`), so a claim
    whose prose merely MENTIONS the syntax (``— anchor:` ``) is not mistaken
    for one. Because the anchor rides the claim's own line, `contract slice`
    copies it verbatim into a child packet — provenance without new plumbing.
    """
    out = []
    for raw in _section(text, "Pre-registered claims").splitlines():
        line = raw.strip()
        m = CLAIM_LINE_RE.match(line)
        if not m:
            continue
        cid, rest = m.group(1), m.group(2)
        clauses = [c.strip() for c in CLAUSE_RE.split(rest) if c.strip()]
        anchor, verify, prose = "", "", []
        for i, clause in enumerate(clauses):
            low = clause.lower()
            if low.startswith("anchor:") and i == len(clauses) - 1:
                anchor = clause[len("anchor:"):].strip().strip("`")
            elif low.startswith("verify with:"):
                verify = clause[len("verify with:"):].strip().strip("`")
            else:
                prose.append(clause)
        out.append({"id": cid, "claim": " — ".join(prose).strip(),
                    "verify_with": verify, "anchor": anchor})
    return out


def _bullets(body):
    """List items of a section body, in order (bullets or numbered)."""
    items = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", line)
        if m:
            items.append(m.group(1).strip())
    return items


def shaping_findings(path):
    """{n: text} for every F# line of a shaping file ({} when unreadable)."""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    found = {}
    for raw in _section(text, "Findings").splitlines():
        m = re.match(r"^-+\s*F(\d+)\b[:\s]*(.*)$", raw.strip())
        if m:
            found[int(m.group(1))] = m.group(2).strip()
    return found


def resolve_anchor(anchor, text, graph_nodes=None, shaping_path=None):
    """Resolve one claim anchor against a contract (and its graph).

    Returns (kind, detail): kind in {'section', 'node', 'shaping', 'unknown'};
    detail is the excerpt when the anchor resolved, None when it did not.
    Forms: `§<Section>[#<n>]`, `<NodeId>`, `shaping:F<n>`.
    """
    if not anchor:
        return "none", None
    m = SECTION_ANCHOR_RE.match(anchor)
    if m:
        name, idx = m.group(1).strip(), m.group(2)
        body = _section(text, name)
        if not body:
            return "section", None
        if idx is None:
            return "section", body
        items = _bullets(body)
        n = int(idx)
        if 1 <= n <= len(items):
            return "section", items[n - 1]
        return "section", None
    m = SHAPING_ANCHOR_RE.match(anchor)
    if m:
        return "shaping", shaping_findings(shaping_path).get(int(m.group(1)))
    if NODE_ANCHOR_RE.match(anchor):
        if graph_nodes is None or anchor not in graph_nodes:
            return "node", None
        return "node", graph_nodes[anchor][1]
    return "unknown", None


def _excerpt(body, limit=4):
    """The lines of a resolved region, trimmed for a seam's glance."""
    lines = [l.strip() for l in body.splitlines()
             if l.strip() and not l.strip().startswith("<!--")]
    out = ["| " + l for l in lines[:limit]]
    if len(lines) > limit:
        out.append("| …")
    return out


def seed_from_contract(path):
    """Read a contract.md -> (fields, warnings).

    Best-effort: Goal <- Objective, Claims <- P#, Phase <- first F#/W#
    node, Next <- the graph's entry node (no incoming edge). Returns
    (None, [...]) when the file is missing.
    """
    fields = {"goal": "", "phase": "", "claims": [], "next": ""}
    warnings = []
    if not os.path.exists(path):
        return None, ["no contract found at {}".format(path)]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    goal = _first_paragraph(_section(text, "Objective"))
    if goal:
        fields["goal"] = goal
    else:
        warnings.append("no ## Objective found")

    for line in _section(text, "Pre-registered claims").splitlines():
        s = line.strip()
        if re.match(r"^-?\s*P\d+", s):
            fields["claims"].append(re.sub(r"^-\s*", "", s))
    if not fields["claims"]:
        warnings.append("no P# claims found")

    block = _graph_block(text)
    if block:
        nodes, edges = mermaid_graph(block)
        backs = set(graph_back_edges(edges))
        incoming = {v for u, l, v in edges if (u, l, v) not in backs}
        for nid, (_shape, label) in nodes.items():
            if nid not in incoming:
                fields["next"] = label
                break
        for nid, (_shape, label) in nodes.items():
            if re.match(r"^[FW]\d+$", nid):
                fields["phase"] = label
                break
        if not fields["next"]:
            warnings.append("graph has no entry node")
    else:
        warnings.append("no ## Execution graph (mermaid) found")
    return fields, warnings


def cmd_note(args):
    st = read_ledger(args.ledger)

    if args.from_contract is not None:
        fields, warns = seed_from_contract(args.from_contract)
        if fields is None:
            print(warns[0], file=sys.stderr)
            return 2
        for w in warns:
            print("seed: " + w, file=sys.stderr)
        for key in ("goal", "phase", "next"):
            if fields[key] and not st[key]:
                st[key] = fields[key]
        for c in fields["claims"]:
            if c not in st["claims"]:
                st["claims"].append(c)

    fresh = not st["goal"] and not st["verified"] and not st["next"]

    if args.goal is not None:
        st["goal"] = args.goal
    if args.next is not None:
        st["next"] = args.next
    if args.source is not None:
        st["source"] = args.source
    if args.phase is not None:
        st["phase"] = args.phase

    if args.claim is not None:
        verifier = args.verify_with or "<unspecified>"
        pid = "P{}".format(entry_number("P", st["claims"]))
        st["claims"].append("{}: {} — verify with: {}".format(pid, args.claim, verifier))

    if args.core is not None:
        name, _, fact = args.core.partition(" — ")
        if not fact:
            print("core entry must look like 'name — defining fact'", file=sys.stderr)
            return 2
        slot = args.core_slot
        if slot is not None:
            if not 0 <= slot < len(st["core"]):
                print("no such core slot: {}".format(slot), file=sys.stderr)
                return 2
            st["core"][slot] = args.core
        else:
            if len(st["core"]) >= 2:
                print(
                    "Core is full (2/2). Use --core-slot to swap one.",
                    file=sys.stderr,
                )
                return 2
            st["core"].append(args.core)

    if args.check is not None:
        if not args.by:
            print("--check requires --by (the verifier)", file=sys.stderr)
            return 2
        nid = "✓{:02d}".format(entry_number("✓", st["verified"]))
        covering = args.covering or "<unspecified>"
        entry = "{} {} — verified by: {}, covering {}".format(
            nid, args.check, args.by, covering
        )
        if args.confidence is not None:
            entry += ", confidence {}/20".format(args.confidence)
        st["verified"].append(entry)

    if args.open is not None:
        if not args.settled_by:
            print("--open requires --settled-by", file=sys.stderr)
            return 2
        qid = "?{:02d}".format(entry_number("?", st["open"]))
        st["open"].append(
            "{} {} — settled by: {}".format(qid, args.open, args.settled_by)
        )

    if args.close is not None:
        idx = None
        needle = "?{:02d}".format(args.close)
        for i, q in enumerate(st["open"]):
            if q.startswith(needle):
                idx = i
                break
        if idx is None:
            print("no such open question: {}".format(needle), file=sys.stderr)
            return 2
        if args.check is None:
            print(
                "--close requires --check (the checkpoint that settled "
                "{}); a question is closed against a checkpoint, never "
                "dropped silently".format(needle),
                file=sys.stderr,
            )
            return 2
        st["open"].pop(idx)

    _backup_before_write(args.ledger)
    write_ledger(args.ledger, st)
    print_ledger(st)
    if fresh and args.goal is None and args.next is None:
        # user opened with note but supplied nothing — remind how to open
        print(
            "\n(ledger was empty; use --goal G --next N to open it)",
            file=sys.stderr,
        )
    return 0


def print_ledger(st):
    source_line = "Source: {}\n".format(st["source"]) if st["source"] else ""
    phase_line = "Phase: {}\n".format(st["phase"]) if st["phase"] else ""
    print(
        "Mode: loop\n" + source_line + phase_line +
        "Goal: {}\n".format(st["goal"] or "<empty>") +
        "Claims ({}):\n".format(len(st["claims"])) +
        "\n".join("  - " + c for c in st["claims"]) + ("\n" if st["claims"] else "") +
        "Core ({}):\n".format(len(st["core"])) +
        "\n".join("  - " + c for c in st["core"]) + ("\n" if st["core"] else "") +
        "Verified ({}):\n".format(len(st["verified"])) +
        "\n".join("  - " + c for c in st["verified"]) + ("\n" if st["verified"] else "") +
        "Open ({}):\n".format(len(st["open"])) +
        "\n".join("  - " + q for q in st["open"]) + ("\n" if st["open"] else "") +
        "Next: {}".format(st["next"] or "<empty>")
    )


def cmd_seam(args):
    st = read_ledger(args.ledger)
    if not st["goal"]:
        print("no ledger found at {}; call riel_note(goal=…, next=…) first".format(
            args.ledger), file=sys.stderr)
        return 1
    print_ledger(st)
    n_verified = len(st["verified"])
    if n_verified == 0:
        print("\n[!] No ✓NN yet — remember to append immediately when a gate passes.")
    if len(st["core"]) > 2:
        print("\n[!] Core has {} live items; re-park to at most 2.".format(len(st["core"])))
    if st["next"] == "":
        print("\n[!] Next is empty — the ledger stops being state. Fill it.")
    anchored = []
    if os.path.isfile(CONTRACT_PATH):
        with open(CONTRACT_PATH, encoding="utf-8") as fh:
            anchored = [c for c in claim_anchors(fh.read()) if c["anchor"]]
    if anchored:
        print("\n[anchor] {} of the claims carry an anchor — `riel_seam(anchors=true)` "
              "re-reads each one beside its region.".format(len(anchored)))
    return 0


def cmd_resume(args):
    st = read_ledger(args.ledger)
    if not st["goal"]:
        print("no ledger found at {}".format(args.ledger), file=sys.stderr)
        return 1
    print("=" * 60)
    print("RIEL RESUME — restore state after gap/compaction, in order")
    print("=" * 60)
    print("\n[1/4] Ledger (every ✓NN matters, not just the last):\n")
    print_ledger(st)
    print(
        "\n[2/4] Failure invariants — re-check before acting:\n"
        "  1. ✓NN declared but never written\n"
        "  2. called verified without coverage\n"
        "  3. Next changed without work changing (churn)\n"
        "  4. critical ✓NN re-verified without variation\n"
        "  5. Goal ≠ what is being executed\n"
        "  6. Open grows without anything settled\n"
        "  7. confidence always the same value → broken scale\n"
        "  8. monitor never reports → unplugged\n"
        "  9. cannot restate Goal in your own words\n"
        " 10. last ✓NN took 3+ failed attempts → context contaminated"
    )
    print(
        "\n[3/4] Mode gate: is `loop` still correct? (fast/full/loop)\n"
        "\n[4/4] Restate the mode (inner register or ledger line), then set\n"
        "      `Next` = the first action back.",
    )
    return 0


# ----------------------------------------------------------------- todo ----

def outerize(text):
    """Dense-register entry -> outer-register prefix (✓01 -> DONE 01)."""
    return re.sub(
        r"([✓?])(\d+)",
        lambda m: ("DONE " if m.group(1) == "✓" else "OPEN ") + m.group(2),
        text,
    )


def _phase_order(nodes, edges):
    """Phase ids (F#/W#) in authored order — the plan's order, not a topo sort."""
    return [nid for nid in nodes if re.match(r"^[FW]\d+$", nid)]


def _phase_steps(nodes, edges, phase_id):
    """Step node ids of a phase, in authored order.

    A step is a member of the phase's subgraph that is not the phase itself,
    not a gate (`G#`) or another phase, and not a shape milestone
    (START/END/DONE) — those are not work.
    """
    sub = _phase_subgraph(nodes, edges, phase_id)
    steps = []
    for member in nodes:                      # authored order, not a set
        if member not in sub or member == phase_id:
            continue
        if re.match(r"^[FWG]\d+$", member):
            continue
        if member.upper() in ("END", "START", "DONE"):
            continue
        if not (nodes.get(member, ("", ""))[1] or "").strip():
            continue
        steps.append(member)
    return steps


def _label_matches(label, needle):
    label = (label or "").strip()
    return bool(label) and (label in needle or needle in label)


def _phase_of_next(nodes, edges, next_text):
    """Best-effort: which phase does the ledger's Next step belong to?"""
    needle = (next_text or "").strip()
    if not needle:
        return None
    for nid in _phase_order(nodes, edges):
        if _label_matches(nodes.get(nid, ("", ""))[1], needle):
            return nid
        for member in _phase_steps(nodes, edges, nid):
            if _label_matches(nodes.get(member, ("", ""))[1], needle):
                return nid
    return None


def _contract_goal(text):
    """The plan's goal: the contract's `## Objective`, first paragraph."""
    return _first_paragraph(_section(text, "Objective"))


def contract_to_todo_items(text, st):
    """Phase and step items from the contract's DAG (Spec 6).

    The todo IS the plan: phases are rows, steps are nested subtasks
    (`parent` = the phase). The ledger only decides statuses — a phase whose
    gate has a ✓ is completed; the active phase (the one owning the Next)
    carries the current step as `in_progress`, its earlier steps completed and
    the rest pending. No ledger fact (Next, claim, open, ✓) becomes a row;
    those are served by `riel_state`.
    """
    items = []
    block = _graph_block(text)
    if not block:
        return items
    nodes, edges = mermaid_graph(block)
    if not nodes:
        return items

    phase_ids = _phase_order(nodes, edges)
    active = _phase_of_next(nodes, edges, st.get("next") or "")
    if not active and st.get("phase"):
        # fall back: match the ledger's Phase text against node labels
        for nid in phase_ids:
            if _label_matches(nodes.get(nid, ("", ""))[1], st["phase"].strip()):
                active = nid
                break
    verified_count = len(st.get("verified") or [])
    if not active and (st.get("next") or "").strip() and verified_count < len(phase_ids):
        # a Next that matches no label: the plan's cursor is the first phase
        # still without its gate ✓ — best-effort, so the mirror keeps exactly
        # one in_progress instead of going malformed
        active = phase_ids[verified_count]

    # the current step: the step the Next points at (label match), else the
    # first step of the active phase
    current_step = None
    if active:
        steps = _phase_steps(nodes, edges, active)
        needle = (st.get("next") or "").strip()
        for member in steps:
            if _label_matches(nodes.get(member, ("", ""))[1], needle):
                current_step = member
                break
        if current_step is None and steps:
            current_step = steps[0]

    for idx, nid in enumerate(phase_ids):
        label = nodes[nid][1]
        steps = _phase_steps(nodes, edges, nid)
        completed = (idx + 1) <= verified_count and active != nid
        current_pos = (
            steps.index(current_step)
            if (active == nid and current_step in steps) else -1
        )
        # a phase with no steps cannot carry in_progress on a step, so the row
        # itself does (the single-in_progress rule still holds)
        phase_status = "completed" if completed else "pending"
        if active == nid and not steps:
            phase_status = "in_progress"
        items.append({
            "id": "phase-{}".format(nid),
            "content": "PHASE {}: {}".format(nid, label),
            "status": phase_status,
            "parent": "goal",
        })
        for pos, member in enumerate(steps):
            if completed:
                step_status = "completed"
            elif active == nid:
                if pos == current_pos:
                    step_status = "in_progress"
                elif 0 <= pos < current_pos:
                    step_status = "completed"
                else:
                    step_status = "pending"
            else:
                step_status = "pending"
            items.append({
                "id": "step-{}-{}".format(nid, member),
                "content": nodes[member][1],
                "status": step_status,
                "parent": "phase-{}".format(nid),
            })
    return items


def ledger_to_todo(st, contract_text=None):
    """Derive the session-todo mirror from the plan (Spec 6).

    The todo is the PLAN: the goal (the contract's Objective) as the root, the
    contract's phases as rows and each phase's steps as nested subtasks. The
    ledger only decides statuses (`contract_to_todo_items`). The ledger's own
    facts — Next, claims, opens, ✓ — are NOT rows here; `riel_state`
    serves them to the chip and the gate. Without a contract the todo degrades
    to goal + the ledger's single Phase row.
    """
    items = []

    def add(iid, content, status, parent=None):
        item = {"id": iid, "content": content, "status": status}
        if parent:
            item["parent"] = parent
        items.append(item)

    goal = _contract_goal(contract_text) if contract_text else ""
    if not goal:
        goal = st["goal"] or ""
    add("goal", "GOAL: {}".format(goal or "<empty>"), "pending")

    if contract_text:
        items.extend(contract_to_todo_items(contract_text, st))
        if (st.get("next") or "").strip() and not any(
                i["status"] == "in_progress" for i in items):
            # every phase is gated but the ledger still has a Next: the
            # done-check is what remains — the goal carries in_progress
            items[0]["status"] = "in_progress"
    elif st["phase"]:
        # no contract: the ledger's Phase row is the plan's only row
        add("phase", "PHASE: {}".format(st["phase"]), "in_progress", "goal")
    return items


def ledger_to_status(st):
    """The ledger's facts as the item list the chip and the gate fold (Spec 6).

    This is the ledger mirror the plugin consumes — goal, phase, next, open
    questions, claims and verified checkpoints — kept separate from the plan
    (`riel_todo`). Same item shape, so the consumers keep one fold.
    """
    items = []

    def add(iid, content, status, parent=None):
        item = {"id": iid, "content": content, "status": status}
        if parent:
            item["parent"] = parent
        items.append(item)

    add("goal", "GOAL: {}".format(st["goal"] or "<empty>"), "pending")
    if st["phase"]:
        add("phase", "PHASE: {}".format(st["phase"]), "pending", "goal")
    if st["next"]:
        add("next", "NEXT: {}".format(st["next"]), "in_progress", "goal")
    for n, q in enumerate(st["open"], 1):
        add("open-{}".format(n), outerize(q), "pending", "goal")
    for n, c in enumerate(st["claims"], 1):
        add("claim-{}".format(n), "CLAIM: {}".format(c), "pending", "goal")
    for n, v in enumerate(st["verified"], 1):
        add("done-{}".format(n), outerize(v), "completed", "goal")
    return items


def cmd_todo(args):
    st = read_ledger(args.ledger)
    if not st["goal"] and not st["verified"] and not st["next"]:
        print("no ledger found at {}; call riel_note(goal=…, next=…) first".format(
            args.ledger), file=sys.stderr)
        return 1
    # Spec 6: the todo is the plan — the contract's phases and steps
    contract_text = None
    contract_path = os.path.join(os.path.dirname(args.ledger) or ".", "contract.md")
    if os.path.isfile(contract_path):
        try:
            with open(contract_path, encoding="utf-8") as fh:
                contract_text = fh.read()
        except OSError:
            contract_text = None
    items = ledger_to_todo(st, contract_text=contract_text)
    print(json.dumps(items, indent=2, ensure_ascii=False))
    if not any(i["status"] == "in_progress" for i in items):
        print(
            "[!] no in_progress item in the mirror — the Next points at no "
            "step; fix the ledger, not the todo.",
            file=sys.stderr,
        )
    return 0


def cmd_status(args):
    """Print the ledger's own facts — the mirror the chip and the gate fold."""
    st = read_ledger(args.ledger)
    if not st["goal"] and not st["verified"] and not st["next"]:
        print("no ledger found at {}; call riel_note(goal=…, next=…) first".format(
            args.ledger), file=sys.stderr)
        return 1
    print(json.dumps(ledger_to_status(st), indent=2, ensure_ascii=False))
    return 0


def cmd_context(args):
    """Emit the contract's context-fetch keywords as JSON.

    The keywords are the contract's index into memory (agent memory, DRAN): the
    agent or the Hermes plugin reads this instead of re-parsing the contract.
    """
    path = args.contract
    if not os.path.exists(path):
        print("no contract at {}; write the contract first".format(path),
              file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    payload = {"contract": path, "keywords": context_keywords(text)}
    out = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)
    return 0


def cmd_clean(args):
    """Clear the worktree's .riel/ state before starting a new task.

    Backs up each file as a flat, timestamped sibling INSIDE .riel/ (never a
    subdirectory), then removes the originals. `--all` also cleans
    contract.md; `--purge` removes without backing up. Idempotent: with
    nothing to clean it exits 0 with a message. The agent asks the user
    first (backup / purge / keep the existing ledger) — clean never decides.
    """
    targets = [LEDGER_PATH]
    if args.all:
        targets.extend([CONTRACT_PATH, SHAPING_PATH])

    present = [p for p in targets if os.path.isfile(p)]
    if not present:
        print("nothing to clean in {} (no {})".format(
            LEDGER_DIR, ", ".join(targets)))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path in present:
        if not args.purge:
            base = os.path.basename(path)[:-len(".md")]
            backup = os.path.join(
                LEDGER_DIR, "{}-{}.bak.md".format(base, stamp))
            # a second clean within the same second must not clobber
            n = 1
            while os.path.exists(backup):
                backup = os.path.join(
                    LEDGER_DIR, "{}-{}-{}.bak.md".format(base, stamp, n))
                n += 1
            shutil.copy2(path, backup)
            os.remove(path)
            print("backed up {} -> {}".format(path, backup))
        else:
            os.remove(path)
            print("purged {}".format(path))
    return 0


def cmd_shaping_validate(args):
    """Validate a .riel/shaping.md against Spec 7.

    Errors: a missing section, an empty Question, a Findings section with no F#
    line. WARNs (never fatal): a finding without source or confidence, an
    alternative without a verdict, an open question without its settling test,
    a Verdict with no Objective line, and a contract claim anchored to a
    finding this shaping does not have.
    """
    path = args.file or SHAPING_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        print("no shaping found at {}".format(path), file=sys.stderr)
        return 1

    issues, warnings = [], []
    titles = [t.strip() for _lvl, t in re.findall(r"^(#{1,2})\s+(.+)$", text, re.M)]
    for name in SHAPING_SECTIONS:
        if not any(t.startswith(name) for t in titles):
            issues.append("missing section: {!r}".format(name))
    positions = []
    for name in SHAPING_SECTIONS:
        for i, t in enumerate(titles):
            if t.startswith(name):
                positions.append(i)
                break
    if positions != sorted(positions):
        issues.append("sections out of order; expected: "
                      + " -> ".join(SHAPING_SECTIONS))

    if not _first_paragraph(_section(text, "Question")):
        issues.append("## Question is empty — no decision to close")

    findings = shaping_findings(path)
    if not findings:
        issues.append("## Findings has no F# line — a shaping without a "
                      "finding is a guess, not research")
    for n in sorted(findings):
        body = findings[n]
        if "source:" not in body:
            warnings.append("F{} has no 'source:' — an unsourced finding is a "
                            "hypothesis".format(n))
        if "confidence" not in body:
            warnings.append("F{} has no confidence (high|med|low)".format(n))

    for i, item in enumerate(_bullets(_section(text, "Alternatives bounced")), 1):
        if "verdict:" not in item:
            warnings.append("A{} has no 'verdict:' (kept|discarded)".format(i))
    for i, item in enumerate(_bullets(_section(text, "Open")), 1):
        if "settled by:" not in item:
            warnings.append("Q{} has no 'settled by:' — name the cheapest test "
                            "that would settle it".format(i))

    verdict = _section(text, "Verdict")
    if not _first_paragraph(verdict):
        issues.append("## Verdict is empty — the contract has nothing to seed from")
    elif "We need" not in verdict and "Necesitamos" not in verdict:
        warnings.append("## Verdict has no Objective line ('We need …')")

    contract = args.contract or CONTRACT_PATH
    if os.path.isfile(contract):
        with open(contract, encoding="utf-8") as fh:
            ctext = fh.read()
        for claim in claim_anchors(ctext):
            m = SHAPING_ANCHOR_RE.match(claim["anchor"] or "")
            if m and int(m.group(1)) not in findings:
                warnings.append(
                    "{} anchors shaping:F{} — this shaping has no such finding"
                    .format(claim["id"], m.group(1)))

    for warning in warnings:
        print("WARN: {}".format(warning), file=sys.stderr)
    if issues:
        print("INVALID shaping {}:".format(path))
        for issue in issues:
            print("  - " + issue)
        return 1
    print("valid: {}".format(path))
    return 0


def cmd_shaping_new(args):
    """Instantiate the shaping skeleton — never over an existing shaping."""
    typename = args.type or "shaping"
    template_path = find_template(typename, args.template_dir)
    if not template_path:
        print("no template for type {!r}; searched: {}".format(
            typename, ", ".join(args.template_dir or DEFAULT_TEMPLATE_DIRS)),
            file=sys.stderr)
        return 2
    with open(template_path, encoding="utf-8") as fh:
        text = fh.read()
    params = dict(p.split("=", 1) for p in args.param)
    try:
        result = render_template(text, params, strict=args.strict)
    except KeyError as exc:
        print(exc.args[0] if exc.args else str(exc), file=sys.stderr)
        return 2
    if args.output == "-":
        print(result)
        return 0
    out = args.output or SHAPING_PATH
    if os.path.exists(out) and not args.force:
        print("{} already exists — a shaping is research, not a template drop; "
              "pass --force to overwrite".format(out), file=sys.stderr)
        return 3
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _backup_before_write(out)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(result if result.endswith("\n") else result + "\n")
    print("wrote {}".format(out))
    leftover = _PARAM_RE.findall(result)
    if leftover:
        print("note: {} placeholder(s) left — fill with patch/edit: {}".format(
            len(set(leftover)), ", ".join(sorted(set(leftover))[:5])))
    return 0


def cmd_anchor(args):
    """Print each claim beside the contract region that supports it.

    The seam's own re-read surface: `— anchor:` names a section, a graph node
    or a shaping finding, and this resolves it, so a claim's support can be
    re-read without re-reading the whole contract.
    """
    contract = args.contract
    if not os.path.isfile(contract):
        print("no contract found at {} — nothing to anchor".format(contract),
              file=sys.stderr)
        return 1
    with open(contract, encoding="utf-8") as fh:
        text = fh.read()
    claims = claim_anchors(text)
    if not claims:
        print("no P# claims in {}".format(contract), file=sys.stderr)
        return 2
    if args.claim:
        wanted = args.claim.strip().upper().lstrip("P")
        claims = [c for c in claims
                  if c["id"].upper().lstrip("P") == wanted]
        if not claims:
            print("no claim {!r} in {}".format(args.claim, contract),
                  file=sys.stderr)
            return 2

    block = _graph_block(text)
    nodes = mermaid_graph(block)[0] if block else {}
    shaping = args.shaping
    if not os.path.isfile(shaping):
        shaping = os.path.join(os.path.dirname(os.path.abspath(contract)),
                               os.path.basename(SHAPING_PATH))

    print("ANCHORED CLAIMS — each claim re-read beside the region that "
          "supports it")
    print("contract: {}   shaping: {}".format(
        contract, shaping if os.path.isfile(shaping) else "none"))
    for claim in claims:
        print("")
        print("{}: {}".format(claim["id"], claim["claim"]))
        if claim["verify_with"]:
            print("    verify with: {}".format(claim["verify_with"]))
        if not claim["anchor"]:
            print("    anchor: <none> — no region to re-read at a seam")
            continue
        kind, detail = resolve_anchor(claim["anchor"], text, nodes, shaping)
        print("    anchor: {} ({})".format(claim["anchor"], kind))
        if detail:
            for line in _excerpt(detail):
                print("      " + line)
        else:
            print("      [!] does not resolve — the support this claim names "
                  "is not here")
    return 0


def cmd_ship(args):
    rc = 0
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print("ship: cannot read {}: {}".format(path, exc), file=sys.stderr)
            rc = 1
            continue
        problems = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if DENSE_RE.search(line):
                problems.append((lineno, line))
        if problems:
            rc = 1
            print("{}: dense markers found in outer register:".format(path))
            for lineno, line in problems[:20]:
                print("  L{}: {}".format(lineno, line[:120]))
        else:
            print("{}: clean".format(path))
    return rc


# -------------------------------------------------------------- contract ----

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Template search order (first match wins — most specific first):
#  1. user-level override (~/.hermes/riel/templates)
#  2. project-level, versioned with the code
#  3. built-in, shipped inside the package next to the engine
DEFAULT_TEMPLATE_DIRS = [
    os.path.expanduser("~/.hermes/riel/templates"),
    os.path.join(os.getcwd(), ".riel", "templates"),
    os.path.join(PKG_ROOT, "templates"),
]


def find_template(typename, extra=None):
    dirs = list(extra or []) + DEFAULT_TEMPLATE_DIRS
    for d in dirs:
        candidate = os.path.join(d, typename + ".md")
        if os.path.exists(candidate):
            return candidate
    return None


_PARAM_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def render_template(text, params, strict=False):
    def repl(match):
        name = match.group(1)
        if name not in params:
            if strict:
                raise KeyError("missing --param {}=".format(name))
            return match.group(0)  # leave placeholder for manual fill
        return params[name]

    return _PARAM_RE.sub(repl, text)


def cmd_contract_new(args):
    if args.list:
        for d in DEFAULT_TEMPLATE_DIRS:
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    if name.endswith(".md"):
                        print(name[:-3])
        return 0
    if args.type == "packet":
        template_path = find_template("packet", args.template_dir)
    else:
        template_path = find_template(args.type, args.template_dir)
    if not template_path:
        print(
            "no template for type {!r}; searched: {}".format(
                args.type, ", ".join(args.template_dir or DEFAULT_TEMPLATE_DIRS)
            ),
            file=sys.stderr,
        )
        return 2
    with open(template_path, encoding="utf-8") as fh:
        text = fh.read()
    params = dict(p.split("=", 1) for p in args.param)
    try:
        result = render_template(text, params, strict=args.strict)
    except KeyError as exc:
        print(exc.args[0] if exc.args else str(exc), file=sys.stderr)
        return 2
    leftover = _PARAM_RE.findall(result)
    if leftover:
        print(
            "note: {} placeholder(s) left — fill with patch/edit: {}".format(
                len(set(leftover)), ", ".join(sorted(set(leftover))[:5])
            ),
            file=sys.stderr,
        )
    if args.output:
        parent = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(parent, exist_ok=True)
        _backup_before_write(args.output)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(result)
        print(result)
    else:
        print(result, end="")
    return 0


_CLOSED_VERBS = ("READ", "EDIT", "CREATE", "RUN", "VERIFY", "ASK")
_TOOL_NAMES = ("read_file", "write_file", "patch", "terminal", "clarify",
               "search_files")


def mermaid_blocks(text):
    """Every ```mermaid block in *text*, in authored order."""
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def mmdc_issues(blocks, timeout=None):
    """Parse each block with mmdc → a list of issue strings (empty when clean).

    Silence when mmdc is not installed: the parser-level check is a bonus, never
    a hard dependency. The call is BOUNDED — a wedged mermaid-cli must not wedge
    the tool that asked for it.
    """
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
                issues.append("mermaid block {} timed out after {}s".format(idx, cap))
                continue
            if res.returncode != 0:
                issues.append("mermaid block {} fails mmdc:\n{}".format(
                    idx, res.stderr.decode("utf-8", "replace")[:400]))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return issues


def _first_mermaid(text):
    """Return the body of the first ```mermaid block, or None."""
    tag = "```mermaid"
    i = text.find(tag)
    if i == -1:
        return None
    i += len(tag)
    j = text.find("```", i)
    if j == -1:
        return None
    return text[i:j].strip()


def _graph_block(text):
    """The mermaid under '## Execution graph'; else the first block."""
    block = _first_mermaid(_section(text, "Execution graph"))
    return block if block is not None else _first_mermaid(text)


def mermaid_graph(block):
    """Best-effort parse of a mermaid flowchart block → (nodes, edges).

    nodes: {id: (shape_opener, label)}; edges: [(src, edge_label, dst)] in
    authored order. Quote-aware, so `{{placeholders}}` inside labels do not
    break bracketing. Not a full mermaid parser — just enough to expand a
    Riel execution graph into explicit text.
    """
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
                label = ("".join(buf).strip().strip("[]").strip()
                         .replace(chr(92) + "n", " "))
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
            lbl = ((m.group(2) or "").strip().strip('"').strip()
                   .replace(chr(92) + "n", " "))
            edges.append((m.group(1), lbl, m.group(3)))
    return nodes, edges


def graph_back_edges(edges):
    """Edges that close a cycle (u->v where v is an ancestor of u)."""
    adj = {}
    for u, _l, v in edges:
        adj.setdefault(u, []).append((_l, v))
    color, backs, roots = {}, [], []
    for u, _l, v in edges:
        if u not in roots:
            roots.append(u)
        if v not in roots:
            roots.append(v)

    def dfs(u):
        color[u] = 1
        for lbl, v in adj.get(u, ()):
            c = color.get(v, 0)
            if c == 1:
                backs.append((u, lbl, v))
            elif c == 0:
                dfs(v)
        color[u] = 2

    for r in roots:
        if color.get(r, 0) == 0:
            dfs(r)
    return backs


def cmd_contract_digest(args):
    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()
    block = _graph_block(text)
    if block is None:
        print("no mermaid graph found in {}".format(args.file), file=sys.stderr)
        return 1
    nodes, edges = mermaid_graph(block)
    out = []
    out.append("Graph digest — explicit structure (the diagram stays for humans)")
    out.append("")
    out.append("Elements ({}):".format(len(nodes)))
    for nid, (_shape, label) in nodes.items():
        out.append("  {} — {}".format(nid, label))
    out.append("")
    out.append("Edges, authored order ({}):".format(len(edges)))
    for u, lbl, v in edges:
        out.append("  {} {} {}".format(
            u, "=[{}]=>".format(lbl) if lbl else "->", v))
    outgoing = {}
    for u, lbl, v in edges:
        outgoing.setdefault(u, []).append((lbl, v))
    branches = {u: a for u, a in outgoing.items() if len({v for _l, v in a}) > 1}
    if branches:
        out.append("")
        out.append("Branches (decision → labeled alternatives):")
        for u, alts in branches.items():
            out.append("  {} → {}".format(
                u, " | ".join("{}: {}".format(l or "?", v) for l, v in alts)))
    incoming = {v for _u, _l, v in edges}
    source = {u for u, _l, _v in edges}
    entries = [nid for nid in nodes if nid not in incoming] or ["(none)"]
    terminals = [nid for nid in nodes if nid not in source] or ["(none)"]
    out.append("")
    out.append("Entry (no incoming): " + ", ".join(entries))
    out.append("Terminals (no outgoing): " + ", ".join(terminals))
    backs = graph_back_edges(edges)
    if backs:
        counter = re.search("< *[0-9]|>= *[0-9]", block)
        guarded = ("  guards: yes" if counter
                   else "  guards: NONE — add a bounded '< 3 / >= 3'")
        out.append("Loops (back-edges): " + ", ".join(
            "{}->{}".format(u, v) for u, _l, v in backs) + guarded)
    out.append("")
    out.append("Meaning & limits: a graph proves order, branches and loops only. "
               "It does not prove a command ran, a gate passed, or the "
               "deliverable exists — that lives in the gates and the ledger.")
    result = "\n".join(out)
    print(result)
    if args.output:
        parent = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(parent, exist_ok=True)
        _backup_before_write(args.output)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(result + "\n")
    return 0


def _first_phase_id(nodes):
    for nid in nodes:
        if re.match(r"^[FW]\d+$", nid):
            return nid
    return None


def _phase_subgraph(nodes, edges, start):
    """Node ids reachable from `start` without crossing into another phase."""
    phase_ids = {nid for nid in nodes if re.match(r"^[FW]\d+$", nid)}
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


def cmd_contract_slice(args):
    """Slice one phase of a contract into a mini packet (assisted).

    Mechanical: the phase subgraph (nodes reachable from the phase without
    crossing into another phase). Context / Gates / Deliverable are left as
    FILL for the parent to complete — the packet format is not per-phase.
    """
    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()
    block = _graph_block(text)
    if block is None:
        print("no mermaid graph found in {}".format(args.file), file=sys.stderr)
        return 1
    nodes, edges = mermaid_graph(block)

    start = args.phase or _first_phase_id(nodes)
    if not start or start not in nodes:
        print("no phase node {!r} in {}".format(args.phase, args.file),
              file=sys.stderr)
        return 2

    keep = _phase_subgraph(nodes, edges, start)
    closers = {"[": "]", "(": ")", "{": "}"}
    task_line = ""
    for ln in text.splitlines():
        if ln.startswith("# Task:"):
            task_line = ln[len("# Task:"):].strip()
            break

    body = [
        "# Task: {} — {}".format(task_line or "(task)", nodes[start][1]),
        "",
        "## Objective",
        _section(text, "Objective") or "<FILL>",
        "",
        "## Context",
    ]
    keywords = context_keywords(text)
    why = _subsection(text, "Context", "Why")
    if why:
        body += [
            "",
            "### Why",
            "<!-- Heredado del contrato: el racional de la tarea — por qué este\n"
            "     objetivo y no otro. No lo reinterpretes ante un conflicto:\n"
            "     escálalo (ASK[goal-changing]). -->",
            why,
        ]
    if keywords:
        body += [
            "",
            "### Context keywords",
            "<!-- Heredadas del contrato: úsalas para traer contexto de "
            "memoria/DRAN antes de ejecutar la fase. -->",
        ]
        for kw in keywords:
            body.append("- {}{}".format(
                kw["term"], " → {}".format(kw["source"]) if kw["source"] else ""))
        body.append("")
        body.append("<!-- FILL: el resto del contexto que esta fase necesita -->")
    else:
        body.append("<!-- FILL: only what this phase needs -->")
    body += [
        "",
        "## Constraints",
        _section(text, "Constraints") or "<FILL>",
        "",
        "## Pre-registered claims",
        _section(text, "Pre-registered claims") or "<FILL>",
        "",
        "## Execution graph",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for nid, (opener, label) in nodes.items():
        if nid in keep:
            body.append('  {}{}"{}"{}'.format(
                nid, opener, label, closers[opener]))
    for u, lbl, v in edges:
        if u in keep and v in keep:
            body.append("  {} -->|{}| {}".format(u, lbl, v) if lbl
                        else "  {} --> {}".format(u, v))
    body += [
        "```",
        "",
        "## Verification gates",
        "<!-- FILL: command / expected / on failure for this phase -->",
        "",
        "## Deliverable",
        "<!-- FILL -->",
        "",
        "## DO NOT",
        _section(text, "DO NOT") or "<FILL>",
    ]
    result = "\n".join(body)
    print(result)
    if args.output:
        parent = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(parent, exist_ok=True)
        _backup_before_write(args.output)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(result + "\n")
    return 0


def cmd_contract_validate(args):
    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()
    issues = []
    warnings = []

    # Structure: nine sections in order
    headings = re.findall(r"^(#{1,2})\s+(.+)$", text, re.MULTILINE)
    wanted_order = [
        "Task:", "Objective", "Context", "Constraints",
        "Pre-registered claims", "Execution graph",
        "Verification gates", "Deliverable", "DO NOT",
    ]
    # headings gives (level, title) — the level-1 heading is "# Task",
    # everything else is "## ..."
    titles = [t.strip() for _, t in headings]
    pos = []
    last = -1
    for w in wanted_order:
        for i, t in enumerate(titles):
            if t.startswith(w) or t == w.rstrip(":"):
                pos.append(i)
                last = max(last, i)
                break
        else:
            issues.append("missing section: {!r}".format(w))
    if pos != sorted(pos):
        issues.append("sections out of order; expected packet.md order")

    # Objective is one sentence starting with "We need"
    mo = re.search(r"^## Objective\s*\n(.+?)(?=\n##\s)", text, re.S | re.M)
    if mo:
        first_line = mo.group(1).strip().splitlines()[0] if mo.group(1).strip() else ""
        if "We need" not in first_line and "Necesitamos" not in first_line:
            issues.append("Objective does not open with \"We need…\"")
        if _sentence_count(mo.group(1)) > 1:
            warnings.append(
                "Objective is more than one sentence — the spec asks for one "
                "(what \"done\" produces); move rationale to '### Why'")
    elif text:
        issues.append("no ## Objective section found")

    # Pre-registered claims
    mp = re.search(
        r"^## Pre-registered claims\s*\n(.*?)(?=\n##\s)", text, re.S | re.M
    )
    if mp:
        claims = re.findall(r"^-+\s+P\d+", mp.group(1), re.M)
        if not claims:
            issues.append("Pre-registered claims section is empty")
    elif text:
        issues.append("no ## Pre-registered claims section found")

    # DO NOT section non-empty
    md = re.search(r"^## DO NOT\s*\n(.*?)(?=\n##\s|\Z)", text, re.S | re.M)
    if md:
        body = md.group(1).strip()
        items = [l for l in body.splitlines() if l.strip().startswith("-")]
        if not items:
            issues.append("DO NOT section has no items (scope enforcement missing)")

    # Context keywords: non-fatal — a contract without them still validates, but
    # the context-fetch step has nothing to search (see spec-contract-format).
    if not context_keywords(text):
        warnings.append(
            "no '### Context keywords' under ## Context "
            "(nothing for the context fetch to search)")

    # Graph conventions
    parsed_nodes = {}
    blocks = re.findall(r"```mermaid\n(.*?)```", text, re.S)
    if not blocks:
        issues.append("no mermaid execution graph found")
    else:
        g = blocks[0]
        parsed_nodes, parsed_edges = mermaid_graph(g)
        ok_ids = {"S", "G", "W", "F", "END", "START", "Q", "SELF", "DC", "APP",
                  "REC", "FIX", "ERR"}
        bad_ids = [
            nid for nid in parsed_nodes
            if nid.upper() not in ok_ids and not re.match(r"^(S|G|W|F)\d+", nid)
        ]
        if bad_ids:
            issues.append("non-predictable node ids: {}".format(sorted(set(bad_ids))))
        # A graph with nodes but no edges at all is degenerate
        if "-->" not in blocks[0]:
            issues.append("execution graph has no edges")
        pops_run = re.findall(r'\[\"RUN ', blocks[0])
        pops_verify = re.findall(r'\{"[^\"]*"', blocks[0])
        if not pops_run:
            issues.append("no RUN gate found in graph")
        if not pops_verify:
            issues.append("no VERIFY/Check decision found in graph (funnel missing)")
        # Every decision node must have at least one labeled outgoing edge
        decisions = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\{", blocks[0])
        for node in set(decisions):
            if not re.search(
                r"{}.*-->?\s*\|".format(re.escape(node)), blocks[0]
            ):
                issues.append(
                    "decision node {!r} has no labeled outgoing edge".format(node)
                )
        # --- closed verb vocabulary on execution nodes (riel-contract) ---
        bad_verbs = []
        for nid, (shape, label) in parsed_nodes.items():
            lab = label.strip()
            m = re.match("[A-Za-z]+", lab)
            verb = m.group(0).upper() if m else ""
            if shape == "[" and verb not in _CLOSED_VERBS:
                bad_verbs.append((nid, lab[:50]))
            if verb == "ASK" and not re.match(
                    r"ASK\[(irreversible|outside-claims|goal-changing)\]", lab):
                issues.append(
                    "ASK node {!r} must start with its trigger: "
                    "ASK[irreversible|outside-claims|goal-changing]".format(nid))
            if len(lab.split()) > 20:
                warnings.append(
                    "node {} label is {} tokens (keep <= 15-20)".format(
                        nid, len(lab.split())))
        if bad_verbs:
            issues.append(
                "execution node(s) not starting with a closed verb "
                "(READ/EDIT/CREATE/RUN/VERIFY/ASK): {}".format(bad_verbs))
        if "<br" in g:
            issues.append(
                "uses <br/> — mermaid v11 strict breaks on it; "
                "use a line-break label")
        if any(ln.strip().startswith("style ") for ln in g.splitlines()):
            issues.append(
                "execution graph carries `style` — a parsed-as-spec DAG must not")
        labels = re.findall('"([^"]*)"', g)
        found_tools = sorted({
            t for label in labels
            for t in _TOOL_NAMES
            if t in re.findall("[A-Za-z_][A-Za-z0-9_]*", label)
        })
        if found_tools:
            issues.append(
                "tool name(s) in node labels — use semantic verbs: {}".format(
                    found_tools))
        # soft: a loop without a counter guard
        if graph_back_edges(parsed_edges) and not re.search(
                "< *[0-9]|>= *[0-9]", g):
            warnings.append(
                "graph has a loop but no counter guard (< 3 / >= 3) — "
                "bounded retries prevent infinite loops")

    # if mmdc is available, try parsing each graph block
    issues.extend(mmdc_issues(blocks))

    # Claim anchors (Spec 2 + Spec 7). A claim with no anchor cannot be
    # re-read at a seam — a WARN, never fatal: the shipped templates carry
    # none. An anchor whose support is missing IS a failure (the section
    # forms); a node the local graph lacks is the inherited-on-a-slice case.
    shaping_path = os.path.join(
        os.path.dirname(os.path.abspath(args.file)),
        os.path.basename(SHAPING_PATH))
    for claim in claim_anchors(text):
        if not claim["anchor"]:
            warnings.append(
                "{} has no anchor — a seam cannot re-read its support: add "
                "'— anchor: §Section#n', a node id, or 'shaping:F#'".format(
                    claim["id"]))
            continue
        kind, detail = resolve_anchor(claim["anchor"], text, parsed_nodes,
                                      shaping_path)
        if kind == "unknown":
            issues.append(
                "{} anchor {!r} is not a valid form: §<Section>[#<n>] | "
                "<NodeId> | shaping:F<n>".format(claim["id"], claim["anchor"]))
        elif kind == "section" and detail is None:
            issues.append(
                "{} anchor {!r} does not resolve — no such section or bullet "
                "in this contract".format(claim["id"], claim["anchor"]))
        elif kind == "node" and detail is None:
            warnings.append(
                "{} anchor {!r} is not a node of this graph — on a slice that "
                "is inherited from the parent contract".format(
                    claim["id"], claim["anchor"]))
        elif kind == "shaping" and detail is None:
            warnings.append(
                "{} anchors {} — {}".format(
                    claim["id"], claim["anchor"],
                    "no such finding in {}".format(shaping_path)
                    if os.path.isfile(shaping_path) else "no shaping file to check"))

    for w in warnings:
        print("WARN: {}".format(w), file=sys.stderr)
    if issues:
        print("INVALID packet {}:".format(args.file))
        for issue in issues:
            print("  - " + issue)
        return 1
    print("valid: {}".format(args.file))
    return 0


# ------------------------------------------------------------------ fetch ---

def _redact_url(url):
    """Drop the query string so a token in the URL never reaches logs/stderr."""
    parts = urllib.parse.urlsplit(url)
    if parts.query:
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    return url


def cmd_mermaid(args):
    """Parse every mermaid block of the given files with mmdc.

    The repo gate behind `make validate` and the parser-level half of
    `riel_check(mermaid=true)`: silence (exit 0) when there are no blocks or no
    mmdc, exit 1 with one line per failing block.
    """
    total, failed = 0, 0
    for path in args.file:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            print("MISSING: {}".format(path))
            failed += 1
            continue
        with open(path, encoding="utf-8") as fh:
            blocks = mermaid_blocks(fh.read())
        if not blocks:
            print("SKIP: {} (no mermaid block)".format(path))
            continue
        total += len(blocks)
        issues = mmdc_issues(blocks)
        if issues:
            failed += len(issues)
            for issue in issues:
                print("FAIL: {} -> {}".format(path, issue.replace("\n", " ")[:200]))
        else:
            print("PASS: {} -> {} block(s)".format(path, len(blocks)))
    print("----")
    if not shutil.which(VERIFY_CMD):
        print("mmdc not found (install: npm install -g @mermaid-js/mermaid-cli) "
              "— {} block(s) skipped".format(total))
        return 0
    print("{} blocks, {} failed".format(total, failed))
    return 0 if failed == 0 else 1


def cmd_fetch(args):
    """Download a file over HTTP(S) and write it atomically.

    Server-agnostic: the URL carries whatever the server needs (e.g. a
    short-lived signed token). Security defaults: https required (http only
    for localhost, or anywhere with --allow-http for a trusted transport such
    as a VPN), TLS verified, bounded response size, optional sha256 integrity
    check, atomic write, and the URL is never printed (it may embed a secret).
    """
    url = args.url
    out = args.output
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        print("fetch: unsupported scheme {!r} (want http/https)".format(
            parsed.scheme), file=sys.stderr)
        return 2
    host = parsed.hostname or ""
    if (parsed.scheme == "http" and not args.allow_http
            and host not in ("localhost", "127.0.0.1", "::1")):
        print("fetch: refusing plain http to non-local host {!r}; use https "
              "or --allow-http (trusted transport, e.g. a VPN)".format(host),
              file=sys.stderr)
        return 2

    req = urllib.request.Request(
        url, headers={"User-Agent": "riel/{}".format(VERSION)})
    for raw in args.header or []:
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            print("fetch: bad --header {!r} (want 'Name: value')".format(raw),
                  file=sys.stderr)
            return 2
        req.add_header(name.strip(), value.strip())

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > args.max_bytes:
                    print("fetch: response exceeds {} bytes; aborting".format(
                        args.max_bytes), file=sys.stderr)
                    return 3
                chunks.append(chunk)
            data = b"".join(chunks)
    except urllib.error.HTTPError as exc:
        print("fetch: HTTP {} for {}".format(exc.code, _redact_url(url)),
              file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print("fetch: {} for {}".format(exc, _redact_url(url)), file=sys.stderr)
        return 1

    digest = hashlib.sha256(data).hexdigest()
    if args.sha256:
        want = args.sha256.strip().lower()
        if digest != want:
            print("fetch: sha256 mismatch\n  want {}\n  got  {}".format(
                want, digest), file=sys.stderr)
            return 4

    outdir = os.path.dirname(os.path.abspath(out))
    os.makedirs(outdir, exist_ok=True)
    _backup_before_write(out)
    fd, tmp = tempfile.mkstemp(dir=outdir, prefix=".riel-fetch-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, out)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print("fetch: cannot write {}: {}".format(out, exc), file=sys.stderr)
        return 1

    print("fetched {} bytes -> {} (sha256 {})".format(len(data), out, digest))
    return 0


# ------------------------------------------------------------------ main ----

def main(argv=None):
    p = argparse.ArgumentParser(prog="riel", description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument(
        "--ledger", default=LEDGER_PATH,
        help="path to the ledger file (default: .riel/ledger.md)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("note", help="append/update ledger entries")
    n.add_argument("--goal")
    n.add_argument("--next")
    n.add_argument("--source")
    n.add_argument("--phase")
    n.add_argument("--core")
    n.add_argument("--core-slot", type=int)
    n.add_argument("--claim")
    n.add_argument("--verify-with")
    n.add_argument("--check")
    n.add_argument("--by")
    n.add_argument("--covering")
    n.add_argument("--confidence", type=int)
    n.add_argument("--open")
    n.add_argument("--settled-by")
    n.add_argument("--close", type=int,
                   help="close open question N (requires --check/--by)")
    n.add_argument("--from-contract", nargs="?", const=CONTRACT_PATH,
                   default=None, metavar="PATH",
                   help="seed goal/phase/claims/next from a contract.md "
                        "(default: .riel/contract.md)")
    n.set_defaults(fn=cmd_note)

    s = sub.add_parser("seam", help="re-print ledger + due reminders")
    s.set_defaults(fn=cmd_seam)

    an = sub.add_parser("anchor",
                        help="re-read each claim beside its contract region "
                             "(sections, graph nodes, shaping findings)")
    an.add_argument("claim", nargs="?", default=None,
                    help="only this claim (P1 or 1; default: all)")
    an.add_argument("--contract", default=CONTRACT_PATH)
    an.add_argument("--shaping", default=SHAPING_PATH)
    an.set_defaults(fn=cmd_anchor)

    sh = sub.add_parser("shaping", help="work with .riel/shaping.md (Spec 7)")
    shsub = sh.add_subparsers(dest="shcmd", required=True)
    shv = shsub.add_parser("validate", help="validate a shaping file")
    shv.add_argument("file", nargs="?", default=None,
                     help="path (default: .riel/shaping.md)")
    shv.add_argument("--contract", default=CONTRACT_PATH,
                     help="contract to check the shaping:F# anchors against")
    shv.set_defaults(fn=cmd_shaping_validate)
    shn = shsub.add_parser("new", help="instantiate the shaping template")
    shn.add_argument("--type", default="shaping")
    shn.add_argument("--param", action="append", default=[],
                     help="template parameter key=value (repeatable)")
    shn.add_argument("--template-dir", action="append", default=None)
    shn.add_argument("--output", "-o", default=None,
                     help="destination (default: .riel/shaping.md; '-' = stdout)")
    shn.add_argument("--force", action="store_true",
                     help="overwrite an existing shaping")
    shn.add_argument("--strict", action="store_true")
    shn.set_defaults(fn=cmd_shaping_new)

    r = sub.add_parser("resume", help="post-gap bootstrap")
    r.set_defaults(fn=cmd_resume)

    t = sub.add_parser("todo",
                       help="derive the Hermes session-todo mirror (JSON): "
                            "the plan — goal, phases and their steps")
    t.set_defaults(fn=cmd_todo)

    ss = sub.add_parser("status",
                        help="the ledger's own facts (JSON) for the chip and "
                             "the gate: goal, phase, next, opens, claims, ✓")
    ss.set_defaults(fn=cmd_status)

    cx = sub.add_parser("context",
                        help="context-fetch keywords from a contract (JSON)")
    cx.add_argument("--contract", default=CONTRACT_PATH,
                    help="path to contract.md (default: .riel/contract.md)")
    cx.add_argument("--output", "-o")
    cx.set_defaults(fn=cmd_context)

    cl = sub.add_parser("clean",
                        help="clear .riel/ state — flat timestamped backups "
                             "inside .riel/, never a subdirectory")
    cl.add_argument("--all", action="store_true",
                    help="also clean contract.md and shaping.md "
                         "(default: ledger only)")
    cl.add_argument("--purge", action="store_true",
                    help="remove without backing up")
    cl.set_defaults(fn=cmd_clean)

    h = sub.add_parser("ship", help="check outgoing file for dense markers")
    h.add_argument("files", nargs="+")
    h.set_defaults(fn=cmd_ship)

    mm = sub.add_parser("mermaid",
                        help="parse every mermaid block of FILE... with mmdc "
                             "(silent without mmdc; bounded per call)")
    mm.add_argument("file", nargs="+", help="markdown files to check")
    mm.set_defaults(fn=cmd_mermaid)

    dg = sub.add_parser("digest",
                        help="explicit text digest of a file's mermaid graph")
    dg.add_argument("file")
    dg.add_argument("--output", "-o")
    dg.set_defaults(fn=cmd_contract_digest)

    b = sub.add_parser("contract", help="work with contracts and packets")
    bsub = b.add_subparsers(dest="bcmd", required=True)

    bn = bsub.add_parser("new", help="instantiate a template")
    bn.add_argument("--type", default="packet",
                    help="template type (default: blank packet)")
    bn.add_argument("--param", action="append", default=[],
                    help="template parameter key=value (repeatable)")
    bn.add_argument("--template-dir", action="append", default=None)
    bn.add_argument("--list", action="store_true")
    bn.add_argument("--output", "-o")
    bn.add_argument("--strict", action="store_true",
                    help="fail if any {{placeholder}} remains unfilled")
    bn.set_defaults(fn=cmd_contract_new)

    bv = bsub.add_parser("validate", help="validate a packet file")
    bv.add_argument("file")
    bv.set_defaults(fn=cmd_contract_validate)

    bd = bsub.add_parser("digest",
                         help="print an explicit text digest of the graph")
    bd.add_argument("file")
    bd.add_argument("--output", "-o")
    bd.set_defaults(fn=cmd_contract_digest)

    bs = bsub.add_parser("slice",
                         help="slice one phase into a mini packet")
    bs.add_argument("file")
    bs.add_argument("--phase",
                    help="phase node id (default: first F#/W#)")
    bs.add_argument("--output", "-o")
    bs.set_defaults(fn=cmd_contract_slice)

    f = sub.add_parser("fetch",
                       help="download a file over HTTP(S), atomically")
    f.add_argument("url")
    f.add_argument("--output", "-o", required=True,
                   help="destination path (written atomically)")
    f.add_argument("--sha256",
                   help="expected sha256 of the body (integrity check)")
    f.add_argument("--header", action="append", default=[],
                   help="extra request header 'Name: value' (repeatable)")
    f.add_argument("--allow-http", action="store_true",
                   help="permit plain http to any host (trusted transport, e.g. a VPN)")
    f.add_argument("--timeout", type=float, default=30.0,
                   help="socket timeout in seconds (default: 30)")
    f.add_argument("--max-bytes", type=int, default=5000000,
                   help="abort if the body exceeds this many bytes (default: 5MB)")
    f.set_defaults(fn=cmd_fetch)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
