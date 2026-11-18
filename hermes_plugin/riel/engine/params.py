"""The ONE declaration of `riel_note`'s parameters (riel-run/v1).

Three places encode this set: the JSON schema the model reads, the flag
mapping the handler applies, and the argparse parser the engine builds.
This file is the single source; the three consumers derive from it.

Each record is:

    name    — the tool parameter and the schema property
    flag    — the engine's CLI flag
    kind    — "str" | "int" (the type both the schema and argparse use)
    repeat  — True when the flag may repeat (argparse action="append")
    help    — the schema description AND the argparse help, one text
    section — the run.md `## section` the entry lands in

The v2 surface is deliberately SMALL: `note` is the only state writer, and
it can NOT create goals, nexts, phases or claims; it can not self-supply an
exit code (the engine runs `--command` and captures the real one); there is
no verify_with, check, by, from_contract or source — those were v1 concepts
and riel 2.0 has no converter.

Stdlib only, no imports: the engine loads it as a sibling script and the
package loads it by path.
"""

NOTE_PARAMS = (
    {
        "name": "gate",
        "flag": "--gate",
        "kind": "str",
        "repeat": True,
        "section": "## Evidence",
        "help": (
            "Gate id (G#) this evidence completes; repeatable. Requires "
            "--command and --covering."
        ),
    },
    {
        "name": "claim",
        "flag": "--claim",
        "kind": "str",
        "repeat": True,
        "section": "## Evidence",
        "help": (
            "Existing claim id (P#) the evidence covers; repeatable. Claims "
            "are created in the definition, never by note."
        ),
    },
    {
        "name": "command",
        "flag": "--command",
        "kind": "str",
        "section": "## Evidence",
        "help": (
            "Shell command the engine executes in the worktree to produce "
            "the evidence; the real exit code is captured, never supplied."
        ),
    },
    {
        "name": "covering",
        "flag": "--covering",
        "kind": "str",
        "section": "## Evidence",
        "help": "What scope the command actually covers.",
    },
    {
        "name": "confidence",
        "flag": "--confidence",
        "kind": "int",
        "section": "## Evidence",
        "help": (
            "Optional confidence 1..20 (default: absent). Exit 0 with "
            "confidence >= 12 counts as passed."
        ),
    },
    {
        "name": "core",
        "flag": "--core",
        "kind": "str",
        "section": "## Core",
        "help": (
            "A load-bearing fact the receiver must know, as 'name — fact'."
        ),
    },
    {
        "name": "core_slot",
        "flag": "--core-slot",
        "kind": "int",
        "section": "## Core",
        "help": "Which Core slot to write (1-BASED); omit to append.",
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
        "help": "The cheapest test that would settle the open question.",
    },
    {
        "name": "close",
        "flag": "--close",
        "kind": "int",
        "section": "## Open",
        "help": "Number N of Q<N> to close (requires --evidence N).",
    },
    {
        "name": "evidence",
        "flag": "--evidence",
        "kind": "int",
        "section": "## Open",
        "help": "Number N of E<N> that settles the question closed by --close N.",
    },
)

PARAM_NAMES = tuple(param["name"] for param in NOTE_PARAMS)
