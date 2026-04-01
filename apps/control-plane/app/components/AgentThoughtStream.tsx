"use client";

import { useEffect, useMemo, useState } from "react";

/**
 * Mocked “live agent console” feed for the Live Habitat surface.
 * Replace with SSE / polling when backend streaming exists.
 */
export function AgentThoughtStream({
  threadId,
  revision,
  status,
}: {
  threadId: string;
  revision: string | number | undefined;
  status: string | undefined;
}) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 4000);
    return () => clearInterval(id);
  }, []);

  const lines = useMemo(() => {
    const rid = revision != null && revision !== "" ? String(revision) : "—";
    const st = status ?? "—";
    const short = threadId.length > 12 ? `${threadId.slice(0, 8)}…` : threadId;
    const phase = tick % 4;
    const pulse =
      phase === 0
        ? "Watching working staging surface…"
        : phase === 1
          ? "Evaluating preview assembly health…"
          : phase === 2
            ? "Syncing habitat metadata…"
            : "Idle — waiting for graph activity…";
    return [
      { t: "runtime", m: `Thread ${short} · rev ${rid}` },
      { t: "state", m: `Staging status: ${st}` },
      { t: "feed", m: pulse },
      { t: "hint", m: "Streaming is mocked — connect OpenClaw / run events here later." },
    ];
  }, [threadId, revision, status, tick]);

  return (
    <div className="cp-thought-stream" aria-label="Agent activity (mocked feed)">
      <div className="cp-thought-stream__header">
        <span className="cp-thought-stream__dot" aria-hidden />
        <span className="cp-thought-stream__title">Live console</span>
        <span className="cp-thought-stream__badge">Mock</span>
      </div>
      <ul className="cp-thought-stream__lines">
        {lines.map((line, i) => (
          <li key={`${line.t}-${i}`} className="cp-thought-stream__line">
            <span className="cp-thought-stream__tag">{line.t}</span>
            <span className="cp-thought-stream__msg">{line.m}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
