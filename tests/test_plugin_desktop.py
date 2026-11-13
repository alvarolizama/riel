"""Regression tests for the Riel desktop half — the statusbar chip.

Three layers, each with the cheapest honest check available:

  * package wiring — manifest/paths, and the two rules the SDK enforces on a
    disk plugin (allowed import specifiers, no hardcoded colors);
  * `ledger_status.read_run` — stdlib-only, driven by the STUB engine
    (`_stub_engine.py`, the 2.0 run contract) against a real temp worktree:
    one bounded, symlink-safe read answering `{present, worktree, markdown,
    status}`;
  * the chip itself — the plugin file is loaded by a real Node process against
    stubbed `@hermes/plugin-sdk` / `react` modules, `register()` is called,
    the gateway events are emitted and the component is rendered, so a syntax
    error, a bad import, a broken label or a missing refetch fails here instead
    of silently in the app.

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

sys.path.insert(0, str(HERE))

import _stub_engine as stub  # noqa: E402

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

// Dialog/Streamdown stubs: they only need to EXIST for the import to
// resolve. `asChild` triggers must PASS THROUGH their child so the walk
// still finds the real button.
const makeStub = (tag) => (props) => {
  if (props && props.asChild && props.children) return props.children
  return { tag, props: props || {} }
}

export const host = {
  state: {
    cwd: { get: () => process.env.RIEL_TEST_CWD || '' },
    busy: { get: () => process.env.RIEL_TEST_BUSY === '1' },
    focusedSessionId: { get: () => (globalThis.__RIEL_FOCUS__ ||= process.env.RIEL_TEST_FOCUS || 's1') },
    focusedStoredSessionId: { get: () => (globalThis.__RIEL_FOCUS__ ||= process.env.RIEL_TEST_FOCUS || 's1') }
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
export const Switch = makeStub('switch')
export const Input = makeStub('input')
export const Button = makeStub('button')
export const PALETTE_AREA = 'palette'
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

let restCalls = 0
const contributions = []
const runCalls = []
// Path-aware rest stub: /run answers only when the harness was told a run
// exists (RIEL_TEST_RUN=1).
const settingsState = { ok: true, gate: true, tools: true, context: true, harness_note: '' }
const settingsCalls = []
const restStub = async (path, options) => {
  restCalls += 1
  if (path.startsWith('/settings')) {
    settingsCalls.push(path + ((options && options.method) || ''))
    if (options && options.method === 'POST' && options.body) {
      for (const [key, value] of Object.entries(options.body)) settingsState[key] = value
    }
    return { ...settingsState }
  }
  if (path.startsWith('/session_cwd')) {
    // Resolve the focused session's stored cwd (the DB fallback)
    const m = /session_id=([^&]+)/.exec(path)
    const sid = m ? decodeURIComponent(m[1]) : ''
    const known = JSON.parse(process.env.RIEL_TEST_DB_CWDS || '{}')
    const cwd = known[sid]
    return cwd ? { found: true, cwd } : { found: false, error: 'session has no stored cwd' }
  }
  if (path.startsWith('/run')) {
    runCalls.push(path)
    globalThis.__RIEL_LAST_RUN_URL__ = path
    return process.env.RIEL_TEST_RUN === '1'
      ? { present: true, worktree: '/wt', markdown: '# Run: x', status: { active: true } }
      : { present: false, worktree: '/wt', markdown: '', status: null }
  }
  return { present: false }
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
  // `button` is null when the chip renders nothing (no run) — the label
  // assertions then read null instead of the empty tree's text.
  return { tree, button: findChipButton(tree) }
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

const findChipButton = (node) => {
  if (!node || typeof node !== 'object') return null
  if (node.type === 'button') return node
  const children = node.props && node.props.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findChipButton(child)
      if (found) return found
    }
  } else if (children && typeof children === 'object') {
    return findChipButton(children)
  }
  return null
}

const first = render()
await tick()   // let the run effect's first fetch land before asserting
const firstAfterFetch = render()

const tool = process.env.RIEL_TEST_TOOL && JSON.parse(process.env.RIEL_TEST_TOOL)
if (tool) emit('tool.start', { payload: { name: tool, tool_id: 't1' }, session_id: 's1' })
await tick()
const withActivity = render()

// session.info events: the focused session's own cwd report, then optionally a
// FOREIGN session reporting a different one — the chip must keep the focused's.
// Each report is followed by a re-render (the stub's setState does not schedule
// one) plus a tool.complete to bump the run-refetch revision.
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
  for (const cleanup of cleanups) if (typeof cleanup === 'function') cleanup()
  globalThis.__RIEL_CLEANUPS__ = []
  globalThis.__RIEL_INDEX__ = current
  await tick()
  switched = render()
}

const current = switched || afterComplete || withActivity

const textOf = (node) => {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join(' ')
  if (node && typeof node === 'object' && node.props) return textOf(node.props.children)
  return ''
}
const chipButton = findChipButton(current.tree)
const labelOf = (r) => (r && r.button ? textOf(r.button.props.children).replace(/\\s+/g, ' ').trim() : null)
const runVisible = (() => {
  const walk = (node) => {
    if (!node || typeof node !== 'object' || !node.props) return false
    if (node.type === 'button' && textOf(node).startsWith('Riel')) return true
    for (const child of [].concat(node.props.children || [])) if (walk(child)) return true
    return false
  }
  return walk(current.tree)
})()

console.log(JSON.stringify({
  id: plugin.id,
  name: plugin.name,
  areas: contributions.map((c) => c.area),
  palette_ids: contributions.filter((c) => c.area === 'palette').map((c) => c.data && c.data.id),
  settings_calls: settingsCalls,
  defaultEnabled: plugin.defaultEnabled,
  order: chip.order,
  session_cwd: (() => {
    // The cwd the chip resolved to, captured from the last /run probe
    const m = /worktree=([^&]+)/.exec(globalThis.__RIEL_LAST_RUN_URL__ || '')
    return m ? decodeURIComponent(m[1]) : null
  })(),
  first_label: labelOf(firstAfterFetch),
  activity_label: labelOf(withActivity),
  activity_title: withActivity.button ? withActivity.button.props.title : null,
  activity_class: withActivity.button ? withActivity.button.props.className : null,
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
  run_visible: runVisible,
  streamdown_mermaid: (() => {
    if (process.env.RIEL_TEST_RUN !== '1') return null
    return Boolean(globalThis.__RIEL_STREAMDOWN_PROPS__ && 'mermaid' in globalThis.__RIEL_STREAMDOWN_PROPS__)
  })(),
  final_label: labelOf(current),
  final_title: chipButton ? chipButton.props.title : null,
  rest_paths: (() => {
    const seen = new Set()
    for (const p of runCalls) seen.add(p.split('?')[0])
    for (const p of settingsCalls) seen.add(p.split('?')[0].replace('POST', ''))
    return [...seen]
  })(),
  run_calls: runCalls.length,
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

    def test_the_desktop_half_polls_run_not_ledger(self):
        """The old /ledger and /contract routes are gone from the chip."""
        source = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        self.assertNotIn("'/ledger", source)
        self.assertNotIn("'/contract", source)
        self.assertIn("'/run?worktree=", source)


class ReadRunTest(unittest.TestCase):
    """`ledger_status.read_run` driven through the stub engine."""

    @classmethod
    def setUpClass(cls):
        cls.status = load_module("riel_ledger_status", DASHBOARD / "ledger_status.py")
        stub.install(cls.status.tools)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-status-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_absent_run_is_reported_not_invented(self):
        report = self.status.read_run(self.tmp)
        self.assertFalse(report["present"])
        self.assertEqual(report["markdown"], "")
        self.assertIsNone(report["status"])
        self.assertNotIn("error", report)

    def test_directory_that_does_not_exist_reports_an_error(self):
        report = self.status.read_run(str(Path(self.tmp) / "nope"))
        self.assertFalse(report["present"])
        self.assertIn("not a directory", report["error"])

    def test_reads_the_verbatim_markdown_and_the_status_object(self):
        stub.seed(self.tmp, goal="ship the chip", next="wire the statusbar",
                  claims=["P1"], gates=["G1"])
        payload = json.loads(self.status.tools.riel_note({
            "gates": ["G1"], "command": "true", "covering": "all",
            "claims": ["P1"], "worktree": self.tmp}))
        self.assertEqual(payload["exit_code"], 0, payload)
        report = self.status.read_run(self.tmp)
        self.assertTrue(report["present"])
        self.assertIn("# Run:", report["markdown"])
        self.assertIn("```riel-state", report["markdown"])
        self.assertEqual(report["chars"], len(report["markdown"]))
        status = report["status"]
        self.assertIsInstance(status, dict, "the engine status is ONE JSON object")
        self.assertEqual(status["goal"], "ship the chip")
        self.assertTrue(status["gates"][0]["done"])
        self.assertIsInstance(report["updated"], int)
        self.assertGreaterEqual(report["stale_secs"], 0)

    def test_a_worktree_is_symlink_resolved_before_reading(self):
        """The read goes through the REAL worktree, never a raw symlink path."""
        real = tempfile.mkdtemp(prefix="riel-real-")
        self.addCleanup(shutil.rmtree, real, ignore_errors=True)
        stub.seed(real, goal="via symlink")
        link = Path(self.tmp) / "link"
        link.symlink_to(real, target_is_directory=True)
        report = self.status.read_run(str(link))
        self.assertTrue(report["present"])
        self.assertEqual(report["worktree"], os.path.realpath(real),
                         "the report names the resolved worktree")
        self.assertEqual(report["status"]["goal"], "via symlink")

    def test_never_raises_on_a_junk_worktree_argument(self):
        for value in ("", "   ", "/dev/null", "\x00"):
            with self.subTest(value=value):
                report = self.status.read_run(value)
                self.assertFalse(report["present"])
                self.assertIsInstance(report, dict)


@unittest.skipUnless(_fastapi_available(), "fastapi is not installed in this interpreter")
class PluginApiRouteTest(unittest.TestCase):
    """The real router used by the gateway mount."""

    @classmethod
    def setUpClass(cls):
        cls.api = load_module("riel_plugin_api", DASHBOARD / "plugin_api.py")
        # The route module resolves its own dashboard half (and through it, its
        # own tools reference) — the stub must be installed THERE, or the /run
        # route would answer from the real engine while the test seeds the stub.
        stub.install(cls.api._ledger_status.tools)

    def test_router_exposes_the_run_route_and_never_the_old_ones(self):
        paths = {getattr(route, "path", None) for route in self.api.router.routes}
        self.assertIn("/run", paths)
        self.assertIn("/health", paths)
        self.assertNotIn("/ledger", paths, "the old ledger route is gone")
        self.assertNotIn("/contract", paths, "the old contract route is gone")

    def test_all_task_routes_are_sync_defs(self):
        """Sync defs run on FastAPI's threadpool — no blocker on the event loop."""
        for route in self.api.router.routes:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            import inspect
            self.assertFalse(
                inspect.iscoroutinefunction(endpoint),
                f"{getattr(route, 'path', '?')} is async: a bounded engine call would block the loop",
            )

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(self.api.router)
        return TestClient(app)

    def test_run_route_returns_the_object(self):
        with tempfile.TemporaryDirectory(prefix="riel-route-") as tmp:
            tools = load_module("riel_route_tools", PLUGIN / "tools.py")
            stub.install(tools)
            stub.seed(tmp, goal="route goal")
            client = self._client()
            ok = client.get("/run", params={"worktree": tmp})
            self.assertEqual(ok.status_code, 200)
            body = ok.json()
            self.assertTrue(body["present"])
            self.assertIn("# Run:", body["markdown"])
            self.assertEqual(body["status"]["goal"], "route goal")

            missing = client.get("/run", params={"worktree": ""})
            self.assertEqual(missing.status_code, 200)
            self.assertFalse(missing.json()["present"])

    def test_health_reports_the_bundled_engine_and_no_cwd(self):
        payload = self._client().get("/health").json()
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["engine"].endswith("run.py"))
        self.assertNotIn("cwd", payload, "/health must not leak the gateway's cwd")


