/**
 * Base URL for server-side fetch() to the FastAPI orchestrator (no path suffix).
 *
 * Resolution order matches operational expectations: same URL as system-mode and
 * most `/api/*` proxies, with a legacy override for older `.env` files.
 */
export function getOrchestratorServerOrigin(): string {
  const pub = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "");
  if (pub) return pub;
  const legacy = process.env.ORCHESTRATOR_ORIGIN?.trim().replace(/\/$/, "");
  if (legacy) return legacy;
  return "http://127.0.0.1:8010";
}
