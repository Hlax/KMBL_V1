# MEMORY.MD

Optional local scratch; **not** orchestration state.

- **KMBL** persisted data is canonical for runs, threads, and checkpoints.
- Do not treat this file as continuity, hidden memory, or a substitute for payload fields.
- Do not store persona, chat history, or cross-invocation “soul” content here.

Each KMBL invocation is authoritative; this file must never override **event_input** or **current_state_summary** from the payload.
