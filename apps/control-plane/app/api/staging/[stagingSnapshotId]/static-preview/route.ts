import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Proxy GET /orchestrator/staging/{id}/static-preview — assembled HTML for static FE artifacts.
 * Pass-through body and status; same-origin iframe for staging review.
 */
export async function GET(
  request: Request,
  context: { params: { stagingSnapshotId: string } },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { stagingSnapshotId } = context.params;
  const url = new URL(request.url);
  const bundle = url.searchParams.get("bundle_id");
  const target = new URL(
    `${base}/orchestrator/staging/${encodeURIComponent(stagingSnapshotId)}/static-preview`,
  );
  if (bundle) {
    target.searchParams.set("bundle_id", bundle);
  }
  try {
    const res = await fetch(target.toString(), { cache: "no-store" });
    const text = await res.text();
    const ct = res.headers.get("content-type") ?? "text/html; charset=utf-8";
    const headers = new Headers();
    headers.set("Content-Type", ct);
    headers.set("Cache-Control", "private, no-store");
    const csp = res.headers.get("content-security-policy");
    if (csp) {
      headers.set("Content-Security-Policy", csp);
    }
    const xcto = res.headers.get("x-content-type-options");
    if (xcto) {
      headers.set("X-Content-Type-Options", xcto);
    }
    return new NextResponse(text, { status: res.status, headers });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}
