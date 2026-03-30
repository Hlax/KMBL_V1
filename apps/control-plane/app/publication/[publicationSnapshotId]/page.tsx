import Link from "next/link";
import { notFound } from "next/navigation";
import { IdentityContextLinks, IdentityNavExtras } from "@/app/components/IdentityNavExtras";
import { identityOverviewPath } from "@/lib/identity-nav";
import { OperatorOutputSurface } from "@/app/components/OperatorOutputSurface";
import { buildPublicationAuditFacts } from "@/lib/review-publication-audit-read-model";
import { serverOriginFromHeaders } from "@/lib/server-origin";
import type { PublicationDetail } from "@/lib/api-types";

export const dynamic = "force-dynamic";

function formatWhen(iso: string | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function canonDisplayTitle(payload: Record<string, unknown> | undefined): string {
  if (!payload) return "Publication";
  const summary = payload.summary;
  if (summary && typeof summary === "object") {
    const t = (summary as { title?: unknown }).title;
    if (typeof t === "string" && t.trim()) return t.trim();
  }
  return "Publication";
}

function canonSummaryType(payload: Record<string, unknown> | undefined): string | null {
  if (!payload) return null;
  const summary = payload.summary;
  if (summary && typeof summary === "object") {
    const ty = (summary as { type?: unknown }).type;
    if (typeof ty === "string" && ty.trim()) return ty.trim();
  }
  return null;
}

export default async function PublicationDetailPage({
  params,
}: {
  params: { publicationSnapshotId: string };
}) {
  const { publicationSnapshotId } = params;
  const origin = serverOriginFromHeaders();
  const url = `${origin}/api/publication/${encodeURIComponent(publicationSnapshotId)}`;

  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    return (
      <>
        <h1 className="pub-page-title">Publication</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not reach the server</p>
          <p className="pub-empty__body">
            {e instanceof Error ? e.message : String(e)}
          </p>
          <p style={{ marginTop: "1rem" }}>
            <Link href="/publication">← Publication index</Link>
          </p>
        </div>
      </>
    );
  }

  const text = await res.text();
  let data: PublicationDetail | null = null;
  try {
    data = JSON.parse(text) as PublicationDetail;
  } catch {
    /* handled below */
  }

  if (res.status === 404) {
    notFound();
  }

  if (!res.ok || !data) {
    const err =
      typeof data?.error === "string"
        ? data.error
        : text.slice(0, 400);
    return (
      <>
        <h1 className="pub-page-title">Publication</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load this publication</p>
          <p className="pub-empty__body">
            HTTP {res.status}. {err}
          </p>
          <p style={{ marginTop: "1rem" }}>
            <Link href="/publication">← Publication index</Link>
          </p>
        </div>
      </>
    );
  }

  const payload =
    data.payload_json && typeof data.payload_json === "object"
      ? (data.payload_json as Record<string, unknown>)
      : undefined;
  const displayTitle = canonDisplayTitle(payload);
  const audit = buildPublicationAuditFacts(data);
  const pl = data.publication_lineage;
  const lineageThread = pl?.thread_id ?? data.thread_id;
  const lineageGraphRun = pl?.graph_run_id ?? data.graph_run_id;
  const lineageIdentity = pl?.identity_id ?? data.identity_id;

  return (
    <>
      <p className="muted small cp-crumb-line">
        <Link href="/publication">← Publication index</Link>
        {lineageIdentity ? (
          <>
            {" · "}
            <IdentityNavExtras identityId={lineageIdentity} />
          </>
        ) : null}
      </p>

      <h1 className="pub-page-title">{displayTitle}</h1>
      <p className="pub-page-id mono">{data.publication_snapshot_id}</p>
      {canonSummaryType(payload) ? (
        <p className="muted small" style={{ marginTop: "-0.5rem", marginBottom: "1rem" }}>
          Type <span className="mono">{canonSummaryType(payload)}</span>
        </p>
      ) : null}

      <p className="op-banner op-banner--canon" style={{ marginBottom: "1rem" }}>
        <strong>Immutable canon</strong> — this row is the read surface after publish. Preview,
        artifacts, and evaluation are summarized below; raw JSON stays under <em>Debug</em>. To change
        canon, publish from a <strong>new staging snapshot</strong> (staging id cannot publish
        twice).
      </p>

      <section className="pub-hero" aria-labelledby="pub-hero-heading">
        <div className="pub-hero__head">
          <h2 id="pub-hero-heading" className="op-section-title" style={{ margin: 0 }}>
            Canon at a glance
          </h2>
          <span className="pub-hero__timestamp" title="When this snapshot was published">
            Published {formatWhen(data.published_at)}
          </span>
        </div>
        <div className="pub-hero__grid">
          <div>
            <span className="pub-hero__label">Visibility</span>
            <div className="pub-hero__value">
              <span className="op-badge op-badge--canon">{data.visibility ?? "—"}</span>
            </div>
          </div>
          <div>
            <span className="pub-hero__label">Published by</span>
            <div className="pub-hero__value">{data.published_by ?? "—"}</div>
          </div>
          <div>
            <span className="pub-hero__label">Source staging</span>
            <div className="pub-hero__value mono small">
              {audit.sourceStagingSnapshotId ? (
                <Link
                  className="op-break-long"
                  href={`/review/staging/${encodeURIComponent(audit.sourceStagingSnapshotId)}`}
                >
                  {audit.sourceStagingSnapshotId}
                </Link>
              ) : (
                "—"
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="debug-panel">
        <h2 className="op-section-title">Lineage &amp; traceability</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Ids copied to the publication row — links open related operator surfaces.
        </p>
        <dl className="debug-kv pub-lineage-dl">
          <dt>identity</dt>
          <dd>
            {lineageIdentity ? (
              <>
                <Link href={identityOverviewPath(lineageIdentity)} title="Identity overview">
                  {lineageIdentity}
                </Link>
                <span className="muted small"> · </span>
                <IdentityContextLinks identityId={lineageIdentity} />
              </>
            ) : (
              <span className="muted">—</span>
            )}
          </dd>
          <dt>thread_id</dt>
          <dd className="mono">{lineageThread ?? "—"}</dd>
          <dt>graph_run_id</dt>
          <dd className="mono">
            {lineageGraphRun ? (
              <Link href={`/runs/${encodeURIComponent(lineageGraphRun)}`}>{lineageGraphRun}</Link>
            ) : (
              "—"
            )}
          </dd>
          <dt>parent publication</dt>
          <dd className="mono">
            {audit.parentPublicationSnapshotId ? (
              <Link
                href={`/publication/${encodeURIComponent(audit.parentPublicationSnapshotId)}`}
              >
                {audit.parentPublicationSnapshotId}
              </Link>
            ) : (
              <span className="muted">None (first in chain)</span>
            )}
          </dd>
        </dl>
      </div>

      <div className="debug-panel debug-panel--ok">
        <h2 className="op-section-title">Publication record (audit)</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Immutable write metadata — single persisted event when published.
        </p>
        <ol className="op-audit-history">
          <li>
            <span className="op-audit-history__title">Published to canon</span>
            <span className="op-audit-history__meta">
              {formatWhen(audit.publishedAt)}
              {audit.publishedBy ? (
                <>
                  {" "}
                  · <span className="mono">{audit.publishedBy}</span>
                </>
              ) : (
                <span className="muted"> · actor not recorded</span>
              )}
            </span>
          </li>
        </ol>
      </div>

      <details className="debug-panel">
        <summary>Raw payload_json (debug)</summary>
        {payload && typeof payload.version === "number" ? (
          <p className="muted small" style={{ marginTop: 0 }}>
            Version <span className="mono">{payload.version}</span>
            {canonSummaryType(payload) ? (
              <>
                {" "}
                · type <span className="mono">{canonSummaryType(payload)}</span>
              </>
            ) : null}
          </p>
        ) : null}
        <pre className="op-pre">{JSON.stringify(data.payload_json ?? {}, null, 2)}</pre>
      </details>
    </>
  );
}
