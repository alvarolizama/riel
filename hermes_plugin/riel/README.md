# Riel — plugin de Hermes (v3.0.0)

El paquete ES el producto: la prosa, el motor, las tools, el gate y el chip.
El estado vive en `.riel/run.md` (riel-run/v1), la evidencia de una pregunta en
`.riel/shapings/<slug>.md` (riel-shaping/v3) y el orden de varias preguntas en
`.riel/project.md` (riel-project/v1). No hay conversor ni compatibilidad con las
tools v1 (`riel_plan`, `riel_seam`).

**La superficie son tools, nunca una línea de comandos.** Siete tools tipadas —
`riel_guide` (la prosa), `riel_project` (`new|validate|status`, el orden de los
shapings), `riel_shape` (`new|validate`, una pregunta), `riel_run`
(`new|validate|activate|rebase|status|slice|archive`, una sola puerta para
`.riel/run.md`), `riel_note` (el estado y sus gates), `riel_clean`, `riel_check`
— sobre el motor (stdlib, sin deps, que viaja dentro del paquete y decide nada:
el formato tiene un solo dueño). Ninguna tool recibe argv; el campo `tool` de la
respuesta es provenance (qué tool contestó) y el `verb` cuando la tool lo lleva,
nunca una interfaz. Toda respuesta — positivas y negativas — habla el mismo
sobre de seis llaves (`tool, worktree, exit_code, passed, stdout, stderr`).

## El modelo project / shaping / run

- **Riel explica y valida; no authora.** `project new`, `shape new` y `run new`
  IMPRIMEN sus plantillas (el editor es el camino de escritura). Un sistema de
  proyectos, un MCP, una API o un copy-paste escribe los bytes; `validate`
  decide si están bien formados. No hay fetch: el transporte es asunto del
  productor, el Markdown es el contrato.
- **Un shaping = una pregunta y una respuesta.** `.riel/shapings/<slug>.md` con
  marker `<!-- riel-shaping/v3 id:shp_xxxxxxxx -->`. El uid es la identidad
  (sobrevive un rename), el slug la ubicación y el sha256 la revisión. Siete
  secciones en orden: `Question` (UNA línea, UN `?`), `Answer` (UNA línea, sin
  `?`, con `— supported by F#` o `— decided by: owner`), `Findings` (dossiers
  `### F#` con cuerpo, source y su `#### Diagram` opcional), `Facts`,
  `Not wanted` (lo que NO queremos, con la razón), `What we want` (We need ·
  Claim seeds · Scope) y `Open` AL FINAL (el residuo, con su test más barato).
  El Basis congela el heading + source + confidence, nunca el cuerpo.
- **Las fases son secciones.** `## Phases` carga el DAG general en su preámbulo
  (mermaid entre fases, lista `- F1 → F2`, o el orden de los headings) y luego un
  `### F#: <título>` por fase, cada una con sus steps y sus propios `#### Claims`,
  `#### Gates` y `#### Deliverable`. La membresía es ESTRUCTURAL: no hay sufijo
  `— phase:` ni gates globales. Los steps se numeran por fase (`F1S1`, `F1S2`…),
  así que insertar un step no renumera los anchors de otra fase: `§F1#2` es estable.
  `Constraints` y `DO NOT` son globales — un run es un shaping es un PR.
- **Un run ejecuta un shaping.** La Definition lo declara en `### Shaping` (path o
  uid); `activate` valida ese shaping, resuelve los anchors `shaping:F#` contra
  él, congela los findings en `### Basis` y registra path + uid + sha256 en
  Metadata. Editar el shaping ligado marca stale (exit 3) y pide `rebase`;
  editar un shaping hermano no.
- **Un project ordena los shapings.** `.riel/project.md` con `## Objective` y
  `## Graph` (nodos `S#` que son shapings, lista lineal o mermaid con ramas).
  `project status` DERIVA el progreso: un nodo está done cuando el run archivado
  en `.riel/runs/<slug>.md` está done. No escribe estado, no tiene gates propios.
- **`run archive`** mueve el run terminado a `.riel/runs/<slug>.md` (verificado,
  sin poda) y libera el worktree para el siguiente shaping. Un worktree sostiene
  un solo run activo: los tracks paralelos van en worktrees aparte, un PR cada uno.
- **`riel_note` ejecuta gates**: `gates: ["G1"], command: "<comando real>",
  covering: "<alcance>", claims: ["P1"]` — el MOTOR corre el comando, captura
  el exit code real y registra la evidencia `E#`. Nadie pasa un exit code.
- **`run status`** responde UN objeto JSON del estado del run, incluido el
  shaping ligado (`path`, `id`, `sha256`).
- **`riel_clean`** borra TODO lo que está dentro de `.riel/` (run, project,
  shapings, runs, estado legacy y backups); solo queda el lock. El archivado es
  opt-in: `archive=true` copia el árbol fuera de `.riel/`
  (`~/.hermes/riel/archive/<worktree>/<ts>/`) y verifica cada sha256 ANTES de
  borrar. Sin eso no hay vuelta: `.riel/` está gitignored. Ya no hay `scope`.
- **Sin versiones viejas**: solo se lee `riel-shaping/v3`. Un shaping v1/v2 se
  rechaza, no se convierte; un `.riel/shaping.md` suelto no se lee. Un run sin
  `definition_sha256` es stale. Actualizar es re-authorar, no migrar.

## La prosa viaja acá, y se lee por una sola puerta, por secciones

`guide/` trae los topics que el índice lista (`project`, `run`, `shaping`,
`delegate`, `tools`): sin argumento `riel_guide()` devuelve el índice; con
`topic` devuelve el **índice de secciones** de esa guía; con `section` sólo esa
rebanada, y `full=true` el cuerpo entero. La sección `riel` del prompt publica
lo que el catálogo de tools no puede —que la prosa existe— más el estado del
worktree. **No se registra ningún skill**: un skill de plugin nunca entra en
`<available_skills>`, así que habría dos puertas y dos formas de que la prosa se
desincronice.

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
y que manifiesto, README y motor digan todos `3.0.0`.

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
make lint          # byte-compile de motor, paquete, scripts y tests
make validate      # dense-register + grafo + mmdc sobre README, specs, guides y templates
hermes plugins validate hermes_plugin/riel   # mismo discovery/registro que usa Hermes
```
