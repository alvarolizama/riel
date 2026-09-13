"""Regression tests for the Riel desktop half — the statusbar chip.

Three layers, each with the cheapest honest check available:

  * package wiring — manifest/paths, and the two rules the SDK enforces on a
    disk plugin (allowed import specifiers, no hardcoded colors);
  * `ledger_status.read_status` — stdlib-only, driven by the **vendored**
    rielctl against a real temp worktree;
  * the chip itself — the plugin file is loaded by a real Node process against
    stubbed `@hermes/plugin-sdk` / `react` modules, `register()` is called, the
    gateway events are emitted and the component is rendered, so a syntax
    error, a bad import, a broken label or a missing refetch fails here instead
    of silently in the app.

The stub is a tiny stand-in for React's state/effect cells: `useState` keys its
cells by call order (0 = ledger status, 1 = last tool, 2 = refetch revision) and
`useEffect` re-runs a cell after its cleanup. Re-rendering is explicit —
the harness resets the call indexes and invokes the component again — which is
enough to assert what a render produces without pulling in React itself.

The FastAPI route test needs `fastapi` (present in a Hermes venv, absent from a
plain interpreter) and skips without it; `node` is skipped when not installed.

Run:
    python3 -m unittest discover -s tests -v
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"
DASHBOARD = PLUGIN / "dashboard"
DESKTOP = PLUGIN / "desktop"
VENDOR_RIELCTL = PLUGIN / "vendor" / "riel-cli" / "scripts" / "rielctl"

CLIENT_CWD = "/tmp/riel-statusbar-test-worktree"
ALLOWED_SPECIFIERS = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}


def load_module(name, path):
    """Load a module from an arbitrary path (no package import)."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover - SourceFileLoader always yields a spec
        raise RuntimeError(f"could not build a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fastapi_available():
    try:
        import fastapi  # noqa: F401
    except Exception:
        return False
    return True


def _node_available():
    return shutil.which("node") is not None


SDK_STUB = """\
function map() {
  return (globalThis.__RIEL_LISTENERS__ ||= new Map())
}

// Dialog/Streamdown/Popover stubs: they only need to EXIST for the import to
// resolve. `asChild` triggers (PopoverTrigger) must PASS THROUGH their child
// so the walk still finds the real button — Radix does the same.
const makeStub = (tag) => (props) => {
  if (props && props.asChild && props.children) return props.children
  return { tag, props: props || {} }
}

export const host = {
  state: {
    cwd: { get: () => process.env.RIEL_TEST_CWD || '' },
    busy: { get: () => process.env.RIEL_TEST_BUSY === '1' },
    focusedSessionId: { get: () => (globalThis.__RIEL_FOCUS__ ||= process.env.RIEL_TEST_FOCUS || 's1') }
  },
  notify: (payload) => {
    globalThis.__RIEL_NOTIFIED__ = payload
  },
  onEvent: (type, listener) => {
    const listeners = map().get(type) || new Set()
    listeners.add(listener)
    map().set(type, listeners)
    return () => listeners.delete(listener)
  }
}
export const haptic = () => {
  globalThis.__RIEL_TAPPED__ = true
}
export const useValue = (atom) => (atom && typeof atom.get === 'function' ? atom.get() : null)

export const Streamdown = (props) => {
  globalThis.__RIEL_STREAMDOWN_PROPS__ = props || {}
  if (props && props.asChild && props.children) return props.children
  return { tag: 'streamdown', props: props || {} }
}
export const Dialog = makeStub('dialog')
export const DialogContent = makeStub('dialog-content')
export const DialogHeader = makeStub('dialog-header')
export const DialogTitle = makeStub('dialog-title')
export const DialogDescription = makeStub('dialog-description')
export const Popover = makeStub('popover')
export const PopoverContent = makeStub('popover-content')
export const PopoverTrigger = makeStub('popover-trigger')
export const ScrollArea = makeStub('scroll-area')
"""

REACT_STUB = """\
// Cells keyed by call order and persisted on globalThis, so a second render pass
// sees what setState wrote. Good enough to assert render output without React.
export const useState = (initial) => {
  const store = (globalThis.__RIEL_STATE__ ||= [])
  const index = globalThis.__RIEL_INDEX__++
  if (!(index in store)) store[index] = initial
  return [store[index], (value) => {
    store[index] = typeof value === 'function' ? value(store[index]) : value
  }]
}

export const useEffect = (run) => {
  const cleanups = (globalThis.__RIEL_CLEANUPS__ ||= [])
  const index = globalThis.__RIEL_EFFECT_INDEX__++
  if (typeof cleanups[index] === 'function') cleanups[index]()
  const cleanup = run()
  cleanups[index] = typeof cleanup === 'function' ? cleanup : null
}
"""

JSX_STUB = """\
export const jsx = (type, props) => ({ type, props })
export const jsxs = jsx
"""

HARNESS = """\
import plugin from './plugin.mjs'

const ledger = JSON.parse(process.env.RIEL_TEST_LEDGER || 'null')
const tool = JSON.parse(process.env.RIEL_TEST_TOOL || 'null')
let restCalls = 0
const contributions = []
// Path-aware rest stub: /contract answers only when the harness was told a
// contract exists (RIEL_TEST_CONTRACT=1); /ledger always answers the fixture.
const restStub = async (path) => {
  restCalls += 1
  if (path.startsWith('/ledger')) globalThis.__RIEL_LAST_LEDGER_URL__ = path
  if (path.startsWith('/contract')) {
    return process.env.RIEL_TEST_CONTRACT === '1'
      ? { present: true, markdown: '# Task: x' }
      : { present: false }
  }
  return ledger
}

const ctx = {
  rest: restStub,
  register: (contribution) => contributions.push(contribution)
}

plugin.register(ctx)
const chip = contributions.find((c) => c.area === 'statusBar.right')
if (!chip || typeof chip.render !== 'function') {
  console.error('FAIL: no statusBar.right contribution with a render')
  process.exit(2)
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
const emit = (type, event) => {
  for (const listener of (globalThis.__RIEL_LISTENERS__ || new Map()).get(type) || []) listener(event)
}
const render = () => {
  globalThis.__RIEL_INDEX__ = 0
  globalThis.__RIEL_EFFECT_INDEX__ = 0
  const element = chip.render()
  const tree = instantiate(element)
  return { tree, button: findLedgerButton(tree) || tree }
}

// Minimal React: function components arrive UNINVOKED — call them (depth-capped)
// so the assertion walks real DOM-ish nodes, the same way React would.
const instantiate = (node, depth = 0) => {
  if (depth > 8 || !node || typeof node !== 'object') return node
  if (typeof node.type === 'function') {
    return instantiate(node.type(node.props), depth + 1)
  }
  const children = node.props && node.props.children
  if (Array.isArray(children)) {
    return { ...node, props: { ...node.props, children: children.map((c) => instantiate(c, depth + 1)) } }
  }
  if (children && typeof children === 'object') {
    return { ...node, props: { ...node.props, children: instantiate(children, depth + 1) } }
  }
  return node
}

// The chips render as nested spans. Walk for the FIRST button that has an
// onClick handler OR is the ledger trigger (the Popover wraps it now — Radix
// passes asChild through, but the stub doesn't, so we accept either shape).
const findLedgerButton = (node) => {
  if (!node || typeof node !== 'object') return null
  if (node.type === 'button') return node
  const children = node.props && node.props.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findLedgerButton(child)
      if (found) return found
    }
  } else if (children && typeof children === 'object') {
    return findLedgerButton(children)
  }
  return null
}

const first = render()
await tick()   // let the ledger effect's first fetch land before asserting
const firstAfterFetch = render()
if (tool) emit('tool.start', { payload: { name: tool, tool_id: 't1' }, session_id: 's1' })
await tick()
const withActivity = render()

// session.info events: the focused session's own cwd report, then optionally a
// FOREIGN session reporting a different one — the chip must keep the focused's.
// Each report is followed by a re-render (the stub's setState does not schedule
// one) plus a tool.complete to bump the ledger-refetch revision.
if (process.env.RIEL_TEST_INFO_CWD) {
  const sid = process.env.RIEL_TEST_INFO_SESSION || 's1'
  emit('session.info', { payload: { cwd: process.env.RIEL_TEST_INFO_CWD }, session_id: sid })
  await tick()
  emit('tool.complete', { payload: { name: 'refetch', tool_id: 't2' }, session_id: sid })
  await tick()
  render()
}
if (process.env.RIEL_TEST_FOREIGN_INFO) {
  emit('session.info', { payload: { cwd: process.env.RIEL_TEST_FOREIGN_INFO }, session_id: 's9' })
  await tick()
  emit('tool.complete', { payload: { name: 'refetch2', tool_id: 't3' }, session_id: 's1' })
  await tick()
  render()
}

let afterComplete = null
if (tool && process.env.RIEL_TEST_COMPLETE === '1') {
  emit('tool.complete', { payload: { name: tool, tool_id: 't1', duration_s: 1.4 }, session_id: 's1' })
  await tick()
  afterComplete = render()
}

// Optional mid-run focus switch: the atom changes, effects re-run (cleanup +
// fetch), and the NEXT render must not carry the previous session's state.
let switched = null
if (process.env.RIEL_TEST_SWITCH === '1') {
  globalThis.__RIEL_FOCUS__ = 's2'
  const current = globalThis.__RIEL_INDEX__   // preserve state cells across renders
  const cleanups = globalThis.__RIEL_CLEANUPS__ || []
  // run the focus-change cleanups (the clear effect), then re-render
  for (const cleanup of cleanups) if (typeof cleanup === 'function') cleanup()
  globalThis.__RIEL_CLEANUPS__ = []
  globalThis.__RIEL_INDEX__ = current
  await tick()
  switched = render()
}

const current = switched || afterComplete || withActivity
// The ledger button is now a PopoverTrigger (Radix owns the click): the
// harness toggles the popover state cell directly instead of calling onClick.
if (current.button.props.onClick) current.button.props.onClick()

// The label is now nested spans — flatten to text for the assertions.
const textOf = (node) => {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join(' ')
  if (node && typeof node === 'object' && node.props) return textOf(node.props.children)
  return ''
}
const labelOf = (r) => textOf(r.button.props.children).replace(/\s+/g, ' ').trim()
// Class of the ✓ counter inside the label (color only on the marks).
const checkClassOf = (r) => {
  const walk = (node) => {
    if (!node || typeof node !== 'object' || !node.props) return null
    const cn = node.props.className || ''
    if (String(cn).includes('text-primary') && !String(cn).includes('pulse')) return cn
    for (const child of [].concat(node.props.children || [])) {
      const found = walk(child)
      if (found) return found
    }
    return null
  }
  return walk(r.button)
}
// Is there a Riel: Contract chip next to the ledger one?
const contractVisible = (() => {
  const walk = (node) => {
    if (!node || typeof node !== 'object' || !node.props) return false
    if (textOf(node).includes('Riel: Contract')) return true
    for (const child of [].concat(node.props.children || [])) if (walk(child)) return true
    return false
  }
  return walk(current.tree)
})()

console.log(JSON.stringify({
  id: plugin.id,
  name: plugin.name,
  defaultEnabled: plugin.defaultEnabled,
  areas: contributions.map((c) => c.area),
  order: chip.order,
  session_cwd: (() => {
    // The cwd the chips resolved to, captured from the last /ledger rest call
    const m = /worktree=([^&]+)/.exec(globalThis.__RIEL_LAST_LEDGER_URL__ || '')
    return m ? decodeURIComponent(m[1]) : null
  })(),
  first_label: labelOf(firstAfterFetch),
  activity_label: labelOf(withActivity),
  activity_title: withActivity.button.props.title,
  activity_class: withActivity.button.props.className,
  activity_running_class: (function () {
    const walk = (node) => {
      if (!node || typeof node !== 'object' || !node.props) return null
      const cn = String(node.props.className || '')
      if (cn.includes('pulse')) return cn
      for (const child of [].concat(node.props.children || [])) {
        const found = walk(child)
        if (found) return found
      }
      return null
    }
    return walk(withActivity.button)
  })(),
  check_class: checkClassOf(current),
  contract_visible: contractVisible,
  streamdown_mermaid: (() => {
    // The stub records Streamdown's props whenever it renders. The dialog's
    // body (with the contract markdown) renders it via instantiate above when
    // a contract exists — if the dialog passed the option, it is on record.
    if (process.env.RIEL_TEST_CONTRACT !== '1') return null
    return Boolean(globalThis.__RIEL_STREAMDOWN_PROPS__ && 'mermaid' in globalThis.__RIEL_STREAMDOWN_PROPS__)
  })(),
  final_label: labelOf(current),
  final_title: current.button.props.title,
  rest_calls: restCalls,
  tapped: globalThis.__RIEL_TAPPED__ === true,
  notified: globalThis.__RIEL_NOTIFIED__ || null
}))
process.exit(0)
"""


def _stub_environment(root: Path) -> Path:
    """A minimal `@hermes/plugin-sdk` + `react` so the chip can run under Node."""
    sdk = root / "node_modules" / "@hermes" / "plugin-sdk"
    react = root / "node_modules" / "react"
    sdk.mkdir(parents=True)
    react.mkdir(parents=True)

    (sdk / "package.json").write_text(
        json.dumps({"name": "@hermes/plugin-sdk", "version": "0.0.0", "type": "module", "main": "index.mjs"}),
        encoding="utf-8",
    )
    (sdk / "index.mjs").write_text(SDK_STUB, encoding="utf-8")
    (react / "package.json").write_text(
        json.dumps(
            {
                "name": "react",
                "version": "0.0.0",
                "type": "module",
                "exports": {".": "./index.mjs", "./jsx-runtime": "./jsx-runtime.mjs"},
            }
        ),
        encoding="utf-8",
    )
    (react / "index.mjs").write_text(REACT_STUB, encoding="utf-8")
    (react / "jsx-runtime.mjs").write_text(JSX_STUB, encoding="utf-8")

    (root / "plugin.mjs").write_text((DESKTOP / "plugin.js").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    return root / "harness.mjs"


class DesktopWiringTest(unittest.TestCase):
    """The package halves and the rules the SDK enforces on a disk plugin."""

    def test_package_layout_matches_the_documented_one(self):
        for path in (
            PLUGIN / "plugin.yaml",
            PLUGIN / "__init__.py",
            DASHBOARD / "manifest.json",
            DASHBOARD / "plugin_api.py",
            DESKTOP / "plugin.js",
        ):
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")

    def test_dashboard_manifest_names_the_api_file(self):
        manifest = json.loads((DASHBOARD / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "riel")
        self.assertTrue((DASHBOARD / manifest["api"]).is_file())

    def test_desktop_half_imports_only_allowed_specifiers(self):
        source = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        specifiers = set()
        for line in source.splitlines():
            if line.startswith("import "):
                specifiers.add(line.split("from", 1)[1].strip().strip("'\""))
        self.assertTrue(specifiers)
        self.assertTrue(specifiers <= ALLOWED_SPECIFIERS, specifiers - ALLOWED_SPECIFIERS)

    def test_desktop_half_uses_no_hardcoded_colors(self):
        source = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        for banned in ("#000", "#fff", "black", "white", "rgb(", "hsl("):
            self.assertNotIn(banned, source, f"hardcoded color {banned!r} — use theme vars")


class LedgerStatusTest(unittest.TestCase):
    """`ledger_status` driven through the vendored rielctl."""

    @classmethod
    def setUpClass(cls):
        cls.status = load_module("riel_ledger_status", DASHBOARD / "ledger_status.py")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-status-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, *argv):
        proc = subprocess.run(
            [sys.executable, str(VENDOR_RIELCTL), *argv],
            cwd=self.tmp,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def test_absent_ledger_is_reported_not_invented(self):
        status = self.status.read_status(self.tmp)
        self.assertFalse(status["present"])
        self.assertEqual(status["goal"], "")
        self.assertNotIn("error", status)

    def test_directory_that_does_not_exist_reports_an_error(self):
        status = self.status.read_status(str(Path(self.tmp) / "nope"))
        self.assertFalse(status["present"])
        self.assertIn("not a directory", status["error"])

    def test_reads_the_mirror_counters_and_headlines(self):
        self._seed("note", "--goal", "ship the chip", "--next", "wire the statusbar")
        self._seed("note", "--check", "ledger parses", "--by", "make test")
        self._seed("note", "--open", "does it follow the focused tab?", "--settled-by", "manual check")
        status = self.status.read_status(self.tmp)
        self.assertTrue(status["present"])
        self.assertEqual(status["goal"], "ship the chip")
        self.assertEqual(status["next"], "wire the statusbar")
        self.assertEqual(status["verified"], 1)
        self.assertEqual(status["open"], 1)
        self.assertIsInstance(status["updated"], int)
        self.assertGreaterEqual(status["stale_secs"], 0)

    def test_detail_carries_the_full_content_of_every_item(self):
        """The popover shows everything: claims with verify-with, ✓ with evidence, opens."""
        self._seed("note", "--goal", "g", "--next", "n")
        self._seed("note", "--claim", "P1: la cosa", "--verify-with", "make test")
        self._seed("note", "--check", "el gate corrio", "--by", "make test, 3 passed")
        self._seed("note", "--open", "sobrevive el cambio de sesion?", "--settled-by", "probe")
        status = self.status.read_status(self.tmp)
        self.assertEqual(len(status["claims_detail"]), 1)
        self.assertIn("P1: la cosa", status["claims_detail"][0])
        self.assertIn("make test", status["claims_detail"][0])          # verify-with viaja
        self.assertEqual(len(status["verified_detail"]), 1)
        self.assertIn("verified by: make test, 3 passed", status["verified_detail"][0])
        self.assertEqual(len(status["open_detail"]), 1)
        self.assertIn("sobrevive", status["open_detail"][0])

    def test_read_contract_returns_verbatim_markdown(self):
        Path(self.tmp, ".riel").mkdir()
        Path(self.tmp, ".riel", "contract.md").write_text(
            "# Task: probe\n\n## Objective\nWe need x\n\n```mermaid\nflowchart TD\n  A[\"B\"]\n```\n",
            encoding="utf-8",
        )
        result = self.status.read_contract(self.tmp)
        self.assertTrue(result["present"])
        self.assertIn("# Task: probe", result["markdown"])
        self.assertIn("```mermaid", result["markdown"])
        self.assertEqual(result["chars"], len(result["markdown"]))

    def test_read_contract_without_one_says_so(self):
        result = self.status.read_contract(self.tmp)
        self.assertFalse(result["present"])
        self.assertIn("contract", result["error"])
        self.assertEqual(result["markdown"], "")

    def test_read_contract_junk_inputs_never_raise(self):
        for value in ("", "   ", "/dev/null", "\x00"):
            with self.subTest(value=value):
                result = self.status.read_contract(value)
                self.assertFalse(result["present"])
                self.assertIsInstance(result, dict)

    def test_ledger_without_goal_is_present_but_empty(self):
        ledger = Path(self.tmp) / ".riel" / "ledger.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# Riel ledger\n", encoding="utf-8")
        status = self.status.read_status(self.tmp)
        self.assertTrue(status["present"])
        self.assertEqual(status["verified"], 0)
        self.assertIn("error", status)  # rielctl declines to build a mirror

    def test_never_raises_on_a_junk_worktree_argument(self):
        for value in ("", "   ", "/dev/null", "\x00"):
            with self.subTest(value=value):
                status = self.status.read_status(value)
                self.assertFalse(status["present"])
                self.assertIsInstance(status, dict)


@unittest.skipUnless(_fastapi_available(), "fastapi is not installed in this interpreter")
class PluginApiRouteTest(unittest.TestCase):
    """The real router used by the gateway mount."""

    @classmethod
    def setUpClass(cls):
        cls.api = load_module("riel_plugin_api", DASHBOARD / "plugin_api.py")

    def test_router_exposes_both_routes(self):
        paths = {getattr(route, "path", None) for route in self.api.router.routes}
        self.assertIn("/ledger", paths)
        self.assertIn("/health", paths)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(self.api.router)
        return TestClient(app)

    def test_ledger_route_returns_the_summary(self):
        with tempfile.TemporaryDirectory(prefix="riel-route-") as tmp:
            subprocess.run(
                [sys.executable, str(VENDOR_RIELCTL), "note", "--goal", "route goal"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            )
            client = self._client()
            ok = client.get("/ledger", params={"worktree": tmp})
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.json()["present"])
            self.assertEqual(ok.json()["goal"], "route goal")

            missing = client.get("/ledger", params={"worktree": ""})
            self.assertEqual(missing.status_code, 200)
            self.assertFalse(missing.json()["present"])

    def test_health_reports_the_vendored_rielctl(self):
        payload = self._client().get("/health").json()
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["rielctl"].endswith("rielctl"))

    def test_contract_route_returns_verbatim_markdown(self):
        with tempfile.TemporaryDirectory(prefix="riel-route-") as tmp:
            contract = Path(tmp) / ".riel" / "contract.md"
            contract.parent.mkdir(parents=True)
            contract.write_text("# Task: x\n\n```mermaid\nflowchart TD\n  A[\"B\"]\n```\n", encoding="utf-8")
            client = self._client()
            ok = client.get("/contract", params={"worktree": tmp})
            self.assertEqual(ok.status_code, 200)
            payload = ok.json()
            self.assertTrue(payload["present"])
            self.assertIn("# Task: x", payload["markdown"])
            self.assertIn("```mermaid", payload["markdown"])
            self.assertEqual(payload["chars"], len(payload["markdown"]))

    def test_contract_route_reports_missing_not_invented(self):
        with tempfile.TemporaryDirectory(prefix="riel-route-") as tmp:
            payload = self._client().get("/contract", params={"worktree": tmp}).json()
            self.assertFalse(payload["present"])
            self.assertIn("contract", payload["error"])
            self.assertEqual(payload["markdown"], "")


@unittest.skipUnless(_node_available(), "node is not installed")
class ChipTest(unittest.TestCase):
    """The chip loaded and rendered by a real Node process, with a stubbed SDK."""

    def run_chip(self, ledger=None, busy=False, tool=None, complete=False, extra_env=None):
        with tempfile.TemporaryDirectory(prefix="riel-chip-") as tmp:
            root = Path(tmp)
            harness = _stub_environment(root)
            env = dict(
                os.environ,
                RIEL_TEST_CWD=CLIENT_CWD,
                RIEL_TEST_LEDGER=json.dumps(ledger),
                RIEL_TEST_TOOL=json.dumps(tool),
                RIEL_TEST_BUSY="1" if busy else "0",
                RIEL_TEST_COMPLETE="1" if complete else "0",
            )
            env.update(extra_env or {})
            proc = subprocess.run(
                ["node", str(harness)],
                cwd=root,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            return json.loads(proc.stdout)

    LEDGER = {"present": True, "goal": "ship the chip", "next": "wire the statusbar", "verified": 3, "open": 1}

    def test_registers_a_statusbar_chip(self):
        result = self.run_chip(ledger=self.LEDGER)
        self.assertEqual(result["id"], "riel")
        self.assertEqual(result["areas"], ["statusBar.right"])
        self.assertFalse(result["defaultEnabled"], "the desktop half ships opt-in")

    def test_idle_chip_shows_counters(self):
        result = self.run_chip(ledger=self.LEDGER)
        self.assertEqual(result["final_label"], "Riel: Ledger ✓3 ?1")
        self.assertIn("--ui-text-tertiary", result["activity_class"])
        self.assertIn("text-primary", result["check_class"], "the ✓ carries the color, not the label")

    def test_chip_without_a_ledger_says_so(self):
        result = self.run_chip()
        self.assertEqual(result["final_label"], "Riel: Ledger")
        self.assertIn("--ui-text-tertiary", result["activity_class"])

    def test_no_contract_no_contract_chip(self):
        """The Contrato chip only exists when the backend says there is one."""
        result = self.run_chip(ledger=self.LEDGER)
        self.assertFalse(result["contract_visible"])

    def test_contract_chip_appears_when_there_is_one(self):
        result = self.run_chip(ledger=self.LEDGER, extra_env={"RIEL_TEST_CONTRACT": "1"})
        self.assertTrue(result["contract_visible"])

    def test_streamdown_renders_mermaid(self):
        """Streamdown ships with mermaid OFF (context default void 0) — the
        contract dialog must pass the mermaid option or the graph stays a
        plain code block. Asserted at the source level: the option is on the
        Streamdown call inside the contract dialog."""
        source = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        dialog_body = source.split("function ContractDialog")[1].split("\nfunction ")[0]
        self.assertIn("mermaid", dialog_body,
                      "the contract dialog does not pass the mermaid option to Streamdown")
        self.assertIn("mermaid: {}", dialog_body)

    def test_long_next_is_not_dumped_into_the_bar(self):
        """The next action lives in the tooltip now — the bar stays short."""
        ledger = dict(self.LEDGER, next="x" * 200)
        result = self.run_chip(ledger=ledger)
        self.assertEqual(result["final_label"], "Riel: Ledger ✓3 ?1")
        self.assertIn("x" * 60, result["final_title"])

    def test_running_turn_pulses(self):
        result = self.run_chip(ledger=self.LEDGER, busy=True, tool="terminal")
        self.assertIn("●", result["activity_label"])
        self.assertIn("animate-pulse", result["activity_running_class"], "the running dot pulses")
        self.assertIn("Turno en curso: terminal", result["activity_title"])

    def test_tool_completion_refetches_the_ledger(self):
        result = self.run_chip(ledger=self.LEDGER, tool="terminal", complete=True)
        self.assertGreaterEqual(
            result["rest_calls"], 2, "a finished tool must trigger an immediate ledger re-read"
        )
        self.assertIn("Último tool: terminal (1.4s)", result["final_title"])

    def test_tooltip_carries_goal_and_next(self):
        result = self.run_chip(ledger=self.LEDGER)
        self.assertIn("ship the chip", result["final_title"])
        self.assertIn("→ wire the statusbar", result["final_title"])

    def test_idle_without_ledger_still_shows_the_last_tool(self):
        result = self.run_chip(tool="terminal", complete=True)
        self.assertEqual(result["final_label"], "Riel: Ledger")
        self.assertIn("Último tool: terminal", result["final_title"])

    def test_ledger_click_opens_the_popover(self):
        """The ledger chip opens a popover now (Radix trigger), not a toast."""
        result = self.run_chip(ledger=self.LEDGER, tool="terminal", complete=True)
        self.assertFalse(result["tapped"], "no toast anymore — the popover is the UI")
        self.assertIsNone(result["notified"])

    def test_background_session_tools_do_not_move_the_chip(self):
        """A tool in ANOTHER tile must not reach the focused chip's tooltip.

        The pulsing dot may stay (busy is the focused session's own state) —
        what must NOT appear is the background tool's NAME.
        """
        mine = self.run_chip(ledger=self.LEDGER, busy=True, tool="terminal")
        self.assertIn("Turno en curso: terminal", mine["activity_title"])
        # the harness emits events with session_id 's1'; focus another session
        # and the same event is ignored: no tool name in the tooltip.
        other = self.run_chip(ledger=self.LEDGER, busy=True, tool="terminal",
                              extra_env={"RIEL_TEST_FOCUS": "s2"})
        self.assertNotIn("terminal", other["activity_title"],
                         "a background tile's tool leaked into the focused chip")

    def test_focus_switch_clears_the_stale_ledger(self):
        """No leftover ledger from the previous conversation after a switch."""
        result = self.run_chip(ledger=self.LEDGER, extra_env={"RIEL_TEST_SWITCH": "1"})
        self.assertFalse(result["final_label"].startswith("Riel: Ledger ✓"),
                         "the previous session's ledger survived the focus switch")

    def test_session_info_cwd_is_authoritative_per_session(self):
        """The worktree comes from session.info, keyed per session.

        A background session reporting a DIFFERENT cwd must not move the
        focused chip's worktree; the focused session's own session.info does.
        """
        # focused s1 reported /wt/riel -> chip reads that worktree
        mine = self.run_chip(ledger=self.LEDGER, extra_env={"RIEL_TEST_INFO_CWD": "/wt/riel"})
        self.assertTrue(mine["session_cwd"].endswith("/wt/riel"))
        # s2 reports /wt/other: stored, but the focused chip keeps /wt/riel
        other = self.run_chip(
            ledger=self.LEDGER,
            extra_env={"RIEL_TEST_INFO_CWD": "/wt/riel", "RIEL_TEST_FOREIGN_INFO": "/wt/other"},
        )
        self.assertTrue(other["session_cwd"].endswith("/wt/riel"),
                        "a background session's cwd leaked into the focused chip")
        # now s1 itself reports a move -> the focused chip follows
        moved = self.run_chip(ledger=self.LEDGER, extra_env={"RIEL_TEST_INFO_CWD": "/wt/moved"})
        self.assertTrue(moved["session_cwd"].endswith("/wt/moved"))


if __name__ == "__main__":
    unittest.main()
