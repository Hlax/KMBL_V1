import { NextResponse } from "next/server";

import {
  fallbackOperatorSummary,
  isOrchestratorRouteNotFound,
  parseJsonSafe,
} from "@/lib/orchestrator-proxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/operator-summary → orchestrator GET /orchestrator/operator-summary (Pass O).
 */
export async function GET() {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const url = `${base}/orchestrator/operator-summary`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    const parsed = parseJsonSafe(text);
    if (isOrchestratorRouteNotFound(res.status, parsed.ok ? parsed.value : null, !parsed.ok)) {
      return NextResponse.json(fallbackOperatorSummary(), { status: 200 });
    }
    const data = parsed.ok ? parsed.value : text;
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}
