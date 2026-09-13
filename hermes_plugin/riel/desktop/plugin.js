// Riel — desktop half: two statusbar chips for the focused session's worktree.
//
//   Riel ✓4 ?2        — the ledger: verified checkpoints (✓, primary color) and
//                       open questions (?, amber). Click: toast with Goal/Next.
//   Contrato          — only when .riel/contract.md exists. Click: modal with
//                       the contract rendered as Markdown (Streamdown draws the
//                       sections and the mermaid graph, the chat pipeline).
//
// Style: native statusbar vocabulary — Capitalized label in
// text-(--ui-text-tertiary) at 0.6875rem, color ONLY on the ✓/? marks
// (primary / amber-600, the two accents the bar itself uses).
//
// Session-awareness: the chips follow the FOCUSED chat. `host.state.cwd` is a
// workspace-global that can still hold the previous conversation's folder right
// after a switch (the app's own store docs it), and a detached session never
// republishes it. So the authoritative worktree comes from the gateway's
// `session.info` events (cwd + session_id), captured per focused session and
// re-adopted on focus switch; `host.state.cwd` is only the seed while nothing
// better has arrived.
//
// Opt-in: `defaultEnabled: false` ships it inventory-only in Capabilities →
// Plugins, mirroring the agent half's `plugins.enabled` gate in config.yaml.

import { host, haptic, useValue } from '@hermes/plugin-sdk'
import { Streamdown } from '@hermes/plugin-sdk'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

const POLL_MS = 5000
const NEXT_MAX_CHARS = 40
const TOOL_MAX_CHARS = 18
const CHIP_CLASS = 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) transition-colors'
const CHECK_CLASS = 'text-primary'
const OPEN_CLASS = 'text-amber-600'
const RUNNING_CLASS = 'text-primary animate-pulse'

function truncate(text, max) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? clean.slice(0, max - 1) + '…' : clean
}

/* ------------------------------------------------------------------ ledger */

/** One detail section: heading + bullet list, only when there is content. */
function DetailSection({ heading, items, mark, markClass }) {
  if (!items || !items.length) return null
  return jsxs('div', {
    className: 'flex flex-col gap-0.5',
    children: [
      jsx('div', {
        className: 'pt-1 text-[0.6875rem] font-medium tracking-wide text-(--ui-text-quaternary)',
        children: heading
      }),
      ...items.map((text, i) =>
        jsxs('div', {
          // break-words: a ✓ line carries the whole checkpoint (claim + evidence)
          // and must WRAP, not truncate with an ellipsis.
          className: 'flex items-baseline gap-1.5 leading-snug break-words',
          children: [
            mark
              ? jsx('span', { className: 'shrink-0 ' + (markClass || ''), children: mark })
              : null,
            jsx('span', { className: 'min-w-0 flex-1 text-(--ui-text-secondary)', children: text })
          ]
        }, i)
      )
    ]
  })
}

/** The ledger's popover body: everything the ledger has, like `rielctl seam`. */
function LedgerPanel({ ledger, busy, tool }) {
  const row = (label, value, valueClass) =>
    jsxs('div', {
      className: 'flex items-baseline justify-between gap-3 py-0.5',
      children: [
        jsx('span', { className: 'shrink-0 text-(--ui-text-quaternary)', children: label }),
        jsx('span', { className: valueClass || 'text-right text-(--ui-text-secondary)', children: value })
      ]
    })

  if (!ledger) {
    return jsx('div', {
      className: 'px-2 py-3 text-center text-xs text-(--ui-text-quaternary)',
      children: 'Este worktree no tiene .riel/ledger.md'
    })
  }

  const stale = ledger.stale_secs == null ? '' : ` · hace ${Math.round(ledger.stale_secs / 60)} min`
  return jsxs('div', {
    className: 'flex flex-col gap-1.5 px-1 py-0.5 text-xs',
    children: [
      ledger.phase
        ? jsx('div', { className: 'text-(--ui-text-quaternary)', children: `Fase: ${ledger.phase}` })
        : null,
      jsx('div', { className: 'font-medium text-(--ui-text-primary)', children: ledger.goal || '(sin goal)' }),
      jsxs('div', { className: 'flex items-baseline gap-1.5 text-(--ui-text-secondary)', children: [
        jsx('span', { className: 'text-(--ui-text-quaternary)', children: '→' }),
        jsx('span', { children: ledger.next || '(sin next)' })
      ]}),
      jsx('div', { className: 'mt-1 border-t border-(--ui-stroke-secondary) pt-1.5' }),
      row('Verificados', ledger.verified, 'text-right tabular-nums text-primary'),
      row('Abiertas', ledger.open, 'text-right tabular-nums ' + (ledger.open > 0 ? OPEN_CLASS : '')),
      row('Claims', ledger.claims, 'text-right tabular-nums'),
      busy
        ? row('Turno', 'en curso' + (tool ? `: ${tool.name}` : ''), 'text-right')
        : tool
          ? row('Último tool', `${tool.name}${tool.duration_s != null ? ` (${tool.duration_s}s)` : ''}${tool.error ? ' — error' : ''}`, 'text-right')
          : null,
      stale
        ? jsx('div', { className: 'text-(--ui-text-quaternary)', children: stale.replace(' · ', '') })
        : null,
      jsx(DetailSection, {
        heading: 'Verificados',
        items: ledger.verified_detail,
        mark: '✓',
        markClass: CHECK_CLASS
      }),
      jsx(DetailSection, {
        heading: 'Abiertas',
        items: ledger.open_detail,
        mark: '?',
        markClass: OPEN_CLASS
      }),
      jsx(DetailSection, {
        heading: 'Claims',
        items: ledger.claims_detail,
        mark: '·'
      })
    ]
  })
}

