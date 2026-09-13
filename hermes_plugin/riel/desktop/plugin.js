// Riel — desktop half: a statusbar chip with the live ledger of the current
// worktree AND what the agent is doing right now. Clicking it opens the
// task's contract.md, rendered as Markdown (Streamdown draws the sections and
// the mermaid graph — the same pipeline core chat surfaces use).
//
// Data paths:
//   * state  — host.state.cwd → ctx.rest('/ledger') → the plugin's own Python
//     backend → the vendored `rielctl todo` mirror (polled, and refetched the
//     moment a tool finishes, so the counters catch up fast).
//   * activity — host.onEvent('tool.start' | 'tool.complete'), the app's
//     gateway event tap: turn-in-progress comes from host.state.busy.
//   * contract — the same backend, GET /contract, verbatim markdown.
// The renderer never reads the filesystem.
//
// App-level by design: the chip is one app-wide surface, so activity is not
// filtered per tile — it shows the most recent tool the app saw.
//
// Opt-in: `defaultEnabled: false` ships it inventory-only in Capabilities →
// Plugins, mirroring the agent half's `plugins.enabled` gate in config.yaml.

import { host, haptic, useValue } from '@hermes/plugin-sdk'
import { Streamdown } from '@hermes/plugin-sdk'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

const POLL_MS = 5000
const NEXT_MAX_CHARS = 34
const TOOL_MAX_CHARS = 18
const CHIP_CLASS = 'px-1.5 text-[0.6875rem] tabular-nums'

function truncate(text, max) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? clean.slice(0, max - 1) + '…' : clean
}

/** The chip's one-line label: activity wins while a turn is running. */
function chipLabel(ledger, busy, tool) {
  const counters = ledger ? `${ledger.verified}✓ ${ledger.open}?` : ''
  if (busy) {
    const doing = tool ? (tool.running ? tool.name : `${tool.name} ✓`) : 'pensando'
    return `riel ● ${truncate(doing, TOOL_MAX_CHARS)}${counters ? ' · ' + counters : ''}`
  }
  if (ledger) return `riel ${counters} · ${truncate(ledger.next || ledger.goal, NEXT_MAX_CHARS)}`
  return tool ? `riel · último: ${truncate(tool.name, TOOL_MAX_CHARS)}` : 'riel · sin ledger'
}

/** Tooltip: the ledger headlines, then the activity detail. */
function chipTitle(ledger, busy, tool) {
  const lines = []
  if (ledger) {
    lines.push(ledger.goal || '(sin goal)', `→ ${ledger.next || '(sin next)'}`)
    const stale = ledger.stale_secs == null ? '' : ` · hace ${Math.round(ledger.stale_secs / 60)} min`
    lines.push(`${ledger.verified}✓ ${ledger.open}? ${ledger.claims}P${stale}`)
  } else {
    lines.push('Este worktree no tiene .riel/ledger.md')
  }
  if (busy) lines.push('turno en curso')
  if (tool) {
    const took = tool.running ? '' : tool.duration_s == null ? '' : ` (${tool.duration_s}s)`
    lines.push(`último tool: ${tool.name}${took}${tool.error ? ' — error: ' + truncate(tool.error, 80) : ''}`)
  }
  lines.push('clic: ver el contrato')
  return lines.join('\n')
}

function ContractDialog({ open, onOpenChange, cwd }) {
  const [contract, setContract] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setContract(null)
    const load = async () => {
      try {
        const data = await globalThis.__rielCtx.rest(
          '/contract?worktree=' + encodeURIComponent(cwd || '')
        )
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
  }, [open, cwd])

  const body = () => {
    if (loading) return jsx('div', { className: 'py-8 text-center text-sm text-(--ui-text-tertiary)', children: 'cargando contrato…' })
    if (!contract) return null
    if (!contract.present) {
      return jsx('div', {
        className: 'py-8 text-center text-sm text-(--ui-text-tertiary)',
        children: contract.error || 'sin contrato en este worktree'
      })
    }
    return jsx('div', {
      className: 'max-h-[70vh] overflow-y-auto rounded-md border border-(--ui-stroke-secondary) bg-(--ui-background) p-4 text-sm',
      children: jsx(Streamdown, { children: contract.markdown })
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
            jsx(DialogTitle, { key: 't', children: 'Contrato Riel' }),
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

function RielChip({ ctx }) {
  const cwd = useValue(host.state.cwd)
  const busy = useValue(host.state.busy)
  const [status, setStatus] = useState(null)
  const [tool, setTool] = useState(null)
  const [revision, setRevision] = useState(0)
  const [dialogOpen, setDialogOpen] = useState(false)

  // The dialog fetches through the plugin context; reach it from its effect.
  globalThis.__rielCtx = ctx

  // Activity: the app's gateway event tap. Every finished tool bumps `revision`
  // so the ledger is re-read immediately instead of at the next poll.
  useEffect(() => {
    const started = host.onEvent('tool.start', event => {
      const name = (event && event.payload && event.payload.name) || 'tool'
      setTool({ name, running: true })
    })
    const completed = host.onEvent('tool.complete', event => {
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
  }, [cwd, revision, ctx])

  const ledger = status && status.present ? status : null
  const onClick = () => setDialogOpen(true)

  const className = busy
    ? `${CHIP_CLASS} text-(--ui-accent)`
    : ledger
      ? `${CHIP_CLASS} text-(--ui-text-tertiary)`
      : `${CHIP_CLASS} text-(--ui-text-quaternary)`

  return jsx('span', {
    className: 'inline-flex items-center',
    children: [
      jsx('button', {
        key: 'chip',
        type: 'button',
        title: chipTitle(ledger, busy, tool),
        className,
        onClick,
        children: chipLabel(ledger, busy, tool)
      }),
      jsx(ContractDialog, {
        key: 'dialog',
        open: dialogOpen,
        onOpenChange: setDialogOpen,
        cwd
      })
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
      render: () => jsx(RielChip, { ctx })
    })
  }
}
