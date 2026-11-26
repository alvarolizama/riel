# Project: {{name}}

<!-- riel-project/v1 -->

## Objective
<!-- ONE sentence: what the whole project produces. Each shaping below closes
     one question on the way there; the project is their order, not their
     content. The questions live in the shapings, never copied here. -->

{{objective}}

## Graph
<!-- The execution order of the shapings. One node per shaping, and one
     shaping is one run and one PR. The list register chains linearly; use
     mermaid when tracks branch or run in parallel. A node label is the
     shaping's path, its uid (shp_xxxxxxxx) or its slug.

     Progress is derived, never written here: a node is done when the contract
     bound to that shaping in .riel/runs/<slug>.md is done. `project status`
     reads that evidence and names the next shaping to run. -->
- S1: .riel/shapings/{{slug}}.md
