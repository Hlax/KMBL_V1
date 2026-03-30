"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Props = {
  graphRunId: string;
  resumeEligible: boolean;
  resumeExplanation: string | null;
  retryDeferredNote: string | null;
};

export function RunResumeActions({
  graphRunId,
  resumeEligible,
  resumeExplanation,
  retryDeferredNote,
}: Props) {
  const router = useRouter();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function doResume() {
    setMsg(null);
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/runs/${encodeURIComponent(graphRunId)}/resume`,
        { method: "POST" },
      );
      const text = await res.text();
      let data: { detail?: unknown; error?: string; ok?: boolean } = {};
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
            : typeof data.error === "string"
              ? data.error
              : text.slice(0, 300);
        setErr(m || `HTTP ${res.status}`);
        return;
      }
      setMsg("Resume accepted — refreshing from server.");
      router.refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="op-card" style={{ marginBottom: "1.25rem" }}>
      <h2 className="op-section-title">Runtime actions</h2>
      <p className="muted small">
        Mutations apply on the orchestrator only; this page refreshes from persisted state — no
        optimistic status replacement.
      </p>
      <div className="op-field">
        <button
          type="button"
          className="op-btn op-btn--primary"
          disabled={!resumeEligible || busy}
          onClick={() => void doResume()}
        >
          {busy ? "Working…" : "Resume"}
        </button>
        {resumeExplanation ? (
          <p className="small" style={{ marginTop: "0.5rem" }}>
            {resumeExplanation}
          </p>
        ) : null}
      </div>
      <div className="op-field">
        <span>Retry</span>
        <button type="button" className="op-btn" disabled>
          Retry (not available)
        </button>
        {retryDeferredNote ? (
          <p className="muted small">{retryDeferredNote}</p>
        ) : null}
      </div>
      {msg ? <p className="op-ok">{msg}</p> : null}
      {err ? (
        <p className="op-err" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}
