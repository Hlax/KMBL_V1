"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Props = {
  stagingSnapshotId: string;
  status: string;
  currentRating?: number | null;
  currentFeedback?: string | null;
};

const ratingLabels: Record<number, string> = {
  1: "Reject",
  2: "Poor",
  3: "OK",
  4: "Good",
  5: "Excellent",
};

export function StagingRatingSection({
  stagingSnapshotId,
  status,
  currentRating,
  currentFeedback,
}: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [selectedRating, setSelectedRating] = useState<number | null>(currentRating ?? null);
  const [feedback, setFeedback] = useState(currentFeedback ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (status === "rejected") {
    return null;
  }

  async function onRate(rating: number) {
    setMsg(null);
    setErr(null);
    setBusy(true);
    setSelectedRating(rating);
    try {
      const res = await fetch(
        `/api/staging/${encodeURIComponent(stagingSnapshotId)}/rate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rating,
            feedback: feedback.trim() || undefined,
          }),
        },
      );
      const text = await res.text();
      if (res.status === 200) {
        setMsg(`Rated ${rating}/5 — ${ratingLabels[rating]}`);
        router.refresh();
        return;
      }
      setErr(text);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="op-rating-section" style={{ 
      background: "var(--surface-alt, #1a1a2e)", 
      borderRadius: "8px", 
      padding: "1rem 1.25rem",
      marginBottom: "1rem",
      border: "1px solid var(--border, #333)"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>Rate this build:</span>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onRate(n)}
              disabled={busy}
              className={`op-btn ${selectedRating === n ? "op-btn--primary" : ""}`}
              style={{
                minWidth: "2.5rem",
                fontSize: "1rem",
                padding: "0.4rem 0.6rem",
                opacity: selectedRating && selectedRating !== n ? 0.5 : 1,
              }}
              title={ratingLabels[n]}
            >
              {n}
            </button>
          ))}
        </div>
        <span className="muted small" style={{ display: "flex", gap: "0.5rem" }}>
          <span style={{ color: "#e74c3c" }}>1=Reject</span>
          <span>·</span>
          <span style={{ color: "#27ae60" }}>5=Excellent</span>
        </span>
        {currentRating && (
          <span className="muted small">
            (Current: <strong>{currentRating}/5</strong>)
          </span>
        )}
      </div>
      
      <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.75rem", alignItems: "flex-start", flexWrap: "wrap" }}>
        <input
          type="text"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Feedback (optional) — what's wrong or could be better?"
          style={{
            flex: "1 1 300px",
            padding: "0.5rem 0.75rem",
            borderRadius: "4px",
            border: "1px solid var(--border, #444)",
            background: "var(--surface, #0d0d1a)",
            color: "var(--fg, #fff)",
            fontSize: "0.9rem",
          }}
        />
        {currentFeedback && (
          <span className="muted small" style={{ alignSelf: "center" }}>
            Previous: "{currentFeedback.slice(0, 40)}{currentFeedback.length > 40 ? "..." : ""}"
          </span>
        )}
      </div>

      {msg && <p className="op-ok" style={{ margin: "0.5rem 0 0" }}>{msg}</p>}
      {err && <p className="op-err" style={{ margin: "0.5rem 0 0" }} role="alert">{err}</p>}
    </div>
  );
}
