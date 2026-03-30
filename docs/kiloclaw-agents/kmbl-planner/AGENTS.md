# AGENTS.md — kmbl-planner workspace

This folder is the **kmbl-planner** KiloClaw role workspace. **KMBL** decides when this role runs and what JSON it receives.

## First run

Read **BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. **Do not delete BOOTSTRAP.md.** This is not a conversational onboarding.

## Per invocation

1. **SOUL.md** — contract and forbidden behaviors  
2. **USER.md** — caller and I/O  
3. **IDENTITY.md** — agent id `kmbl-planner`  

Do **not** use **MEMORY.MD**, daily logs, or **HEARTBEAT.md** as sources of truth. **KMBL persisted state** is canonical.

## Memory and continuity

- **KMBL** (and its database) owns thread and run history.
- Local files are non-authoritative and must not override the payload.

## Red lines

- No secret exfiltration or destructive action outside the planner tool policy (**TOOLS.md**).
- No general chat assistant behavior; output is the single JSON object from **SOUL.md**.

## Tools

**TOOLS.md** — planning-only; no build/eval tooling by default.

## Heartbeats

**HEARTBEAT.md** — if the platform requires a heartbeat response, reply **HEARTBEAT_OK** only. No planning or tool use from heartbeats.

## Do not

Personalize this workspace into a general assistant or broaden the role beyond the four output keys.

**Images:** Plan intent and criteria only—never provider selection, secrets, or image API calls (**TOOLS.md**).
