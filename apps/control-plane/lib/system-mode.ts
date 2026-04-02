/**
 * Control-plane system mode: how truthfully the UI reflects the orchestrator.
 * fully_connected: URL set, orchestrator reachable, transport config valid, not using proxy fallbacks.
 * degraded: unreachable, misconfigured transport, or missing URL.
 * fallback: orchestrator route miss — synthetic JSON (backend_unimplemented) is being shown.
 */

import { isOrchestratorRouteNotFound, parseJsonSafe } from "./orchestrator-proxy";

export type SystemMode = "fully_connected" | "degraded" | "fallback";

export type OrchestratorHealthBody = Record<string, unknown> | null;

/** Result of probing GET /orchestrator/runs?limit=1 (direct or via Next proxy). */
export type RunsListProbeResult = {
  /** 2xx and JSON is a real orchestrator body (not FastAPI route miss, not CP synthetic fallback). */
  healthy: boolean;
  routeNotFound: boolean;
  backendUnimplemented: boolean;
};

/**
 * Classify a GET /orchestrator/runs response (direct to FastAPI or proxied through the control plane).
 * Shared by direct orchestrator probes and same-origin /api/runs probes.
 */
export function evaluateRunsListProbe(status: number, bodyText: string): RunsListProbeResult {
  const parsed = parseJsonSafe(bodyText);
  const parseFailed = !parsed.ok;
  const value = parsed.ok ? parsed.value : null;
  if (isOrchestratorRouteNotFound(status, value, parseFailed)) {
    return { healthy: false, routeNotFound: true, backendUnimplemented: false };
  }
  if (status < 200 || status >= 300) {
    return { healthy: false, routeNotFound: false, backendUnimplemented: false };
  }
  if (parseFailed || !value || typeof value !== "object" || Array.isArray(value)) {
    return { healthy: false, routeNotFound: false, backendUnimplemented: false };
  }
  const o = value as { backend_unimplemented?: unknown };
  if (o.backend_unimplemented === true) {
    return { healthy: false, routeNotFound: false, backendUnimplemented: true };
  }
  return { healthy: true, routeNotFound: false, backendUnimplemented: false };
}

export function deriveSystemMode(input: {
  orchestratorUrlSet: boolean;
  healthReachable: boolean;
  healthBody: OrchestratorHealthBody;
  /**
   * Direct GET {NEXT_PUBLIC_ORCHESTRATOR_URL}/orchestrator/runs?limit=1 from this server.
   * Catches wrong binary, missing route, or network errors even when /health is OK.
   */
  directOrchestratorRunsListHealthy: boolean;
  /**
   * Same-origin GET /api/runs?limit=1 succeeded (2xx). False e.g. when env is unset (route returns 500)
   * or the proxy cannot reach the orchestrator (502).
   */
  controlPlaneProxyRunsResponseOk: boolean;
  /** True when the CP proxy returned synthetic empty list (backend_unimplemented). */
  proxyUsedFallback?: boolean;
}): SystemMode {
  if (!input.orchestratorUrlSet) return "degraded";
  if (!input.healthReachable) return "degraded";

  const body = input.healthBody;
  const res = body && typeof body === "object" ? (body as { kiloclaw_resolution?: unknown }).kiloclaw_resolution : null;
  const kr = res && typeof res === "object" ? (res as { configuration_valid?: unknown }) : null;
  if (kr?.configuration_valid === false) return "degraded";

  const eff = body && typeof body === "object" ? (body as { kiloclaw_transport_effective?: unknown }).kiloclaw_transport_effective : null;
  if (eff === "invalid") return "degraded";

  // Control-plane /api/runs is the browser-facing path; check it before direct orchestrator probes.
  if (!input.controlPlaneProxyRunsResponseOk) return "degraded";
  if (input.proxyUsedFallback) return "fallback";
  if (!input.directOrchestratorRunsListHealthy) return "degraded";

  return "fully_connected";
}

export function systemModeLabel(mode: SystemMode): { title: string; detail: string } {
  switch (mode) {
    case "fully_connected":
      return {
        title: "System: connected",
        detail:
          "Orchestrator health OK and proxy routes are not using synthetic fallbacks for this check.",
      };
    case "degraded":
      return {
        title: "System: degraded",
        detail:
          "Orchestrator URL unset, /health unreachable, transport invalid, direct GET /orchestrator/runs failed, or the control-plane proxy returned an error for /api/runs — verify deployment topology and NEXT_PUBLIC_ORCHESTRATOR_URL on the server.",
      };
    case "fallback":
      return {
        title: "System: fallback data",
        detail:
          "GET /api/runs returned synthetic list data (backend_unimplemented) — the control-plane proxy did not get a real orchestrator response. Fix NEXT_PUBLIC_ORCHESTRATOR_URL, routing, or orchestrator version.",
      };
    default:
      return { title: "System: unknown", detail: "" };
  }
}
