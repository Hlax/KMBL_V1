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

## Evaluator browser grounding (important for quality loops)

The KMBL evaluator uses **OpenClaw mcporter Playwright** to open a real browser tab against the candidate preview during evaluation. This gives the evaluator actual DOM/console/visual evidence rather than only inspecting JSON artifacts.

For this to work, the **preview URL must be browser-reachable from the OpenClaw environment**.

### What happens without a reachable preview

| Scenario | Evaluator behaviour | Retry impact |
|----------|--------------------|----|
| `KMBL_ORCHESTRATOR_PUBLIC_BASE_URL` set to tunnel URL | Full browser grounding via mcporter | Normal — retries based on real rendered evidence |
| No public base (localhost derived) | Artifact-only evaluation | **Weakly grounded** — retries capped at `KMBL_WEAKLY_GROUNDED_MAX_ITERATIONS` (default 3) to avoid token waste |
| `KMBL_EVALUATOR_ALLOW_PRIVATE_PREVIEW_FETCH=true` | Allows localhost URLs through to mcporter | Only works when OpenClaw runs **on the same machine** as the orchestrator |

### Recommended local-dev setup

1. Start a tunnel as described above (cloudflared or ngrok).
2. Set **both** env vars in your orchestrator `.env`:

   ```
   NEXT_PUBLIC_ORCHESTRATOR_URL=https://<tunnel-host>
   KMBL_ORCHESTRATOR_PUBLIC_BASE_URL=https://<tunnel-host>
   ```

   The first is for the control-plane frontend; the second tells the orchestrator to build browser-reachable preview URLs for the evaluator.

3. If OpenClaw runs **locally** on the same machine and you don't need a tunnel:

   ```
   KMBL_EVALUATOR_ALLOW_PRIVATE_PREVIEW_FETCH=true
   ```

   This bypasses the private-host gateway block so localhost preview URLs reach mcporter.

### Checking grounding status

After a graph run completes, check the evaluation report metrics:

- `evaluator_grounding_evidence_quality`: `"browser"` (good), `"artifact_only"` (weak), or `"none"` (no preview)
- `preview_grounding_mode`: raw resolution mode from orchestrator
- `preview_grounding_degraded`: `true` when grounding was expected but unavailable

If you see repeated `WEAKLY_GROUNDED_RETRY_CAP` events in the run timeline, that means the evaluator hit the retry cap because it lacked browser evidence. Fix: set `KMBL_ORCHESTRATOR_PUBLIC_BASE_URL` to a tunnel URL.
