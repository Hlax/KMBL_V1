import { NextResponse } from "next/server";

import {
  fallbackRunsList,
  isOrchestratorRouteNotFound,
  parseJsonSafe,
} from "@/lib/orchestrator-proxy";

export const dynamic = "force-dynamic";

/**
 * Pass I: GET /api/runs?... → orchestrator GET /orchestrator/runs (same query string).
 * Persisted run index only — no snapshots.
 */
export async function GET(request: Request) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  const target = `${base}/orchestrator/runs${qs ? `?${qs}` : ""}`;
  try {
    const res = await fetch(target, { cache: "no-store" });
    const text = await res.text();
    const parsed = parseJsonSafe(text);
    if (isOrchestratorRouteNotFound(res.status, parsed.ok ? parsed.value : null, !parsed.ok)) {
      return NextResponse.json(fallbackRunsList(), { status: 200 });
    }
    const data = parsed.ok ? parsed.value : text;
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      {
        error: e instanceof Error ? e.message : String(e),
      },
      { status: 502 },
    );
  }
}
