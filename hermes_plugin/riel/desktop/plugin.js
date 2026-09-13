// Riel — desktop half: a statusbar chip with the live ledger of the current worktree.
//
// Data path: host.state.cwd (the app's worktree) → ctx.rest('/ledger') → the
// plugin's own Python backend → the vendored `rielctl todo` mirror. The
// renderer never reads the filesystem.
//
// Opt-in: `defaultEnabled: false` ships it inventory-only in Capabilities →
// Plugins, mirroring the agent half's `plugins.enabled` gate in config.yaml.

import { host, haptic, useValue } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

const POLL_MS = 5000
const NEXT_MAX_CHARS = 34
const CHIP_CLASS = 'px-1.5 text-[0.6875rem] tabular-nums'

function truncate(text, max) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? clean.slice(0, max - 1) + '…' : clean
}

function RielChip({ ctx }) {
  const cwd = useValue(host.state.cwd)
  const [status, setStatus] = useState(null)

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
  }, [cwd, ctx])

  const ledger = status && status.present ? status : null
  const label = ledger
    ? `riel ${ledger.verified}✓ ${ledger.open}? · ${truncate(ledger.next || ledger.goal, NEXT_MAX_CHARS)}`
    : 'riel · sin ledger'

  const detail = ledger
    ? `${ledger.goal || '(sin goal)'}\n→ ${ledger.next || '(sin next)'}`
    : (status && status.error) || 'Riel: este worktree no tiene .riel/ledger.md'

  const onClick = () => {
    haptic('tap')
    host.notify({
      kind: ledger ? 'info' : 'warning',
      message: ledger
        ? `${truncate(ledger.goal, 120)} → ${truncate(ledger.next, 120)}`
        : `Sin ledger en ${cwd || '(sin worktree)'}`
    })
  }

  return jsx('button', {
    type: 'button',
    title: detail,
    className: ledger ? `${CHIP_CLASS} text-(--ui-text-tertiary)` : `${CHIP_CLASS} text-(--ui-text-quaternary)`,
    onClick,
    children: label
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