@unittest.skipUnless(_node_available(), "node is not installed")
class ChipTest(unittest.TestCase):
    """The chip loaded and rendered by a real Node process, with a stubbed SDK."""

    def run_chip(self, busy=False, tool=None, complete=False, extra_env=None):
        with tempfile.TemporaryDirectory(prefix="riel-chip-") as tmp:
            root = Path(tmp)
            harness = _stub_environment(root)
            env = dict(
                os.environ,
                RIEL_TEST_CWD=CLIENT_CWD,
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

    def test_registers_a_statusbar_chip(self):
        result = self.run_chip()
        self.assertEqual(result["id"], "riel")
        self.assertEqual(result["areas"].count("statusBar.right"), 1, result["areas"])
        self.assertFalse(result["defaultEnabled"], "the desktop half ships opt-in")

    def test_registers_the_palette_switches(self):
        """⌘K carries the two switches — the bar no longer has room to show them."""
        result = self.run_chip()
        self.assertEqual(result["areas"].count("palette"), 2, result["areas"])
        self.assertEqual(sorted(result["palette_ids"]), ["riel.toggle-context", "riel.toggle-gate"])
        self.assertTrue(all(call.startswith("/settings") for call in result["settings_calls"]))

    def test_no_run_no_chip_at_all(self):
        """The one chip only exists when the backend says there is a run."""
        result = self.run_chip()
        self.assertFalse(result["run_visible"])
        self.assertIsNone(result["final_label"], "the bar is silent without a run")

    def test_run_chip_appears_when_there_is_one(self):
        result = self.run_chip(extra_env={"RIEL_TEST_RUN": "1"})
        self.assertTrue(result["run_visible"])
        self.assertEqual(result["final_label"], "Riel")

    def test_the_chip_polls_run_only(self):
        result = self.run_chip(extra_env={"RIEL_TEST_RUN": "1"})
        self.assertEqual([p for p in result["rest_paths"] if p.startswith("/run")], ["/run"])
        self.assertNotIn("/ledger", result["rest_paths"])
        self.assertNotIn("/contract", result["rest_paths"])

    def test_running_turn_pulses_and_names_the_tool(self):
        result = self.run_chip(busy=True, tool="terminal", extra_env={"RIEL_TEST_RUN": "1"})
        self.assertIn("●", result["activity_label"])
        self.assertIn("terminal", result["activity_label"], "the live tool names itself in the bar")
        self.assertIn("animate-pulse", result["activity_running_class"], "the running dot pulses")
        self.assertIn("Turno en curso: terminal", result["activity_title"])

    def test_tool_completion_refetches_the_run(self):
        """A finished tool re-probes the run — one written mid-task appears."""
        result = self.run_chip(tool="terminal", complete=True, extra_env={"RIEL_TEST_RUN": "1"})
        self.assertGreaterEqual(
            result["run_calls"], 2, "a finished tool must trigger an immediate run re-probe"
        )

    def test_background_session_tools_do_not_move_the_chip(self):
        """A tool in ANOTHER tile must not reach the focused chip's tooltip."""
        mine = self.run_chip(busy=True, tool="terminal", extra_env={"RIEL_TEST_RUN": "1"})
        self.assertIn("Turno en curso: terminal", mine["activity_title"])
        other = self.run_chip(busy=True, tool="terminal",
                              extra_env={"RIEL_TEST_FOCUS": "s2", "RIEL_TEST_RUN": "1"})
        self.assertNotIn("terminal", other["activity_title"],
                         "a background tile's tool leaked into the focused chip")

    def test_focus_switch_clears_the_stale_tool(self):
        """No leftover tool from the previous conversation after a switch."""
        result = self.run_chip(extra_env={"RIEL_TEST_SWITCH": "1", "RIEL_TEST_RUN": "1"})
        self.assertNotIn("●", result["final_label"] or "",
                         "the previous session's tool activity survived the focus switch")

    def test_session_db_fallback_resolves_never_reported_sessions(self):
        """A session that never emitted session.info still gets its REAL
        worktree from the DB fallback — not the stale global cwd."""
        db = json.dumps({"s1": "/wt/from-db"})
        result = self.run_chip(extra_env={"RIEL_TEST_DB_CWDS": db, "RIEL_TEST_RUN": "1"})
        self.assertTrue(result["session_cwd"].endswith("/wt/from-db"),
                        "the DB fallback did not override the stale global cwd")

    def test_streamdown_renders_mermaid(self):
        """Streamdown ships with mermaid OFF — the run dialog must pass the option."""
        source = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        dialog_body = source.split("function RunDialog")[1].split("\nfunction ")[0]
        self.assertIn("mermaid", dialog_body,
                      "the run dialog does not pass the mermaid option to Streamdown")
        self.assertIn("mermaid: {}", dialog_body)

    def test_session_info_cwd_is_authoritative_per_session(self):
        """The worktree comes from session.info, keyed per session.

        A background session reporting a DIFFERENT cwd must not move the
        focused chip's worktree; the focused session's own session.info does.
        """
        mine = self.run_chip(extra_env={"RIEL_TEST_INFO_CWD": "/wt/riel",
                                        "RIEL_TEST_RUN": "1"})
        self.assertTrue(mine["session_cwd"].endswith("/wt/riel"))
        other = self.run_chip(
            extra_env={"RIEL_TEST_INFO_CWD": "/wt/riel", "RIEL_TEST_FOREIGN_INFO": "/wt/other",
                       "RIEL_TEST_RUN": "1"},
        )
        self.assertTrue(other["session_cwd"].endswith("/wt/riel"),
                        "a background session's cwd leaked into the focused chip")
        moved = self.run_chip(extra_env={"RIEL_TEST_INFO_CWD": "/wt/moved",
                                         "RIEL_TEST_RUN": "1"})
        self.assertTrue(moved["session_cwd"].endswith("/wt/moved"))


if __name__ == "__main__":
    unittest.main()