function LedgerChip({ ledger, busy, tool }) {
  const [open, setOpen] = useState(false)

  const title = () => {
    const lines = []
    if (ledger) {
      lines.push(ledger.goal || '(sin goal)', `→ ${ledger.next || '(sin next)'}`)
      const stale = ledger.stale_secs == null ? '' : ` · hace ${Math.round(ledger.stale_secs / 60)} min`
      lines.push(`${ledger.verified} verificados · ${ledger.open} abiertas · ${ledger.claims} claims${stale}`)
    } else {
      lines.push('Este worktree no tiene .riel/ledger.md')
    }
    if (busy) lines.push('Turno en curso' + (tool ? `: ${tool.name}` : ''))
    else if (tool) {
      const took = tool.duration_s == null ? '' : ` (${tool.duration_s}s)`
      lines.push(`Último tool: ${tool.name}${took}${tool.error ? ' — ' + truncate(tool.error, 80) : ''}`)
    }
    lines.push('clic: ver el ledger')
    return lines.join('\n')
  }

  return jsxs(Dialog, {
    open,
    onOpenChange: setOpen,
    children: [
      jsx('button', {
        key: 'trigger',
        type: 'button',
        title: title(),
        className: CHIP_CLASS,
        onClick: () => setOpen(true),
        children: jsxs('span', {
          className: 'inline-flex items-center gap-1',
          children: [
            jsx('span', { children: 'Riel: Ledger' }),
            busy ? jsx('span', { className: RUNNING_CLASS, children: '●' }) : null,
            ledger
              ? jsxs('span', {
                  className: 'inline-flex items-center gap-1 tabular-nums',
                  children: [
                    jsx('span', { className: CHECK_CLASS, children: `✓${ledger.verified}` }),
                    ledger.open > 0
                      ? jsx('span', { className: OPEN_CLASS, children: `?${ledger.open}` })
                      : null
                  ]
                })
              : null
          ]
        })
      }),
      jsx(DialogContent, {
        key: 'content',
        className: 'flex max-h-[85vh] max-w-2xl flex-col overflow-hidden',
        children: [
          jsx(DialogHeader, {
            key: 'head',
            children: [
              jsx(DialogTitle, { key: 't', children: 'Riel · Ledger' }),
              jsx(DialogDescription, {
                key: 'd',
                className: 'text-(--ui-text-tertiary)',
                children: ledger
                  ? `${ledger.verified}✓ ${ledger.open}? ${ledger.claims} claims`
                  : 'sin ledger en este worktree'
              })
            ]
          }),
          jsx('div', {
            key: 'body',
            className: 'min-h-0 flex-1 overflow-y-auto pr-1',
            children: jsx(LedgerPanel, { ledger, busy, tool })
          })
        ]
      })
    ]
  })
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

function ContractChip({ ctx, cwd, sessionId }) {
  const [hasContract, setHasContract] = useState(null)
  const [open, setOpen] = useState(false)

  // Probe for the contract once per worktree/session: the chip only exists
  // when there is something to show.
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
  }, [cwd, sessionId, ctx])

  if (!hasContract) return null

  return jsxs('span', {
    className: 'inline-flex items-center',
    children: [
      jsx('button', {
        key: 'btn',
        type: 'button',
        title: 'Ver el contrato de esta tarea (secciones + grafo)',
        className: CHIP_CLASS,
        onClick: () => setOpen(true),
        children: 'Riel: Contract'
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
  const [status, setStatus] = useState(null)
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
    setStatus(null)
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

  useEffect(() => {
    let alive = true
    const load = async () => {
      if (!cwd) {
        if (alive) setStatus({ present: false })
        return
      }
      try {
        const data = await ctx.rest('/ledger?worktree=' + encodeURIComponent(cwd))
        if (alive) setStatus(data)
      } catch (error) {
        if (alive) setStatus({ present: false, error: String((error && error.message) || error) })
      }
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [cwd, focusedId, revision, ctx])

  const ledger = status && status.present ? status : null

  return jsxs('span', {
    className: 'inline-flex items-center',
    children: [
      jsx(LedgerChip, { key: 'ledger', ledger, busy, tool }),
      jsx(ContractChip, { key: 'contract', ctx, cwd, sessionId: focusedId })
    ]
  })
}

export default {
  id: 'riel',
  name: 'Riel',
  defaultEnabled: false,
  register(ctx) {
    ctx.register({
      id: 'ledger-chip',
      area: 'statusBar.right',
      order: 120,
      render: () => jsx(RielChips, { ctx })
    })
  }
}
