"""Riel — Hermes plugin registration.

The package is the whole product: the six skills (`skills/`, bundled from the
repo by `make plugin-skills`), the `rielctl` they call, the ledger/contract
tools, the `pre_verify` gate and the desktop chip.

The prose reaches the agent two ways, because they answer different questions:
`register_skill` puts each SKILL.md behind `skill_view("riel:<short>")` (the
bodies, by tool), and the `riel` prompt section publishes the INDEX — the six
one-line triggers plus the worktree's ledger state. Neither one alone is enough:
a plugin-registered skill never enters `<available_skills>`, so without the
section the agent would have no reason to look.
"""

import logging

from . import commands, hooks, schemas, section, tools

logger = logging.getLogger(__name__)


def _group_check(key: str):
    """`check_fn` for one group: the tool leaves the model's surface while it is off.

    Registered UNCACHED: a config-backed probe must not serve a stale verdict for
    the ~30s TTL (plus the last-good grace window), or turning a group off looks
    like it did nothing. Fail-open — an unreadable config keeps the tool.
    """

    def _enabled() -> bool:
        try:
            return tools.plugin_settings().read_bool(key, True)
        except Exception:
            return True

    try:
        from tools.registry import no_cache_check_fn

        return no_cache_check_fn(_enabled)
    except Exception:  # pragma: no cover - Hermes absent (repo suite)
        return _enabled


def register(ctx) -> None:
    """Wire schemas to handlers, the prose, the switches and the gate. Called once at startup."""
    # Install defaults, recorded once: the callbacks read the LIVE value per call
    # (`plugins.entries.riel.settings.*`), so a chip toggle lands on the next turn.
    hooks.SETTINGS["enabled"] = bool(ctx.get_config("gate", default=True))
    hooks.SETTINGS["attempts"] = int(ctx.get_config("gate_attempts", default=1) or 1)

    for schema in schemas.SCHEMAS:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset="riel",
            schema=schema,
            handler=tools.HANDLERS[name],
            check_fn=_group_check("tools"),
        )
    for skill_name, skill_path, description in section.skill_entries():
        try:
            ctx.register_skill(skill_name, skill_path, description)
        except Exception as exc:
            logger.warning("riel: could not register the skill %s: %s", skill_name, exc)
    try:
        ctx.register_system_prompt_section(
            section.SECTION_ID,
            section.render,
            position="after_memory",
            max_chars=section.SECTION_MAX_CHARS,
        )
    except Exception as exc:
        logger.warning("riel: could not register the prompt section: %s", exc)
    try:
        ctx.register_command(
            "riel",
            commands.handle,
            description="Riel's switches: status, on/off <gate|tools|context>, note <text>.",
            args_hint="[status|on|off|note] [group|text]",
        )
    except Exception as exc:
        logger.warning("riel: could not register the /riel command: %s", exc)
    ctx.register_hook("pre_verify", hooks.pre_verify)
    logger.debug(
        "riel: registered %d tools and the pre_verify gate (enabled=%s, attempts=%s)",
        len(schemas.SCHEMAS),
        hooks.SETTINGS["enabled"],
        hooks.SETTINGS["attempts"],
    )
