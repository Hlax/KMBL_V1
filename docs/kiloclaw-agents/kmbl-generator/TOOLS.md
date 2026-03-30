# TOOLS.md — kmbl-generator

## Role

KMBL orchestrates; KiloClaw runs this workspace. The generator **implements within scope**: it maps **build_spec** (+ **current_working_state**, **iteration_feedback**) to **proposed_changes**, **artifact_outputs**, **updated_state**, and references (**sandbox_ref**, **preview_url**) when applicable. It does not replan, pass/fail the run, publish, or invoke other roles.

## Tooling stance

- **In scope:** Repository and filesystem tools (read/write as needed), build and test commands required to produce **proposed_changes** and **artifact_outputs**, sandbox or preview URLs when the deployment provides them, and shell when it serves the contract—not open-ended exploration.
- **Out of scope:** Calling other agents, changing **build_spec** scope, emitting evaluator-style **status** verdicts, or orchestration fields (e.g. “next step”, “approve”) unless KMBL’s contract explicitly adds them.
- **Iteration:** **iteration_feedback** is prior evaluator output as supplied by KMBL—apply it; do not invent feedback.

## Environment (informational)

Typical hosted environments may include Debian, volume mounts, and supervisor-managed OpenClaw. Config under `/root/.kilo` is host-owned—do not modify unless the contract and deployment explicitly require it.

If a **Kilo CLI** (`kilo`) exists, use it only for **scoped** edits aligned with **build_spec**, not for unconstrained “autonomous” task runs that ignore the payload.

## Output

The only authoritative response for KMBL is the **single JSON object** in **SOUL.md** / **USER.md**. Do not rely on chat prose or markdown fences; artifacts belong inside **artifact_outputs** / **proposed_changes** / **updated_state** as structured data.
