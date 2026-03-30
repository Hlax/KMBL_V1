import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Server-side probe of GET ${NEXT_PUBLIC_ORCHESTRATOR_URL}/health
 * so the browser does not need CORS on FastAPI (localhost:3000 → 127.0.0.1:8010).
 */
export async function GET() {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim() ?? "";
  const urlChecked = base
    ? `${base.replace(/\/$/, "")}/health`
    : "(NEXT_PUBLIC_ORCHESTRATOR_URL not set)/health";

  if (!base) {
    return NextResponse.json({
      reachable: false,
      urlChecked,
      httpStatus: null,
      body: null,
      error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set",
    });
  }

  try {
    const res = await fetch(urlChecked, { cache: "no-store" });
    const text = await res.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      /* keep raw text */
    }
    return NextResponse.json({
      reachable: res.ok,
      urlChecked,
      httpStatus: res.status,
      body,
      error: res.ok ? null : `HTTP ${res.status}`,
    });
  } catch (e) {
    return NextResponse.json({
      reachable: false,
      urlChecked,
      httpStatus: null,
      body: null,
      error: e instanceof Error ? e.message : String(e),
    });
  }
}
