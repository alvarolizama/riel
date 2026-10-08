# Riel — plugin de Hermes

El paquete ES el producto: la prosa, el motor, las tools, el gate y el chip.

**La superficie son tools, nunca una línea de comandos.** Doce tools tipadas —
`riel_guide` (la prosa), `riel_note`, `riel_seam` (con `anchors`), `riel_resume`,
`riel_todo`, `riel_state`, `riel_context`, `riel_contract`, `riel_shaping`,
`riel_clean`, `riel_fetch`, `riel_check` — sobre el motor (un archivo stdlib que
viaja dentro del paquete y decide nada: el formato tiene un solo dueño). Ninguna
tool recibe argv; el campo `tool` de la respuesta es provenance (qué tool
contestó) y el `verb` cuando la tool lo lleva, nunca una interfaz.

**La prosa viaja acá, y se lee por una sola puerta.** `guide/` trae seis topics
(`protocol`, `ledger`, `contract`, `shaping`, `delegate`, `tools`): sin argumento
`riel_guide()` devuelve el índice, `riel_guide(topic="contract")` el cuerpo y
`riel_guide(topic="contract", section="Claim anchors")` sólo esa rebanada. La
sección `riel` del prompt publica lo que el catálogo de tools no puede —que la
prosa existe— más el estado del worktree. **No se registra ningún skill**: un
skill de plugin nunca entra en `<available_skills>` y necesitaría la sección
igual, así que habría dos puertas y dos formas de que la prosa se desincronice.
Nada que copiar a un directorio de skills, nada de `external_dirs`, nada de
symlinks.

## Instalación (usuario)

```bash
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel
```

El instalador clona el repo y **mueve solo este subdirectorio** a
`~/.hermes/plugins/riel` — el checkout no sobrevive. Por eso el paquete es
autocontenido: `guide/`, `engine/` y `templates/` viajan adentro y **son la
fuente** — no hay copia ni paso de build. Se editan acá y el suite
(`tests/test_plugin_vendor.py`) verifica que no reaparezca un árbol duplicado.

## Instalación (desarrollo)

```bash
HERMES_HOME=~/.hermes/profiles/coder hermes plugins install \\
  "file://$(pwd)#hermes_plugin/riel" --enable
```

Los plugins son **por perfil** (`$HERMES_HOME/plugins/`) y la instalación es
siempre una copia de un commit: no hay symlink, ni en dev.

## Cómo resuelve el worktree

el motor lee y escribe `.riel/` **relativo al cwd**. El handler corre dentro
del proceso de Hermes, cuyo cwd no es el worktree de la sesión, así que cada
llamada resuelve la raíz así:

1. argumento `worktree` de la tool (ruta explícita),
2. el cwd registrado de la sesión (el mismo que usa el tool `terminal`),
3. `TERMINAL_CWD`,
4. el cwd del proceso.

Y ejecuta el motor en un **subproceso** con `cwd=<worktree>`: cada llamada
tiene su propio cwd y no hay `chdir` global compartido entre sesiones
concurrentes (un gateway sirve varias a la vez).

## Mitad desktop — un chip en el statusbar

`desktop/plugin.js` registra un chip en `statusBar.right`, y es el único:

- **Solo existe si hay contrato**: `.riel/contract.md` en el worktree en foco.
  Sin contrato, el statusbar no muestra nada.
- **En reposo**: `Riel` — el plan existe; un clic abre el modal con el
  contrato renderizado (Streamdown dibuja las secciones y el grafo mermaid).
- **Turno en curso**: `Riel ● <tool>` — el punto pulsa en color de acento y
  nombra la tool viva del chat enfocado (p. ej. `Riel ● riel_note`).

El estado del ledger ya no vive en la barra: lo relee el modelo con
`riel_seam` y lo hace cumplir el gate. La barra sólo dice si este worktree
tiene plan y si se está ejecutando.

Los dos datos entran por caminos distintos:

| Dato | Camino |
|---|---|
| Contrato | `host.state.cwd` / `session.info` → `GET /api/plugins/riel/contract?worktree=<cwd>` (al abrir, al cambiar de foco y de inmediato al terminar un tool) |
| Ejecución | `host.onEvent('tool.start' \| 'tool.complete')` — el tap del gateway — más `host.state.busy` para el turno en curso |

El endpoint lo sirve `dashboard/plugin_api.py`, el backend del plugin montado por
el gateway en el proceso del agente. El renderer nunca lee el disco —
solo `<worktree>/.riel/contract.md` puede salir, y solo como markdown
verbatim para el modal.

Un clic abre el modal del contrato; el tooltip lleva el estado del turno
(`Turno en curso: <tool>`).

Los interruptores del chip viejo siguen vivos como comandos de ⌘K:
`Riel: encender/apagar el gate` y `… el bloque del prompt`.

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
| Nunca bloquea | cualquier fallo (sin ledger, sin motor, timeout, ledger ilegible) devuelve `None` y el turno cierra |
| Apagable | `plugins.entries.riel.settings.gate: false` |

Qué worktree se juzga: primero el de los **archivos editados** (un turno puede
editar otro repo), y si ninguno es un worktree con ledger, el cwd de la sesión.
El ✓ cuenta como evidencia cuando su línea trae `— verified by:`.

## Índice de contexto (`riel_context`)

`riel_context` entrega las keywords del contrato (`### Context keywords`: un
término por línea, hint de fuente opcional) y **no busca**. Los backends de
memoria viven en el memory manager del agente (`agent/memory_manager.py`), no en
el registry de tools, así que **un plugin no los alcanza**: el que busca es el
agente, con lo que tenga configurado (DRAN, su memoria, `search_files`). El tool
le dice qué términos y dónde dejar el resultado (`## Core`, máx 2).

Dos momentos, los dos donde `Core` se (re)escribe:

| Momento | Qué pasa |
|---|---|
| Abrir la tarea (`resume`/`seam`) | `riel_context` → el agente busca → `Core` (máx 2) |
| Avanzar de fase | lo mismo para la fase entrante |
| `brief slice` a un hijo | las keywords viajan en el packet; el hijo busca con su propio budget |

`riel_context` emite el mismo índice en JSON para cualquier harness, no solo
Hermes — el plugin no re-parsea el contrato.

## Verificación

```bash
make test          # incluye tests/test_plugin_vendor.py (el árbol + handlers end-to-end)
hermes plugins validate hermes_plugin/riel   # mismo discovery/registro que usa Hermes
```
