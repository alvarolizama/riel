# Riel — steering layer para harness/LLM

Framework propio de dirección de agentes. **Riel no crea capacidad en el
modelo: evita que se pierda.** La tesis viene de la investigación sobre
*capability-realization loss*: la pérdida entre que un modelo tiene una
capacidad y que la entrega de forma estable (trayectoria inestable, estado
que deriva, verificación ausente).

El nombre: el tren ya se mueve solo; el riel solo evita que descarrile.

Aplica a cualquier harness/LLM (DeepSeek u otro) operando sobre las
superficies que el harness expone — system prompt / primer turno, contexto
entre turns, estructura de la tarea, evaluación — sin tocar pesos ni internals.

## Componentes

| Componente | Qué dirige | Metáfora | Estado |
|---|---|---|---|
| `riel-comms` | **Trayectoria** — gramática funcional, persona, superficie mínima | el desvío: el primer turno elige la vía | ✅ skill v1 |
| `riel-ledger` | **Estado** — Goal/Core/Verified/Open/Next, re-leer en cada seam | el nivel de la vía | pendiente (fase 2) |
| `riel-contract` | **Estructura** — mermaid como contrato, verification funnel | los rieles mismos | pendiente (fase 3) |
| `riel-measure` | **Evidencia** — medir trayectorias + score/tiempo/token | verificar que el riel funciona | pendiente (fase 4) |

Cada componente es **independiente y opcional**: una tarea corta usa cero;
un loop largo puede usar los cuatro. Filosofía heredada: "usa solo la
maquinaria que la tarea se gana".

## Cómo se cargan los skills (mecánica Hermes)

Los skills NO se inyectan completos en cada conversación — solo su
nombre+descripción vive en el índice del system prompt de cada turno. Hay
tres niveles de activación:

**Nivel 1 — disponible (automático).** Skill instalado en
`~/.hermes/skills/` → su descripción aparece en el índice de cada turno →
el agente lo carga (`skill_view`) cuando la tarea hace match con el
trigger de la descripción. Por eso los primeros ~57 caracteres de la
descripción son el trigger real.

**Nivel 2 — obligatorio (soul).** Una línea en el soul (system prompt de
identidad): *"En toda conversación o brief para un LLM, aplicar el
protocolo del skill `riel-comms`."* El soul referencia al skill, nunca
incrusta su contenido (se desincronizaría y pesaría en cada turno).

**Nivel 3 — subagentes (brief).** Los subagentes de `delegate_task` tienen
acceso a los mismos skills; el brief del padre incluye *"carga y sigue el
skill riel-comms"* y el subagente lo carga él.

Regla general: el cuerpo del skill entra al contexto **solo cuando se
necesita**; el índice es lo que vive siempre.

## Instalación

```bash
# desde el repo
cp -R ~/Workspace/Repos/alvarolizama/riel/skills/riel-comms ~/.hermes/skills/

# actualizar tras cambios en el repo
cp -R ~/Workspace/Repos/alvarolizama/riel/skills/* ~/.hermes/skills/
```

Verificar: el skill debe aparecer en el índice de skills de la sesión
(`skills_list` o el listado del sistema).

## Estructura

```
riel/
├── README.md          ← este archivo
├── skills/            ← skills instalables (cp a ~/.hermes/skills/)
│   └── riel-comms/
│       └── SKILL.md
└── references/        ← evidencia destilada (apuntes locales)
```

## Evidencia de base

Destilada en Dran (contexto `personal`):

- `j-space-global-workspace-papers` — 24 fuentes verificadas (Anthropic
  global workspace, razonamiento ilegible, metacognición)
- `deepseek-v4-interfaz-y-trayectoria-we-need` — las 3 palancas del
  anclaje de trayectoria en DeepSeek
- `graph-engineering-instrucciones-agentes` — BRAID/FlowBench/mermaid
- `ledger-pattern-estado-de-agentes` — Goal/Core/Verified/Open/Next
- `capability-realization-loss` — el marco del problema
- `harness-analysis-papers-en-extension-points` — mapa paper → harness

## Honestidad sobre la evidencia

- **Medido:** las condiciones del primer turno anclan la trayectoria en
  DeepSeek (schema Minimal 5/5; con inyecciones 0/9).
- **Hipótesis:** que la trayectoria anclada mejore scores — replicación
  independiente con IC 95% [−2.6, +9.3]; un A/B no encontró ganancia.
  Riel no promete mejores resultados sin medir: eso lo hace `riel-measure`.

## Proyecto en Dran

Página `riel` (tipo project, contexto `personal`) — visión, fases, estado.
