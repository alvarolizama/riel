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

`desktop/plugin.js` registra un chip en `statusBar.right` que muestra dos cosas:

- **Estado del ledger** del worktree en foco: `riel 4✓ 2? · next: <acción>`.
- **Actividad viva**: mientras el turno corre el chip pasa a
  `riel ● <tool en ejecución> · 4✓ 2?` en color de acento; cuando el tool
  termina, `riel ● <tool> ✓`; en reposo, `riel · último: <tool>`.

Los dos datos entran por caminos distintos:

| Dato | Camino |
|---|---|
| Ledger | `host.state.cwd` → `GET /api/plugins/riel/ledger?worktree=<cwd>` (cada 5 s, y de inmediato al terminar un tool) |
| Actividad | `host.onEvent('tool.start' \| 'tool.complete')` — el tap del gateway — más `host.state.busy` para el turno en curso |

El endpoint lo sirve `dashboard/plugin_api.py`, el backend del plugin montado por
el gateway en el proceso del agente, y normaliza el mirror de `rielctl todo` vía
`dashboard/ledger_status.py`: el formato del ledger sigue teniendo un solo dueño
(el plugin no re-parsea `.riel/ledger.md`) y el renderer nunca lee el disco —
solo `<worktree>/.riel/ledger.md` puede salir, y solo como contadores + los
titulares de goal/next.

Un clic dispara un toast con `Goal → Next` y el último tool; el tooltip lleva el
goal, el next, los contadores y el detalle del tool (duración, error).

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

## El gate (`pre_verify`)

Riel dice que un checkpoint ✓ solo existe con el gate real detrás; hasta ahora
era prosa. El hook lo vuelve condición del turno: si un turno **editó código**
dentro de un worktree con `.riel/ledger.md` y ese ledger tiene claims sin ningún
✓ con evidencia, el plugin devuelve `{"action": "continue", "message": …}` y el
agente sigue en vez de cerrar.

| Límite | Cómo |
|---|---|
| Opt-in por worktree | sin `.riel/ledger.md` encima de los archivos editados no hay aviso: no es un nag global |
| Un solo aviso por turno | `plugins.entries.riel.settings.gate_attempts` (default 1); por encima de eso Hermes corta en `agent.max_verify_nudges` (3) |
| Nunca bloquea | cualquier fallo (sin ledger, sin `rielctl`, timeout, ledger ilegible) devuelve `None` y el turno cierra |
| Apagable | `plugins.entries.riel.settings.gate: false` |

Qué worktree se juzga: primero el de los **archivos editados** (un turno puede
editar otro repo), y si ninguno es un worktree con ledger, el cwd de la sesión.
El ✓ cuenta como evidencia cuando su línea trae `— verified by:`.

## Verificación

```bash
make test          # incluye tests/test_plugin_vendor.py (hash + handlers end-to-end)
hermes plugins doctor hermes_plugin/riel --ci   # mismo discovery/registro que usa Hermes
```
