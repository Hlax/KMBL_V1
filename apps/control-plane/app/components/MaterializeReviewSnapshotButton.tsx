"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Props = {
  threadId: string;
  /** Optional label override */
  label?: string;
  className?: string;
};

/**
 * Calls control-plane POST /api/working-staging/{threadId}/review-snapshot → orchestrator materialize.
 */
export function MaterializeReviewSnapshotButton({
  threadId,
  label = "Materialize review snapshot",
  className,
}: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onClick = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch(
        `/api/working-staging/${encodeURIComponent(threadId)}/review-snapshot`,
        { method: "POST" },
      );
      const text = await res.text();
      let data: { staging_snapshot_id?: string; detail?: unknown; error?: string } = {};
      try {
        data = JSON.parse(text) as typeof data;
      } catch {
        setMsg(text.slice(0, 200));
        return;
      }
      if (!res.ok) {
        const raw = data as { detail?: unknown; error?: string };
        let detail = String(raw.error ?? res.status);
        const d = raw.detail;
        if (typeof d === "string") detail = d;
        else if (d !== undefined) {
          try {
            detail = JSON.stringify(d);
          } catch {
            detail = String(d);
          }
        }
        setMsg(`Failed: ${detail}`);
        return;
      }
      const sid = data.staging_snapshot_id;
      setMsg(sid ? `Created snapshot ${sid.slice(0, 8)}… — opening review.` : "Created.");
      if (sid) {
        router.push(`/review/staging/${encodeURIComponent(sid)}`);
      } else {
        router.refresh();
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={className}>
      <button
        type="button"
        className="op-btn"
        disabled={busy}
        onClick={() => void onClick()}
      >
        {busy ? "Working…" : label}
      </button>
      {msg ? (
        <span className="muted small" style={{ marginLeft: "0.5rem" }} role="status">
          {msg}
        </span>
      ) : null}
    </span>
  );
}
