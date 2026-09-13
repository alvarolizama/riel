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

// Dialog/Streamdown stubs: they only need to EXIST for the import to resolve —
// the chip tests assert the label and the click, not the dialog's pixels.
const makeStub = (tag) => (props) => ({ tag, props: props || {} })

export const host = {
  state: {
    cwd: { get: () => process.env.RIEL_TEST_CWD || '' },
    busy: { get: () => process.env.RIEL_TEST_BUSY === '1' }
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

export const Streamdown = makeStub('streamdown')
export const Dialog = makeStub('dialog')
export const DialogContent = makeStub('dialog-content')
export const DialogHeader = makeStub('dialog-header')
export const DialogTitle = makeStub('dialog-title')
export const DialogDescription = makeStub('dialog-description')
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
const ctx = {
  rest: async () => {
    restCalls += 1
    return ledger
  },
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
  const tree = element.type(element.props)
  // The chip renders as a span: [button, dialog] — click the button, not the span.
  const button = Array.isArray(tree.props.children)
    ? tree.props.children.find((child) => child && child.type === 'button')
    : tree
  return { tree, button: button || tree }
}

const first = render()
if (tool) emit('tool.start', { payload: { name: tool, tool_id: 't1' }, session_id: 's1' })
await tick()
const withActivity = render()

let afterComplete = null
if (tool && process.env.RIEL_TEST_COMPLETE === '1') {
  emit('tool.complete', { payload: { name: tool, tool_id: 't1', duration_s: 1.4 }, session_id: 's1' })
  await tick()
  afterComplete = render()
}

const current = afterComplete || withActivity
current.button.props.onClick()

console.log(JSON.stringify({
  id: plugin.id,
  name: plugin.name,
  defaultEnabled: plugin.defaultEnabled,
  areas: contributions.map((c) => c.area),
  order: chip.order,
  first_label: first.button.props.children,
  activity_label: withActivity.button.props.children,
  activity_title: withActivity.button.props.title,
  activity_class: withActivity.button.props.className,
  final_label: current.button.props.children,
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

    def run_chip(self, ledger=None, busy=False, tool=None, complete=False):
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

    def test_idle_chip_shows_counters_and_next_action(self):
        result = self.run_chip(ledger=self.LEDGER)
        self.assertEqual(result["final_label"], "riel 3✓ 1? · wire the statusbar")
        self.assertIn("--ui-text-tertiary", result["activity_class"])

    def test_chip_without_a_ledger_says_so(self):
        result = self.run_chip()
        self.assertEqual(result["final_label"], "riel · sin ledger")
        self.assertIn("--ui-text-quaternary", result["activity_class"])

    def test_long_next_is_truncated_not_dumped(self):
        ledger = dict(self.LEDGER, next="x" * 200)
        result = self.run_chip(ledger=ledger)
        self.assertIn("…", result["final_label"])
        self.assertLessEqual(len(result["final_label"]), 60)

    def test_running_turn_names_the_tool(self):
        result = self.run_chip(ledger=self.LEDGER, busy=True, tool="terminal")
        self.assertEqual(result["activity_label"], "riel ● terminal · 3✓ 1?")
        self.assertIn("--ui-accent", result["activity_class"])
        self.assertIn("turno en curso", result["activity_title"])

    def test_tool_completion_refetches_the_ledger(self):
        result = self.run_chip(ledger=self.LEDGER, busy=True, tool="terminal", complete=True)
        self.assertGreaterEqual(
            result["rest_calls"], 2, "a finished tool must trigger an immediate ledger re-read"
        )
        self.assertEqual(result["final_label"], "riel ● terminal ✓ · 3✓ 1?")
        self.assertIn("último tool: terminal (1.4s)", result["final_title"])

    def test_tooltip_carries_goal_and_next(self):
        result = self.run_chip(ledger=self.LEDGER)
        self.assertIn("ship the chip", result["final_title"])
        self.assertIn("→ wire the statusbar", result["final_title"])

    def test_idle_without_ledger_still_shows_the_last_tool(self):
        result = self.run_chip(tool="terminal", complete=True)
        self.assertEqual(result["final_label"], "riel · último: terminal")

    def test_click_opens_the_contract_dialog(self):
        """The click now opens the contract dialog instead of toasting."""
        result = self.run_chip(ledger=self.LEDGER, tool="terminal", complete=True)
        self.assertFalse(result["tapped"], "the click belongs to the dialog now")
        self.assertIsNone(result["notified"])


if __name__ == "__main__":
    unittest.main()
