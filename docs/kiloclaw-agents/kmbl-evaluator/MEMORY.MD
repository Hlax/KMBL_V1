# MEMORY.MD

Optional local scratch; **not** orchestration state.

- **KMBL** owns thread/run history and persisted evaluation artifacts.
- Do not use this file as hidden memory or continuity for scoring.
- No persona content.

Per invocation, **build_candidate** and criteria from the payload are authoritative.
