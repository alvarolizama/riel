"""Regression tests for the Riel desktop half — the statusbar chip.

Three layers, each with the cheapest honest check available:

  * package wiring — manifest/paths, and the two rules the SDK enforces on a
    disk plugin (allowed import specifiers, no hardcoded colors);
  * `ledger_status.read_status` — stdlib-only, driven by the **vendored**
    rielctl against a real temp worktree;
  * the chip itself — the plugin file is loaded by a real Node process against
    stubbed `@hermes/plugin-sdk` / `react` modules, `register()` is called and
    the component is rendered, so a syntax error, a bad import or a broken
    label fails here instead of silently in the app.

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


def _stub_modules(root: Path) -> Path:
    """A minimal `@hermes/plugin-sdk` + `react` so the chip can run under Node."""
    sdk = root / "node_modules" / "@hermes" / "plugin-sdk"
    react = root / "node_modules" / "react"
    sdk.mkdir(parents=True)
    react.mkdir(parents=True)

    (sdk / "package.json").write_text(
        json.dumps({"name": "@hermes/plugin-sdk", "version": "0.0.0", "type": "module", "main": "index.mjs"}),
        encoding="utf-8",
    )
    (sdk / "index.mjs").write_text(
        "export const host = {\n"
        "  state: { cwd: { get: () => process.env.RIEL_TEST_CWD || '' } },\n"
        "  notify: (payload) => { globalThis.__RIEL_NOTIFIED__ = payload },\n"
        "}\n"
        "export const haptic = () => { globalThis.__RIEL_TAPPED__ = true }\n"
        "export const useValue = (atom) => (atom && typeof atom.get === 'function' ? atom.get() : null)\n",
        encoding="utf-8",
    )
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
    (react / "index.mjs").write_text(
        "// useState returns the state the harness injected; useEffect does NOT run the\n"
        "// callback, so no fetch/timer noise — this test targets the render logic.\n"
        "export const useState = (initial) =>\n"
        "  [globalThis.__RIEL_STATE__ === undefined ? initial : globalThis.__RIEL_STATE__, () => {}]\n"
        "export const useEffect = () => {}\n",
        encoding="utf-8",
    )
    (react / "jsx-runtime.mjs").write_text(
        "export const jsx = (type, props) => ({ type, props })\nexport const jsxs = jsx\n",
        encoding="utf-8",
    )

    (root / "plugin.mjs").write_text((DESKTOP / "plugin.js").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "harness.mjs").write_text(
        "import plugin from './plugin.mjs'\n"
        "\n"
        "if (process.env.RIEL_TEST_STATE) globalThis.__RIEL_STATE__ = JSON.parse(process.env.RIEL_TEST_STATE)\n"
        "const contributions = []\n"
        "const ctx = { rest: async () => ({ present: false }), register: (c) => contributions.push(c) }\n"
        "plugin.register(ctx)\n"
        "const chip = contributions.find((c) => c.area === 'statusBar.right')\n"
        "if (!chip || typeof chip.render !== 'function') {\n"
        "  console.error('FAIL: no statusBar.right contribution with a render')\n"
        "  process.exit(2)\n"
        "}\n"
        "const element = chip.render()\n"
        "const tree = element.type(element.props)\n"
        "tree.props.onClick()\n"
        "console.log(JSON.stringify({\n"
        "  id: plugin.id, name: plugin.name, defaultEnabled: plugin.defaultEnabled,\n"
        "  areas: contributions.map((c) => c.area), order: chip.order,\n"
        "  label: tree.props.children, title: tree.props.title, className: tree.props.className,\n"
        "  notified: globalThis.__RIEL_NOTIFIED__ || null, tapped: globalThis.__RIEL_TAPPED__ === true,\n"
        "}))\n"
        "process.exit(0)\n",
        encoding="utf-8",
    )
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

    def test_ledger_route_returns_the_summary(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(self.api.router)

        with tempfile.TemporaryDirectory(prefix="riel-route-") as tmp:
            subprocess.run(
                [sys.executable, str(VENDOR_RIELCTL), "note", "--goal", "route goal"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            )
            client = TestClient(app)
            ok = client.get("/ledger", params={"worktree": tmp})
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.json()["present"])
            self.assertEqual(ok.json()["goal"], "route goal")

            missing = client.get("/ledger", params={"worktree": ""})
            self.assertEqual(missing.status_code, 200)
            self.assertFalse(missing.json()["present"])

    def test_health_reports_the_vendored_rielctl(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(self.api.router)
        payload = TestClient(app).get("/health").json()
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["rielctl"].endswith("rielctl"))


@unittest.skipUnless(_node_available(), "node is not installed")
class ChipRenderTest(unittest.TestCase):
    """The chip loaded and rendered by a real Node process, with a stubbed SDK."""

    def _render(self, state):
        with tempfile.TemporaryDirectory(prefix="riel-chip-") as tmp:
            root = Path(tmp)
            harness = _stub_modules(root)
            env = dict(os.environ, RIEL_TEST_STATE=json.dumps(state), RIEL_TEST_CWD=CLIENT_CWD)
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
        result = self._render({"present": False})
        self.assertEqual(result["id"], "riel")
        self.assertEqual(result["areas"], ["statusBar.right"])
        self.assertFalse(result["defaultEnabled"], "the desktop half ships opt-in")
        self.assertTrue(result["tapped"])

    def test_label_shows_counters_and_next_action(self):
        result = self._render(
            {"present": True, "goal": "ship the chip", "next": "wire the statusbar", "verified": 3, "open": 1}
        )
        self.assertEqual(result["label"], "riel 3✓ 1? · wire the statusbar")
        self.assertIn("ship the chip", result["title"])
        self.assertIn("--ui-text-tertiary", result["className"])
        self.assertIn("ship the chip", result["notified"]["message"])

    def test_label_without_a_ledger_says_so(self):
        result = self._render({"present": False})
        self.assertEqual(result["label"], "riel · sin ledger")
        self.assertIn("--ui-text-quaternary", result["className"])

    def test_long_goal_is_truncated_not_dumped(self):
        result = self._render({"present": True, "goal": "g", "next": "x" * 200, "verified": 0, "open": 0})
        self.assertLessEqual(len(result["label"]), 60)
        self.assertIn("…", result["label"])


if __name__ == "__main__":
    unittest.main()
