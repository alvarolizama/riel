// Riel — desktop half: ONE statusbar chip for the focused session's worktree.
//
//   Riel ● riel_note   — only when .riel/contract.md exists. Click: modal with
//                        the contract rendered as Markdown (Streamdown draws
//                        the sections and the mermaid graph, the chat
//                        pipeline). While the turn runs: a pulsing dot plus
//                        the live tool name. No contract: no chip at all.
//
// The ledger's own state is NOT in the bar anymore: the model re-reads it
// with riel_seam and the gate enforces it — the bar only says whether this
// worktree has a plan and whether it is being executed.
//
// Style: native statusbar vocabulary — Capitalized label in
// text-(--ui-text-tertiary) at 0.6875rem, color ONLY on the live mark
// (primary, the accent the bar itself uses).
//
// Session-awareness: the chip follows the FOCUSED chat. `host.state.cwd` is a
// workspace-global that can still hold the previous conversation's folder right
// after a switch (the app's own store docs it), and a detached session never
// republishes it. So the authoritative worktree comes from the gateway's
// `session.info` events (cwd + session_id), captured per focused session and
// re-adopted on focus switch; `host.state.cwd` is only the seed while nothing
// better has arrived.
//
// Opt-in: `defaultEnabled: false` ships it inventory-only in Capabilities →
// Plugins, mirroring the agent half's `plugins.enabled` gate in config.yaml.

import { host, useValue } from '@hermes/plugin-sdk'
import { Streamdown } from '@hermes/plugin-sdk'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, PALETTE_AREA } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

const TOOL_MAX_CHARS = 18
const CHIP_CLASS = 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) transition-colors'
const RUNNING_CLASS = 'text-primary animate-pulse'

function truncate(text, max) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? clean.slice(0, max - 1) + '…' : clean
}

/* --------------------------------------------------------------- contrato */

