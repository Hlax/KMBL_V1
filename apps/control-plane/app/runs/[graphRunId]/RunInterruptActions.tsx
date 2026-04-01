"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Props = {
  graphRunId: string;
  status: string;
  interruptRequestedAt?: string | null;
};

/**
 * Cooperative interrupt: persists request; graph exits at next boundary (not instant kill).
 */
export function RunInterruptActions({
  graphRunId,
  status,
  interruptRequestedAt,
}: Props) {
  const router = useRouter();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const terminal =
    status === "completed" ||
    status === "failed" ||
    status === "interrupted";
  const canRequest =
    !terminal && (status === "starting" || status === "running");
  const pendingInterrupt =
    status === "interrupt_requested" || Boolean(interruptRequestedAt);

  async function requestInterrupt() {
    setMsg(null);
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/runs/${encodeURIComponent(graphRunId)}/interrupt`,
        { method: "POST" },
      );
      const text = await res.text();
      let data: { detail?: unknown; message?: string } = {};
      try {
        data = JSON.parse(text) as typeof data;
      } catch {
        setErr(text.slice(0, 300));
        return;
      }
      if (!res.ok) {
        const d = data.detail;
        const m =
          typeof d === "object" && d !== null && "message" in d
            ? String((d as { message?: string }).message)
            : typeof data.message === "string"
              ? data.message
              : text.slice(0, 300);
        setErr(m || `HTTP ${res.status}`);
        return;
      }
      setMsg(
        "Interrupt requested — the run will stop at the next planner/generator/evaluator/staging boundary. Refresh to see status.",
      );
      router.refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (terminal) {
    return null;
  }

  return (
    <div className="op-field" style={{ marginTop: "0.75rem" }}>
      <span>Interrupt</span>
      <button
        type="button"
        className="op-btn"
        disabled={!canRequest || busy || pendingInterrupt}
        onClick={() => void requestInterrupt()}
        title="Cooperative stop — not an immediate process kill"
      >
        {busy
          ? "Requesting…"
          : pendingInterrupt
            ? "Interrupt pending…"
            : "Request interrupt"}
      </button>
      {pendingInterrupt ? (
        <p className="muted small" style={{ marginTop: "0.35rem" }}>
          Interrupt is persisted. The graph will exit cleanly at the next boundary; this can take a
          moment.
        </p>
      ) : (
        <p className="muted small" style={{ marginTop: "0.35rem" }}>
          Stops cooperatively after the current step — refresh keeps timeline and status from the
          server.
        </p>
      )}
      {msg ? <p className="op-ok">{msg}</p> : null}
      {err ? (
        <p className="op-err" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}
