# MEMORY.MD

Optional local scratch; **not** orchestration state.

- **KMBL** owns runs, threads, and checkpoints.
- Do not treat this file as hidden continuity or memory for contract correctness.
- No persona or chat-style logs here.

Payload fields (**build_spec**, **current_working_state**, **iteration_feedback**) are the only authoritative context per invocation.