function ContractDialog({ open, onOpenChange, ctx, cwd, sessionId }) {
  const [contract, setContract] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setContract(null)
    const load = async () => {
      try {
        const data = await ctx.rest('/contract?worktree=' + encodeURIComponent(cwd || ''))
        if (alive) setContract(data)
      } catch (error) {
        if (alive) {
          setContract({ present: false, error: String((error && error.message) || error) })
        }
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [open, cwd, sessionId, ctx])

  const body = () => {
    if (loading) return jsx('div', { className: 'py-8 text-center text-sm text-(--ui-text-tertiary)', children: 'Cargando contrato…' })
    if (!contract) return null
    if (!contract.present) {
      return jsx('div', {
        className: 'py-8 text-center text-sm text-(--ui-text-tertiary)',
        children: contract.error || 'Sin contrato en este worktree'
      })
    }
    return jsx('div', {
      className: 'max-h-[70vh] overflow-y-auto rounded-md border border-(--ui-stroke-secondary) bg-(--ui-background) p-4 text-sm',
      children: jsx(Streamdown, {
        // mermaid is OFF by default in Streamdown (context default `void 0` —
        // the fence then falls through to a plain code block). Passing the
        // options object turns the lazy diagram renderer on.
        mermaid: {},
        children: contract.markdown
      })
    })
  }

  return jsx(Dialog, {
    open,
    onOpenChange,
    children: jsx(DialogContent, {
      className: 'max-w-3xl',
      children: [
        jsx(DialogHeader, {
          key: 'head',
          children: [
            jsx(DialogTitle, { key: 't', children: 'Riel · Contract' }),
            jsx(DialogDescription, {
              key: 'd',
              className: 'truncate text-(--ui-text-tertiary)',
              children: cwd || ''
            })
          ]
        }),
        jsx('div', { key: 'body', children: body() })
      ]
    })
  })
}

/** The one chip: it only exists when the worktree has a contract.

 *  - idle: `Riel` — the plan exists, click reads it.
 *  - turn running: `Riel ● <tool>` — the pulsing dot plus the live tool name.
 *  - no contract: nothing at all.
 */
function ContractChip({ ctx, cwd, sessionId, busy, tool, revision }) {
  const [hasContract, setHasContract] = useState(null)
  const [open, setOpen] = useState(false)

  // Probe for the contract once per worktree/session (and again whenever a
  // tool finishes — a contract may have been written mid-task): the chip only
  // exists when there is something to show.
  useEffect(() => {
    let alive = true
    setHasContract(null)
    if (!cwd) {
      setHasContract(false)
      return
    }
    const probe = async () => {
      try {
        const data = await ctx.rest('/contract?worktree=' + encodeURIComponent(cwd))
        if (alive) setHasContract(Boolean(data && data.present))
      } catch {
        if (alive) setHasContract(false)
      }
    }
    probe()
    return () => {
      alive = false
    }
  }, [cwd, sessionId, revision, ctx])

  if (!hasContract) return null

  const title = () => {
    const lines = ['Ver el contrato de esta tarea (secciones + grafo)']
    if (busy) lines.push('Turno en curso' + (tool ? `: ${tool.name}` : ''))
    return lines.join('\n')
  }

  return jsxs('span', {
    className: 'inline-flex items-center',
    children: [
      jsx('button', {
        key: 'btn',
        type: 'button',
        title: title(),
        className: CHIP_CLASS,
        onClick: () => setOpen(true),
        children: jsxs('span', {
          className: 'inline-flex items-center gap-1',
          children: [
            jsx('span', { children: 'Riel' }),
            busy
              ? jsxs('span', {
                  className: 'inline-flex items-center gap-1',
                  children: [
                    jsx('span', { className: RUNNING_CLASS, children: '●' }),
                    tool && tool.running
                      ? jsx('span', { className: 'text-primary', children: truncate(tool.name, TOOL_MAX_CHARS) })
                      : null
                  ]
                })
              : null
          ]
        })
      }),
      jsx(ContractDialog, {
        key: 'dialog',
        open,
        onOpenChange: setOpen,
        ctx,
        cwd,
        sessionId
      })
    ]
  })
}

/* ------------------------------------------------------------------- host */

function RielChips({ ctx }) {
  const globalCwd = useValue(host.state.cwd)
  const busy = useValue(host.state.busy)
  const focusedId = useValue(host.state.focusedSessionId)
  const focusedStoredId = useValue(host.state.focusedStoredSessionId)
  const [tool, setTool] = useState(null)
  const [revision, setRevision] = useState(0)
  // Authoritative cwd PER session. session.info events (keyed by runtime id)
  // seed it live; the stored-id fallback below fills sessions that never
  // reported. Either way, the map only answers for the focused session.
  const [cwdBySession, setCwdBySession] = useState({})
  const focusedCwd = (focusedId && cwdBySession[focusedId])
    || (focusedStoredId && cwdBySession[focusedStoredId])
    || ''
  const cwd = focusedCwd || globalCwd

  // session.info: the gateway telling us a session's real cwd (and branch).
  // Stored under the REPORTING session's id — background sessions included,
  // their entry just never gets read while another session is focused.
  useEffect(() => {
    const off = host.onEvent('session.info', event => {
      const sid = event && event.session_id
      const cwd = event && event.payload && event.payload.cwd
      if (!sid || !cwd) return
      setCwdBySession(prev => (prev[sid] === cwd ? prev : { ...prev, [sid]: cwd }))
    })
    return off
  }, [])

  // Activity: the app's gateway event tap, FILTERED to the focused session.
  // A finished tool bumps the revision so the chip re-probes the contract —
  // one written mid-task shows up without waiting for a focus switch.
  useEffect(() => {
    const belongs = event => {
      const sid = event && event.session_id
      return !sid || sid === host.state.focusedSessionId.get()
    }
    const started = host.onEvent('tool.start', event => {
      if (!belongs(event)) return
      const name = (event && event.payload && event.payload.name) || 'tool'
      setTool({ name, running: true })
    })
    const completed = host.onEvent('tool.complete', event => {
      if (!belongs(event)) return
      const payload = (event && event.payload) || {}
      setTool({
        name: payload.name || 'tool',
        running: false,
        duration_s: payload.duration_s,
        error: payload.error
      })
      setRevision(current => current + 1)
    })
    return () => {
      started()
      completed()
    }
  }, [])

  // Focus switch: clear the stale state, then resolve the NEW session's
  // worktree. session.info events seed the map as sessions report; for a
  // session that never reported (detached, older), ask the plugin's backend,
  // which reads the stored cwd from the session DB — the app's own atoms can
  // still hold the previous conversation's folder at this moment.
  useEffect(() => {
    setTool(null)
    if (!focusedStoredId) return
    let alive = true
    const known = cwdBySession[focusedStoredId]
    if (known) return
    const resolve = async () => {
      try {
        // stored id: the one the session DB keys on
        const data = await ctx.rest('/session_cwd?session_id=' + encodeURIComponent(focusedStoredId))
        if (alive && data && data.found && data.cwd) {
          setCwdBySession(prev => (prev[focusedStoredId] === data.cwd ? prev : { ...prev, [focusedStoredId]: data.cwd }))
        }
      } catch {
        // no answer: the seed (global cwd) keeps serving until session.info
      }
    }
    resolve()
    return () => {
      alive = false
    }
  }, [focusedStoredId, ctx])

  return jsx(ContractChip, { ctx, cwd, sessionId: focusedId, busy, tool, revision })
}

export default {
  id: 'riel',
  name: 'Riel',
  defaultEnabled: false,
  register(ctx) {
    const readState = async () => {
      try {
        return (await ctx.rest('/settings')) || {}
      } catch {
        return {}
      }
    }
    const flip = async (key, label) => {
      const current = await readState()
      try {
        const saved = await ctx.rest('/settings', { method: 'POST', body: { [key]: !current[key] } })
        const on = saved && saved.ok ? !!saved[key] : null
        host.notify({
          kind: 'info',
          message: `Riel ${label}: ${on === null ? 'no se pudo escribir' : on ? 'on' : 'off'} — aplica en la próxima sesión`
        })
      } catch (e) {
        host.notify({ kind: 'error', message: `Riel ${label}: ${(e && e.message) || e}` })
      }
    }

    ctx.register({
      id: 'contract-chip',
      area: 'statusBar.right',
      order: 120,
      render: () => jsx(RielChips, { ctx })
    })
    ctx.register({
      id: 'toggle-gate',
      area: PALETTE_AREA,
      data: {
        id: 'riel.toggle-gate',
        label: 'Riel: encender/apagar el gate',
        keywords: ['riel', 'gate', 'ledger', 'verify'],
        run: () => void flip('gate', 'gate')
      }
    })
    ctx.register({
      id: 'toggle-context',
      area: PALETTE_AREA,
      data: {
        id: 'riel.toggle-context',
        label: 'Riel: encender/apagar el bloque del prompt',
        keywords: ['riel', 'prompt', 'section', 'guide'],
        run: () => void flip('context', 'prompt')
      }
    })
  }
}
