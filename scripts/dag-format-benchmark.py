#!/usr/bin/env python3
"""Benchmark: prose vs mermaid-DAG vs numbered-plan prompt formats.

Asks an LLM to compute the minimum number of sequential rounds (topological
layering) needed to run a dependency graph, given the SAME graph in three
notations:

  prose         - one sentence per node ("draft can only start once ...")
  dag-mermaid   - `graph TD` edge list (what riel-contract puts in briefs)
  dag-compiler  - numbered plan with index references (LLMCompiler-style)

Answers are judged by exact match against ground truth computed locally with
Kahn's algorithm. The script is stdlib-only and provider-agnostic: any
OpenAI-compatible /v1/chat/completions endpoint works.

Usage:
  export OPENAI_API_KEY=<your-key>        # or pass --api-key
  python3 scripts/dag-format-benchmark.py \
      --base-url https://your-endpoint/v1 \
      --models model-a,model-b \
      [--cases content,build] [--max-tokens 1000] [--dry-run]

No credentials or endpoints are hardcoded; everything comes from flags/env.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

# --------------------------------------------------------------------------
# Test graphs: node -> list of prerequisite nodes
# --------------------------------------------------------------------------

CASES = {
    # small graphs (<= 8 nodes)
    "content": {
        "outline": [], "research": [], "draft": ["outline", "research"],
        "figures": ["outline"], "review": ["draft", "figures"],
        "seo": ["draft"], "publish": ["review", "seo"],
    },
    "build": {
        "fetch-deps": [], "lint": ["fetch-deps"], "unit-tests": ["fetch-deps"],
        "typecheck": ["fetch-deps"], "integration": ["unit-tests", "lint"],
        "docker": ["integration", "typecheck"], "deploy": ["docker"],
    },
    "ml": {
        "ingest": [], "clean": ["ingest"], "featurize": ["clean"],
        "split": ["clean"], "train-a": ["featurize"], "train-b": ["featurize"],
        "blend": ["train-a", "train-b"], "evaluate": ["blend", "split"],
    },
    "incident": {
        "page-oncall": [], "gather-logs": ["page-oncall"],
        "check-deploys": ["page-oncall"], "check-dashboards": ["page-oncall"],
        "correlate": ["gather-logs", "check-deploys", "check-dashboards"],
        "mitigate": ["correlate"], "postmortem-draft": ["mitigate"],
    },
    # large graphs (18-20 nodes): where notation starts to matter
    "monorepo": {
        "init": [],
        "fetch-libs": ["init"], "gen-proto": ["init"], "lint-core": ["init"],
        "lint-web": ["init"], "codegen-clients": ["gen-proto"],
        "typecheck-core": ["codegen-clients"], "typecheck-web": ["codegen-clients"],
        "unit-core": ["codegen-clients"], "unit-web": ["codegen-clients"],
        "integration-core": ["unit-core", "typecheck-core"],
        "integration-web": ["unit-web", "typecheck-web"],
        "build-images": ["integration-core", "integration-web", "lint-core", "lint-web"],
        "scan-images": ["build-images"], "sign-images": ["scan-images"],
        "push-staging": ["sign-images"], "smoke-staging": ["push-staging"],
        "promote-prod": ["smoke-staging"],
    },
    "dataplatform": {
        "ingest-events": [], "ingest-billing": [], "ingest-crm": [],
        "dedupe-events": ["ingest-events"],
        "clean-billing": ["ingest-billing"], "clean-crm": ["ingest-crm"],
        "identity-resolution": ["dedupe-events", "clean-crm"],
        "feature-usage": ["dedupe-events"],
        "feature-revenue": ["clean-billing", "identity-resolution"],
        "feature-segments": ["identity-resolution"],
        "train-churn": ["feature-usage", "feature-revenue", "feature-segments"],
        "train-upsell": ["feature-usage", "feature-revenue"],
        "eval-churn": ["train-churn"], "eval-upsell": ["train-upsell"],
        "champion-challenger": ["eval-churn", "eval-upsell"],
        "sync-warehouse": ["identity-resolution", "clean-billing"],
        "build-report": ["champion-challenger"],
        "build-dashboards": ["sync-warehouse"], "qa-dashboards": ["build-dashboards"],
        "ship-digest": ["build-report", "qa-dashboards"],
    },
}

PROMPT = """A team must run these jobs. Each job takes the same amount of time. Jobs whose dependencies are all done can run at the same time.

