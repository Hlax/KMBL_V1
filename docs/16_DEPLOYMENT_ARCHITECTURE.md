# Deployment architecture (KMBL v1)

Target split:

| Surface | Role |
|---------|------|
| **Control plane** | Next.js on **Vercel** — UI, server routes that call the orchestrator over HTTPS |
| **Orchestrator** | Python **FastAPI + LangGraph** on a **VPS/VM** — sole owner of graph execution and KiloClaw HTTP calls |
| **Agent runtime** | **KiloClaw / OpenClaw** on the same or another private host — not embedded in Vercel |
| **System of record** | **Supabase** (Postgres + API) |
| **Future mobile** | **Expo / React Native** — same orchestrator HTTP contracts as the web app |

## Contract stability

- **Control plane ↔ orchestrator:** HTTP JSON (`/health`, `/orchestrator/runs/start`, `/orchestrator/runs/{id}`, `/orchestrator/invoke-role`). Base URL is **always** from env (`NEXT_PUBLIC_ORCHESTRATOR_URL` on Vercel), never hardcoded to localhost in production.
- **Orchestrator ↔ KiloClaw:** `invoke_role(role_type, provider_config_key, payload)` implemented by `providers.kiloclaw` (chat completions transport today). Wire shapes validated by `kmbl_orchestrator.contracts.role_outputs`.
- **Orchestrator ↔ Supabase:** Repository pattern (`persistence/`); use service role only on the orchestrator host.

## Environment layers

1. **Local dev:** repo-root `.env` / `.env.local` for orchestrator; `apps/control-plane/.env.local` for Next.js.
2. **Vercel + local orchestrator (no VPS yet):** use **ngrok** or **cloudflared** to get an `https://…` URL to `localhost`, then set `NEXT_PUBLIC_ORCHESTRATOR_URL` on Vercel to that origin. See `docs/17_LOCAL_TUNNEL_DEV.md`.
3. **Vercel + VPS:** Project env vars for `NEXT_PUBLIC_ORCHESTRATOR_URL` (public URL of your reverse proxy, e.g. `https://orchestrator.example.com`).
4. **VPS:** Orchestrator process env (file or systemd `EnvironmentFile=`) for Supabase + KiloClaw + bind host/port. See `services/orchestrator/DEPLOY.md`.

## Security notes

- Do not expose `SUPABASE_SERVICE_ROLE_KEY` or `KILOCLAW_API_KEY` to the browser.
- KiloClaw gateway tokens are operator credentials; use Tailscale or private networking between orchestrator and gateway when possible.

## Related docs

- `docs/17_LOCAL_TUNNEL_DEV.md` — **cloudflared / ngrok** for Vercel → local orchestrator without a VPS
- `services/orchestrator/DEPLOY.md` — process manager, bind address, reverse proxy, env reload
- `.env.example` (repo root) — orchestrator + platform variables
- `apps/control-plane/.env.example` — Vercel-oriented frontend variables
