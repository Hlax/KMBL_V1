import { NextRequest, NextResponse } from "next/server";

const ORCHESTRATOR = process.env.ORCHESTRATOR_ORIGIN || "http://127.0.0.1:8010";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    const res = await fetch(`${ORCHESTRATOR}/orchestrator/runs/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }
    
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 500 }
    );
  }
}
