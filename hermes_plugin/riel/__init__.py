"""Riel — Hermes plugin registration.

Machinery only: this plugin exposes the ledger/contract tooling (`riel_note`,
`riel_seam`, `riel_resume`, `riel_todo`) on top of a vendored `rielctl`. The
protocol prose — the six `riel-*` skills — is NOT shipped here; it installs as
a skill tap from this same repo:

    hermes skills tap add alvarolizama/riel

Keeping the prose out of the plugin avoids a second copy of the markdown: the
plugin's jobs are tools, hooks and (later) desktop UI.
"""

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Wire schemas to handlers. Called once at startup."""
    for schema in schemas.SCHEMAS:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset="riel",
            schema=schema,
            handler=tools.HANDLERS[name],
        )
    logger.debug("riel: registered %d tools", len(schemas.SCHEMAS))
