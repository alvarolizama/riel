"""Riel — Hermes plugin registration.

Machinery only: this plugin exposes the ledger/contract tooling (`riel_note`,
`riel_seam`, `riel_resume`, `riel_todo`) on top of a vendored `rielctl`, plus the
`pre_verify` gate that keeps a turn from closing with unverified work. The
protocol prose — the six `riel-*` skills — is NOT shipped here; it installs as a
skill tap from this same repo:

    hermes skills tap add alvarolizama/riel

Keeping the prose out of the plugin avoids a second copy of the markdown: the
plugin's jobs are tools, hooks and (later) desktop UI.
"""

import logging

from . import hooks, schemas, tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Wire schemas to handlers and register the gate. Called once at startup."""
    # Settings are read once: a hook runs on the turn's hot path, so it must not
    # hit the config store per call. `plugins.entries.riel.settings.*`.
    hooks.SETTINGS["enabled"] = bool(ctx.get_config("gate", default=True))
    hooks.SETTINGS["attempts"] = int(ctx.get_config("gate_attempts", default=1) or 1)

    for schema in schemas.SCHEMAS:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset="riel",
            schema=schema,
            handler=tools.HANDLERS[name],
        )
    ctx.register_hook("pre_verify", hooks.pre_verify)
    logger.debug(
        "riel: registered %d tools and the pre_verify gate (enabled=%s, attempts=%s)",
        len(schemas.SCHEMAS),
        hooks.SETTINGS["enabled"],
        hooks.SETTINGS["attempts"],
    )
