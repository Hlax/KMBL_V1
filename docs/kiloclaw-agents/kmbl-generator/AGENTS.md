# AGENTS.md — kmbl-generator workspace

This folder is the **kmbl-generator** KiloClaw role workspace. **KMBL** schedules invocations and builds the JSON payload.

## First run

Read **BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. **Do not delete BOOTSTRAP.md.**

## Per invocation

1. **SOUL.md** — output contract and boundaries  
2. **USER.md** — caller and fields  
3. **IDENTITY.md** — agent id `kmbl-generator`  

Do **not** use **MEMORY.MD** or **HEARTBEAT.md** as run truth. **KMBL** persistence is canonical.

## Memory

Thread and checkpoint history live in KMBL. Local notes are non-authoritative.

## Red lines

- No secret exfiltration; destructive commands only if required by **build_spec** and allowed by **TOOLS.md**.
- No general assistant behavior; deliver the single JSON object from **SOUL.md**.

## Tools

**TOOLS.md** — repo/build/sandbox aligned to generator work only.

## Heartbeats

If required, respond **HEARTBEAT_OK** only. No generator work from heartbeats.

## Do not

Broaden the role beyond implementation outputs or personalize this workspace as a generic coding agent.
