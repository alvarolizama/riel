"""The ONE declaration of `riel_note`'s parameters.

Three places used to encode this set independently:

  * the JSON schema the model reads          (`schemas.py`)
  * the flag mapping the handler applies      (`tools.py`, `_STR_FLAGS`/`_INT_FLAGS`)
  * the argparse parser the engine builds     (`run.py`, fifteen `add_argument` calls)

They agreed by discipline and by test, never by construction — a flag added to
one and forgotten in another was a silent drift, and the model would call a
parameter the engine ignored. This file is the single source; the three
consumers derive from it, and a test proves all three agree.

Each record is:

    name   — the tool parameter and the schema property
    flag   — the engine's CLI flag
    kind   — "str" | "int" (the type both the schema and argparse use)
    help   — the schema description AND the argparse help, one text
    section — the ledger `## section` the entry lands in, for documentation

`from_contract` is the one special case: its flag takes an optional value, so it
is declared here as metadata but wired by hand in each consumer.

Stdlib only, no imports: the engine loads it as a sibling script and the
package loads it by path.
"""

NOTE_PARAMS = (
    {
        "name": "goal",
        "flag": "--goal",
        "kind": "str",
        "section": "## Goal",
        "help": "What 'done' means for this task (## Goal).",
    },
    {
        "name": "next",
        "flag": "--next",
        "kind": "str",
        "section": "## Next",
        "help": "The single next concrete action (## Next).",
    },
    {
        "name": "source",
        "flag": "--source",
        "kind": "str",
        "section": "## Source",
        "help": "Where the task came from (## Source).",
    },
    {
        "name": "phase",
        "flag": "--phase",
        "kind": "str",
        "section": "## Phase",
        "help": "Current phase pointer, e.g. F2 (## Phase).",
    },
    {
        "name": "core",
        "flag": "--core",
        "kind": "str",
        "section": "## Core",
        "help": "A load-bearing fact the receiver of this work must know, as 'name — fact'.",
    },
    {
        "name": "core_slot",
        "flag": "--core-slot",
        "kind": "int",
        "section": "## Core",
        "help": "Which Core slot to write (1-based); omit to append.",
    },
    {
        "name": "claim",
        "flag": "--claim",
        "kind": "str",
        "section": "## Claims",
        "help": "A claim about the code ('what must be true'), used with verify_with.",
    },
    {
        "name": "verify_with",
        "flag": "--verify-with",
        "kind": "str",
        "section": "## Claims",
        "help": "The command that would verify the claim, e.g. 'mix test token_test.exs'.",
    },
    {
        "name": "check",
        "flag": "--check",
        "kind": "str",
        "section": "## Verified",
        "help": "A verified checkpoint ('what I checked'), used with by.",
    },
    {
        "name": "by",
        "flag": "--by",
        "kind": "str",
        "section": "## Verified",
        "help": "The real command/gate that produced the evidence for --check (never a guess).",
    },
    {
        "name": "covering",
        "flag": "--covering",
        "kind": "str",
        "section": "## Verified",
        "help": "What scope the checkpoint covers, e.g. 'sign+verify+expiry'.",
    },
    {
        "name": "confidence",
        "flag": "--confidence",
        "kind": "int",
        "section": "## Verified",
        "help": "Confidence in the checkpoint, if the project tracks it.",
    },
    {
        "name": "open",
        "flag": "--open",
        "kind": "str",
        "section": "## Open",
        "help": "An open question, used with settled_by.",
    },
    {
        "name": "settled_by",
        "flag": "--settled-by",
        "kind": "str",
        "section": "## Open",
        "help": "The test/check that would settle the open question.",
    },
    {
        "name": "close",
        "flag": "--close",
        "kind": "int",
        "section": "## Open",
        "help": "Number of an open question to close (requires check and by).",
    },
)

# `from_contract` takes an OPTIONAL value ("true" or a path), so it is not in
# NOTE_PARAMS: a plain string flag cannot express `nargs="?"`, and the tool has
# to distinguish "omitted" from "false". Declared here so consumers can point at
# one place when they need its name.
FROM_CONTRACT = {
    "name": "from_contract",
    "flag": "--from-contract",
    "kind": "str",
    "help": (
        "Seed Goal/Phase/Claims/Next from a contract: 'true' uses .riel/contract.md, "
        "or pass an explicit path. Omit to write entries by hand."
    ),
}

PARAM_NAMES = tuple(param["name"] for param in NOTE_PARAMS) + (FROM_CONTRACT["name"],)