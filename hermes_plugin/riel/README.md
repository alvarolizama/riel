# Riel — plugin de Hermes

Mecánica de Riel como tools de Hermes: `riel_note`, `riel_seam`, `riel_resume`,
`riel_todo`, sobre un `rielctl` **vendorizado** dentro de este directorio.

**La prosa NO viaja acá.** Las seis skills (`riel-ledger`, `riel-contract`,
`riel-protocol`, `riel-briefs`, `riel-delegate`, `riel-cli`) se instalan desde
este mismo repo como skill tap — un solo lugar para el markdown, indexado por
Hermes y con auto-trigger:

```bash
hermes skills tap add alvarolizama/riel
```

## Instalación (usuario)

```bash
hermes plugins install alvarolizama/riel/hermes_plugin/riel
hermes plugins enable riel
```

El instalador clona el repo y **mueve solo este subdirectorio** a
`~/.hermes/plugins/riel` — el checkout no sobrevive. Por eso el paquete es
autocontenido: `vendor/` trae su propia copia de `rielctl` y de los templates,
generada desde el repo (`make plugin-vendor`) y verificada por hash en el suite
(`tests/test_plugin_vendor.py`). El repo es la fuente; `vendor/` es un artefacto
de build.

## Instalación (desarrollo, symlink al checkout)

El plugin resuelve su `rielctl` desde `vendor/`, así que en dev se puede
symlinkear el paquete completo y tener la última versión del checkout:

```bash
make plugin-vendor                     # genera vendor/ desde skills/
make plugin-link                       # ~/.hermes/plugins/riel -> repo
make plugin-link PLUGINS_DIR=~/.hermes/profiles/coder/plugins
hermes plugins enable riel
```

Los plugins son **por perfil** (`$HERMES_HOME/plugins/`): no se comparten como
las skills vía `external_dirs` — hay que symlinkear en cada perfil que lo use.

## Cómo resuelve el worktree

`rielctl` lee y escribe `.riel/` **relativo al cwd**. El handler corre dentro
del proceso de Hermes, cuyo cwd no es el worktree de la sesión, así que cada
llamada resuelve la raíz así:

1. argumento `worktree` de la tool (ruta explícita),
2. el cwd registrado de la sesión (el mismo que usa el tool `terminal`),
3. `TERMINAL_CWD`,
4. el cwd del proceso.

Y ejecuta `rielctl` en un **subproceso** con `cwd=<worktree>`: cada llamada
tiene su propio cwd y no hay `chdir` global compartido entre sesiones
concurrentes (un gateway sirve varias a la vez).

## Mitad desktop — chip de actividad en el statusbar

`desktop/plugin.js` registra un chip en `statusBar.right` con el ledger del
worktree actual: `riel 4✓ 2? · next: <acción>`. Un clic dispara un toast con
`Goal → Next`. Cada 5 s consulta `GET /api/plugins/riel/ledger?worktree=<cwd>`,
servido por `dashboard/plugin_api.py` (el backend del plugin, montado por el
gateway en el proceso del agente). Ese backend normaliza el mirror de
`rielctl todo` vía `dashboard/ledger_status.py`, así que el formato del ledger
sigue teniendo un solo dueño: el plugin no re-parsea `.riel/ledger.md`, y el
renderer nunca lee el disco (solo `<worktree>/.riel/ledger.md` puede salir, y
solo como contadores + los titulares de goal/next).

Tres interruptores, todos apagados por defecto:

| Interruptor | Dónde | Qué habilita |
|---|---|---|
| `plugins.enabled` | `config.yaml` — `hermes plugins enable riel` | la mitad Python: tools + backend |
| Capabilities → Plugins | app de escritorio | la mitad desktop (es **opt-in**) |
| copia del paquete | automática al instalar/actualizar; ⌘K → **Reload desktop plugins** (o **Rescan**) si el chip no aparece | `~/.hermes/desktop-plugins/riel/` |

Dos asimetrías que conviene tener presentes: la mitad desktop es **app-level**
(una sola copia para todos los perfiles, la puso ahí el proceso principal de
Electron), y el backend Python se importa al arrancar la sesión del gateway —
un plugin recién enlazado no sirve rutas hasta la sesión siguiente.

## Verificación

```bash
make test          # incluye tests/test_plugin_vendor.py (hash + handlers end-to-end)
hermes plugins doctor hermes_plugin/riel --ci   # mismo discovery/registro que usa Hermes
```
