import { headers } from "next/headers";
import { NextResponse } from "next/server";

import {
  deriveSystemMode,
  evaluateRunsListProbe,
  systemModeLabel,
  type OrchestratorHealthBody,
} from "@/lib/system-mode";

export const dynamic = "force-dynamic";

/**
 * Aggregates orchestrator /health + two GET /orchestrator/runs probes:
 * - Direct: server → {NEXT_PUBLIC_ORCHESTRATOR_URL}/orchestrator/runs (orchestrator truth)
 * - Proxied: server → same-origin /api/runs (browser-facing path; catches CP/env misconfig)
 */
export async function GET() {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  const orchestratorUrlSet = Boolean(base);

  let healthReachable = false;
  let healthBody: OrchestratorHealthBody = null;
  if (orchestratorUrlSet) {
    try {
      const res = await fetch(`${base}/health`, { cache: "no-store" });
      const text = await res.text();
      healthReachable = res.ok;
      try {
        healthBody = JSON.parse(text) as OrchestratorHealthBody;
      } catch {
        healthBody = null;
      }
    } catch {
      healthReachable = false;
    }
  }

  let directOrchestratorRunsListHealthy = false;
  let directProbe: ReturnType<typeof evaluateRunsListProbe> | null = null;
  if (orchestratorUrlSet) {
    try {
      const res = await fetch(`${base}/orchestrator/runs?limit=1`, { cache: "no-store" });
      const text = await res.text();
      directProbe = evaluateRunsListProbe(res.status, text);
      directOrchestratorRunsListHealthy = directProbe.healthy;
    } catch {
      directOrchestratorRunsListHealthy = false;
      directProbe = {
        healthy: false,
        routeNotFound: false,
        backendUnimplemented: false,
      };
    }
  }

  let controlPlaneProxyRunsResponseOk = false;
  let proxyProbe: ReturnType<typeof evaluateRunsListProbe> | null = null;
  try {
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
    const proto = h.get("x-forwarded-proto") ?? "http";
    const probeUrl = `${proto}://${host}/api/runs?limit=1`;
    const res = await fetch(probeUrl, { cache: "no-store" });
    controlPlaneProxyRunsResponseOk = res.ok;
    const text = await res.text();
    proxyProbe = evaluateRunsListProbe(res.status, text);
  } catch {
    controlPlaneProxyRunsResponseOk = false;
    proxyProbe = {
      healthy: false,
      routeNotFound: false,
      backendUnimplemented: false,
    };
  }

  const proxyUsedFallback = proxyProbe?.backendUnimplemented === true;

  const mode = deriveSystemMode({
    orchestratorUrlSet,
    healthReachable,
    healthBody,
    directOrchestratorRunsListHealthy,
    controlPlaneProxyRunsResponseOk,
    proxyUsedFallback,
  });

  const { title, detail } = systemModeLabel(mode);

  return NextResponse.json({
    mode,
    title,
    detail,
    orchestrator_url_configured: orchestratorUrlSet,
    health_reachable: healthReachable,
    orchestrator_runs_list_direct_healthy: orchestratorUrlSet
      ? directOrchestratorRunsListHealthy
      : null,
    orchestrator_runs_list_direct_route_not_found: directProbe?.routeNotFound ?? null,
    control_plane_proxy_runs_response_ok: controlPlaneProxyRunsResponseOk,
    control_plane_proxy_runs_backend_unimplemented: proxyUsedFallback,
    control_plane_proxy_runs_route_not_found: proxyProbe?.routeNotFound ?? false,
  });
}
