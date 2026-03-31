import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Proxy live working-staging HTML preview (same assembly as orchestrator /working-staging/{id}/preview).
 */
export async function GET(
  request: Request,
  context: { params: { threadId: string } },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { threadId } = context.params;
  const url = new URL(request.url);
  const bundle = url.searchParams.get("bundle_id");
  const target = new URL(
    `${base}/orchestrator/working-staging/${encodeURIComponent(threadId)}/preview`,
  );
  if (bundle) {
    target.searchParams.set("bundle_id", bundle);
  }
  try {
    const res = await fetch(target.toString(), {
      cache: "no-store",
      redirect: "follow",
    });
    const text = await res.text();
    const ct = res.headers.get("content-type") ?? "text/html; charset=utf-8";
    return new NextResponse(text, {
      status: res.status,
      headers: {
        "Content-Type": ct,
        "Cache-Control": "private, no-store",
        ...(res.headers.get("content-security-policy")
          ? { "Content-Security-Policy": res.headers.get("content-security-policy")! }
          : {}),
      },
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}
