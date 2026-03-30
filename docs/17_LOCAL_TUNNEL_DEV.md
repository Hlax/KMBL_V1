# Local orchestrator + Vercel (tunnel: ngrok / cloudflared)

Before you deploy the orchestrator to a VPS, you can expose **localhost** with a **temporary HTTPS URL** so **Vercel** (or any remote client) can call your machine. This avoids changing architecture: the control plane still uses `NEXT_PUBLIC_ORCHESTRATOR_URL` only.

## Recommended: Cloudflare Tunnel (`cloudflared`)

Free, no account required for quick `tunnel --url` runs.

1. Install: [Cloudflare Tunnel downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) (or `winget install --id Cloudflare.cloudflared` on Windows).

2. Start the orchestrator locally (e.g. port **8010**).

3. In another terminal:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8010
   ```

   The CLI prints an `https://....trycloudflare.com` (or similar) URL.

4. In **Vercel** → Project → Settings → Environment Variables, set:

   `NEXT_PUBLIC_ORCHESTRATOR_URL` = `https://<host-from-cloudflared>` (no trailing slash)

5. Redeploy the frontend (or use Preview env vars for a branch).

**Helper script (repo):** `services/orchestrator/scripts/tunnel-cloudflared.ps1` / `tunnel-cloudflared.sh`

## Alternative: ngrok

1. Install [ngrok](https://ngrok.com/download), sign up if you want stable URLs / auth.

2. With the orchestrator on 8010:

   ```bash
   ngrok http 8010
   ```

3. Use the `https://....ngrok-free.app` (or `.ngrok.io`) URL as `NEXT_PUBLIC_ORCHESTRATOR_URL` in Vercel.

**Helper script:** `services/orchestrator/scripts/tunnel-ngrok.ps1` / `tunnel-ngrok.sh`

## Security (read this)

- The tunnel **publishes your local API** to the internet. Anyone with the URL can hit `/health` and any **unauthenticated** routes you expose. Treat it as **dev-only**.
- **Do not** rely on this for production. Use a VPS + proper auth when you go live.
- Rotate URLs often; tunnel hostnames change between runs (unless you use a paid/reserved setup).
- Secrets (`SUPABASE_SERVICE_ROLE_KEY`, `KILOCLAW_API_KEY`) stay **only** in orchestrator env — never in `NEXT_PUBLIC_*`.

## Orchestrator bind address

- For tunnels, uvicorn should listen on **`127.0.0.1`** or **`0.0.0.0`** on the tunnel port (e.g. `8010`). `cloudflared`/`ngrok` connect **to** localhost; they do not need the orchestrator on the public internet directly.

## When you’re done with tunnels

Deploy the orchestrator per `services/orchestrator/DEPLOY.md` and set `NEXT_PUBLIC_ORCHESTRATOR_URL` to your stable HTTPS origin.

## Related

- `docs/16_DEPLOYMENT_ARCHITECTURE.md` — long-term Vercel + VPS split
- `apps/control-plane/.env.example` — `NEXT_PUBLIC_ORCHESTRATOR_URL` examples
