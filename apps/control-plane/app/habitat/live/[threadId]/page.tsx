import Link from "next/link";
import { serverOriginFromHeaders } from "@/lib/server-origin";
import { LiveHabitatClient } from "./LiveHabitatClient";

export const dynamic = "force-dynamic";

type LiveJson = {
  kind?: string;
  read_model?: Record<string, unknown>;
  preview_surface?: Record<string, unknown>;
  error?: string;
};

export default async function LiveHabitatPage({
  params,
}: {
  params: { threadId: string };
}) {
  const { threadId } = params;
  const origin = serverOriginFromHeaders();
  const apiUrl = `${origin}/api/habitat/live/${encodeURIComponent(threadId)}`;
  let initial: LiveJson | null = null;
  let loadErr: string | null = null;

  try {
    const res = await fetch(apiUrl, { cache: "no-store" });
    const text = await res.text();
    try {
      initial = JSON.parse(text) as LiveJson;
    } catch {
      loadErr = "Invalid JSON from live habitat API";
    }
    if (!res.ok && !loadErr) {
      loadErr =
        typeof initial?.error === "string"
          ? initial.error
          : `HTTP ${res.status}`;
    }
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  const previewSrc = `/api/habitat/live/${encodeURIComponent(threadId)}/preview`;

  return (
    <>
      <p className="muted small cp-crumb-line">
        <Link href="/runs">← Review (graph runs)</Link>
        {" · "}
        <Link href="/review">Staging review</Link>
        <span className="muted small"> (snapshots — not this page)</span>
      </p>

      <h1 className="pub-page-title">Live Habitat</h1>
      <p className="pub-page-id mono">{threadId}</p>

      <p className="op-banner op-banner--staging" style={{ marginBottom: "1rem" }}>
        <strong>Mutable surface</strong> — current working staging for this thread. This is not a
        frozen review snapshot and not publication. It updates as generator iterations apply.
      </p>

      {loadErr ? (
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load live habitat</p>
          <p className="pub-empty__body mono small">{loadErr}</p>
          <p className="muted small">
            Ensure the orchestrator is reachable and this thread has working staging (e.g. after a
            run has staged at least once).
          </p>
        </div>
      ) : (
        <LiveHabitatClient threadId={threadId} initial={initial} previewSrc={previewSrc} />
      )}
    </>
  );
}
