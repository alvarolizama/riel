# Riel — plugin de Hermes (v2.0.0)

El paquete ES el producto: la prosa, el motor, las tools, el gate y el chip.
v2.0.0 es un **clean break**: el estado vive en `.riel/run.md` (riel-run/v1) y
no hay conversor ni compatibilidad con las tools v1 (`riel_plan`, `riel_seam`).

**La superficie son tools, nunca una línea de comandos.** Siete tools tipadas —
`riel_guide` (la prosa), `riel_shape` (`new|validate|fetch`, la evidencia antes
del plan), `riel_run` (`new|validate|activate|rebase|status|slice|fetch`, una
sola puerta para `.riel/run.md`), `riel_note` (el estado y sus gates),
`riel_clean`, `riel_check` — sobre el motor (stdlib, sin deps, que
viaja dentro del paquete y decide nada: el formato tiene un solo dueño). Ninguna
tool recibe argv; el campo `tool` de la respuesta es provenance (qué tool
contestó) y el `verb` cuando la tool lo lleva, nunca una interfaz. Toda
respuesta — positivas y negativas — habla el mismo sobre de seis llaves
(`tool, worktree, exit_code, passed, stdout, stderr`).

## El modelo run/shaping

- **`shape new` y `run new` IMPRIMEN** sus plantillas (el editor es el camino de
  escritura): el agente escribe `.riel/run.md` (plan + Metadata + Execution
  state + Core + Open + Evidence, formato estricto `riel-run/v1` que hashea
  plan+shaping) y `.riel/shaping.md` a mano, luego `run validate` y
  `run activate`.
- **`fetch` exige sha256** — el body va pineado, nunca confiado; HTTPS,
  atómico, acotado, y jamás activa lo que escribe.
- **`riel_note` ejecuta gates**: `gates: ["G1"], command: "<comando real>",
  covering: "<alcance>", claims: ["P1"]` — el MOTOR corre el comando, captura
  el exit code real y registra la evidencia `E#`. Nadie pasa un exit code.
- **`run status`** responde UN objeto JSON del estado del run.

## La prosa viaja acá, y se lee por una sola puerta, por secciones

`guide/` trae los topics que el índice lista: sin argumento `riel_guide()`
devuelve el índice; con `topic` devuelve el **índice de secciones** de esa
guía; con `section` sólo esa rebanada, y `full=true` el cuerpo entero. La
sección `riel` del prompt publica lo que el catálogo de tools no puede —que la
prosa existe— más el estado del worktree. **No se registra ningún skill**:
un skill de plugin nunca entra en `<available_skills>`, así que habría dos
puertas y dos formas de que la prosa se desincronice.

## Instalación (usuario)

```bash
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel
```

El instalador clona el repo y **mueve solo este subdirectorio** a
`~/.hermes/plugins/riel` — el checkout no sobrevive. Por eso el paquete es
autocontenido: `guide/`, `engine/` y `templates/` viajan adentro y **son la
fuente** — no hay copia ni paso de build. Se editan acá y el suite
(`tests/test_plugin_vendor.py`) verifica que no reaparezca un árbol duplicado,
y que manifiesto, README y motor digan todos `2.0.0`.

## Instalación (desarrollo)

```bash
HERMES_HOME=~/.hermes/profiles/coder hermes plugins install \
  "file://$(pwd)#hermes_plugin/riel" --enable
```

Los plugins son **por perfil** (`$HERMES_HOME/plugins/`) y la instalación es
siempre una copia de un commit: no hay symlink, ni en dev.

## Cómo resuelve el worktree

El motor resuelve `.riel/` desde el parámetro explícito, nunca del cwd del
proceso. Cada llamada resuelve la raíz así:

1. argumento `worktree` de la tool (ruta explícita),
2. el cwd registrado de la sesión (el mismo que usa el tool `terminal`),
3. `TERMINAL_CWD`,
4. el cwd del proceso (solo fuera de un gateway multiplex).

Y corre el motor **en el mismo proceso** con `run_verb(argv, worktree=…,
out=…, err=…)`: sinks de texto explícitos por llamada (nunca un redirect
global), sin chdir compartido entre sesiones concurrentes. Solo cuando el
motor no puede cargarse en ese intérprete cae al subproceso con
`--worktree <worktree>` — y una carga que falla no envenena el loader: la
llamada siguiente lo reintenta.

## Mitad desktop — un chip en el statusbar

`desktop/plugin.js` registra un chip en `statusBar.right`, y es el único:

- **Solo existe si hay un run**: `.riel/run.md` activo o draft en el worktree en foco.
  Sin run, el statusbar no muestra nada.
- **En reposo**: `Riel` — el run existe; un clic abre el modal con el run
  renderizado (Streamdown dibuja las secciones y el grafo mermaid).
- **Turno en curso**: `Riel ● <tool>` — el punto pulsa en color de acento y
  nombra la tool viva del chat enfocado (p. ej. `Riel ● riel_note`).

El estado detallado del run no vive en la barra: lo relee el modelo con
`riel_run status` y lo hace cumplir el gate. Los dos datos entran por caminos
distintos:

| Dato | Camino |
|---|---|
| Run | `host.state.cwd` / `session.info` → `GET /api/plugins/riel/run?worktree=<cwd>` (al abrir, al cambiar de foco y de inmediato al terminar un tool) |
| Ejecución | `host.onEvent('tool.start' \| 'tool.complete')` — el tap del gateway — más `host.state.busy` para el turno en curso |

`GET /run` responde `{present, worktree, markdown, status}`: el markdown
verbatim (acotado, resuelto contra symlinks) para el modal y el objeto JSON de
`run status` para el estado. Las rutas viejas (`/ledger`, `/contract`) ya no
existen, y `/health` no filtra el cwd del gateway. Todas las rutas son `def`
síncronas: FastAPI las corre en su threadpool y una llamada acotada al motor
nunca bloquea el event loop.

Los interruptores siguen vivos como comandos de ⌘K:
`Riel: encender/apagar el gate` y `… el bloque del prompt`.

## El gate (`pre_verify`)

Mientras haya un run ACTIVO en el worktree editado, el turno no cierra con
claims o gates pendientes: el plugin consulta `run status` (en-proceso, por el
mismo camino seguro que las tools) y devuelve `{"action": "continue", …}`.

| Límite | Cómo |
|---|---|
| Opt-in por worktree | sin `.riel/run.md` encima de los archivos editados no hay aviso; un ledger v1 solo NO habilita el gate |
| Solo runs activos | un run escrito pero sin `activate` es asunto del agente, no del gate |
| Un solo aviso por turno | `plugins.entries.riel.settings.gate_attempts` (int, 0–10, default 1); por encima de eso Hermes corta en `agent.max_verify_nudges` (3) |
| Nunca bloquea | cualquier fallo (sin run, sin motor, estado ilegible) devuelve `None` y el turno cierra |
| Sin subproceso | el gate usa el motor en-proceso (cargador seguro), nunca un fallback de subproceso |
| Apagable | `plugins.entries.riel.settings.gate: false` |

Qué worktree se juzga: primero el de los **archivos editados** (un turno puede
editar otro repo), y si ninguno es un worktree con run, el cwd de la sesión.

## Verificación

```bash
make test          # incluye tests/test_plugin_*.py (paquete + handlers + chip)
hermes plugins validate hermes_plugin/riel   # mismo discovery/registro que usa Hermes
```