{spec}

Produce the minimum number of sequential rounds: list each round as the set of jobs that run together.
Answer with ONLY this JSON, no prose: {{"rounds": [["job", "job"], ["job"]]}}"""


# --------------------------------------------------------------------------
# Ground truth: minimal parallel layers via Kahn's algorithm
# --------------------------------------------------------------------------

def layers(graph):
    indeg = {n: len(d) for n, d in graph.items()}
    dependents = {n: [] for n in graph}
    for n, ds in graph.items():
        for d in ds:
            dependents[d].append(n)
    q = deque(sorted(n for n, k in indeg.items() if k == 0))
    out = []
    while q:
        out.append(sorted(q))
        nxt = []
        for n in q:
            for m in dependents[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    nxt.append(m)
        q = deque(sorted(nxt))
    return out


def validate_graphs(cases):
    """Refuse to run if a ground truth is not a complete topological layering."""
    for name, g in cases.items():
        ls = layers(g)
        pos = {n: i for i, l in enumerate(ls) for n in l}
        assert len(pos) == len(g), f"{name}: layering misses nodes"
        for n, ds in g.items():
            for d in ds:
                assert pos[d] < pos[n], f"{name}: {d} not before {n}"


# --------------------------------------------------------------------------
# The three notations for the same graph
# --------------------------------------------------------------------------

def prose_spec(g):
    lines = []
    for n, ds in g.items():
        if ds:
            lines.append(f"{n} can only start once all of these are finished: {', '.join(ds)}.")
        else:
            lines.append(f"{n} has no prerequisites.")
    lines.append("Everything else in this list has no stated prerequisites beyond what is written above.")
    return " ".join(lines)


def mermaid_spec(g):
    e = ["graph TD"]
    for n, ds in g.items():
        for d in ds:
            e.append(f"  {d} --> {n}")
        if not ds:
            e.append(f"  {n}")
    return "\n".join(e)


def compiler_spec(g):
    idx = {n: i for i, n in enumerate(g)}
    lines = []
    for n, ds in g.items():
        args = ", ".join(f"{d}={idx[d]}" for d in ds)
        lines.append(f"{idx[n]}: plan(name='{n}', deps=[{args}])")
    return "\n".join(lines)


CONDITIONS = {
    "prose": prose_spec,
    "dag-mermaid": mermaid_spec,
    "dag-compiler": compiler_spec,
}


# --------------------------------------------------------------------------
# Model call + judging
# --------------------------------------------------------------------------

def call(base_url, key, model, msg, max_tokens, temperature, retries, timeout):
    body = json.dumps({
        "model": model, "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": msg}],
    }).encode()
    url = base_url.rstrip("/") + "/chat/completions"
    last_err = None
    for i in range(retries):
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            c = d["choices"][0]["message"]["content"]
            u = d.get("usage", {})
            return c, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), None
        except Exception as e:  # noqa: BLE001 - report, backoff, retry
            last_err = str(e)[:160]
            time.sleep(3 * (i + 1))
    return None, 0, 0, last_err


def parse_rounds(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return [sorted(x) for x in json.loads(m.group(0)).get("rounds", [])]
    except Exception:  # noqa: BLE001
        return None


def judge(pred, gt):
    if pred is None:
        return "unparseable", False
    if pred == gt:
        return "exact", True
    tot = sum(len(g) for g in gt)
    if sum(len(p) for p in pred) != tot:
        return "malformed", False  # node duplicated/dropped across rounds
    if len(pred) == len(gt):
        hits = sum(len(set(p) & set(g)) for p, g in zip(pred, gt))
        return f"partial {hits}/{tot}", hits == tot
    return f"wrong-depth({len(pred)} vs {len(gt)})", False


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True,
                    help="OpenAI-compatible base URL, e.g. https://host/v1")
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"),
                    help="API key (default: $OPENAI_API_KEY)")
    ap.add_argument("--models", required=True, help="comma-separated model ids")
    ap.add_argument("--cases", default=",".join(CASES),
                    help=f"comma-separated cases (default: all: {', '.join(CASES)})")
    ap.add_argument("--max-tokens", type=int, default=1000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=90, help="per-request seconds")
    ap.add_argument("--dry-run", action="store_true",
                    help="print ground truth + spec sizes, make no API calls")
    ap.add_argument("--out", default="dag-benchmark-results.txt")
    args = ap.parse_args()

    names = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in names if c not in CASES]
    if unknown:
        ap.error(f"unknown cases: {unknown}")
    cases = {c: CASES[c] for c in names}
    validate_graphs(cases)

    if args.dry_run:
        for name, g in cases.items():
            ls = layers(g)
            print(f"{name} ({len(g)} nodes, {len(ls)} rounds)")
            print("   ", " | ".join(",".join(l) for l in ls))
            for cname, fn in CONDITIONS.items():
                s = fn(g)
                print(f"    {cname:13s} {len(s):5d} chars")
        return

    if not args.api_key:
        ap.error("--api-key or $OPENAI_API_KEY required")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    jobs = []  # (case, cond, model, message, ground_truth)
    for cname, g in cases.items():
        gt = [sorted(l) for l in layers(g)]
        for cond, fn in CONDITIONS.items():
            msg = PROMPT.format(spec=fn(g))
            for model in models:
                jobs.append((cname, cond, model, msg, gt))

    print(f"{len(jobs)} calls: {len(models)} model(s) x {len(cases)} case(s) x "
          f"{len(CONDITIONS)} conditions\n", file=sys.stderr)

    def run(job):
        cname, cond, model, msg, gt = job
        content, ptok, ctok, err = call(
            args.base_url, args.api_key, model, msg,
            args.max_tokens, args.temperature, args.retries, args.timeout)
        if err:
            return (cname, cond, model, "ERROR", False, ptok, ctok, err)
        verdict, ok = judge(parse_rounds(content), gt)
        return (cname, cond, model, verdict, ok, ptok, ctok, "")

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        results = list(ex.map(run, jobs))

    lines = [f"{'case':14s} {'cond':14s} {'model':22s} {'ok':3s} "
             f"{'verdict':22s} {'ptok':>5s} {'ctok':>5s}"]
    for r in results:
        mark = "Y" if r[4] else "N"
        lines.append(f"{r[0]:14s} {r[1]:14s} {r[2]:22s} {mark:3s} "
                     f"{r[3]:22s} {r[5]:5d} {r[6]:5d} {r[7]}")

    acc = defaultdict(lambda: [0, 0])
    for r in results:
        acc[(r[1], r[2])][0] += r[4]
        acc[(r[1], r[2])][1] += 1
    lines.append("\n--- accuracy by condition x model ---")
    for (cond, model), (ok, n) in sorted(acc.items()):
        lines.append(f"{cond:14s} {model:22s} {ok}/{n}")

    toks = defaultdict(lambda: defaultdict(list))
    for r in results:
        toks[r[1]]["p"].append(r[5])
        toks[r[1]]["c"].append(r[6])
    lines.append("\n--- tokens by condition (mean prompt / mean completion) ---")
    for cond in CONDITIONS:
        p, c = toks[cond]["p"], toks[cond]["c"]
        lines.append(f"{cond:14s} prompt={sum(p)/len(p):6.0f} completion={sum(c)/len(c):6.0f}")

    out = "\n".join(lines) + "\n"
    print(out)
    with open(args.out, "w") as f:
        f.write(out)
    print(f"\nsaved to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
