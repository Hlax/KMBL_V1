import Link from "next/link";

import { IdentityContextLinks } from "@/app/components/IdentityNavExtras";
import { identityOverviewPath } from "@/lib/identity-nav";

import { serverOriginFromHeaders } from "@/lib/server-origin";

import type { PublicationDetail, PublicationListResponse } from "@/lib/api-types";

export const dynamic = "force-dynamic";

function pick(
  sp: Record<string, string | string[] | undefined>,
  k: string,
): string | undefined {
  const v = sp[k];
  if (Array.isArray(v)) return v[0];
  return v;
}

function formatWhen(iso: string | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 8 ? `${s.slice(0, 8)}…` : id;
}

export default async function PublicationIndexPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const identity_id = pick(searchParams, "identity_id") ?? "";
  const visibility = pick(searchParams, "visibility") ?? "";
  const limitRaw = pick(searchParams, "limit") ?? "20";

  const origin = serverOriginFromHeaders();
  const listParams = new URLSearchParams();
  if (identity_id.trim()) listParams.set("identity_id", identity_id.trim());
  if (visibility) listParams.set("visibility", visibility);
  if (limitRaw && limitRaw !== "20") listParams.set("limit", limitRaw);

  const listQs = listParams.toString();
  const listUrl = `${origin}/api/publication${listQs ? `?${listQs}` : ""}`;

  let listBody: PublicationListResponse | null = null;
  let listErr: string | null = null;
  let listUnimplemented = false;

  try {
    const listRes = await fetch(listUrl, { cache: "no-store" });
    const listText = await listRes.text();
    try {
      listBody = JSON.parse(listText) as PublicationListResponse;
      listUnimplemented = listBody.backend_unimplemented === true;
    } catch {
      if (!listRes.ok) listErr = listText.slice(0, 200);
    }
    if (!listRes.ok && !listErr) {
      listErr =
        typeof listBody?.error === "string"
          ? listBody.error
          : `HTTP ${listRes.status}`;
    }
  } catch (e) {
    listErr = e instanceof Error ? e.message : String(e);
  }

  const currentParams = new URLSearchParams();
  if (identity_id.trim()) currentParams.set("identity_id", identity_id.trim());
  const currentQs = currentParams.toString();
  const currentFetchUrl = `${origin}/api/publication/current${currentQs ? `?${currentQs}` : ""}`;

  let current: PublicationDetail | null = null;
  let currentStatus: number | null = null;
  let currentErr: string | null = null;
  let currentUnimplemented = false;

  try {
    const curRes = await fetch(currentFetchUrl, { cache: "no-store" });
    currentStatus = curRes.status;
    const curText = await curRes.text();
    if (curRes.status === 404) {
      current = null;
      currentErr = null;
    } else if (curRes.ok) {
      try {
        const parsed = JSON.parse(curText) as PublicationDetail;
        if (parsed.backend_unimplemented) {
          currentUnimplemented = true;
          current = null;
        } else {
          current = parsed;
        }
      } catch {
        currentErr = "Invalid JSON from /api/publication/current";
      }
    } else {
      try {
        const j = JSON.parse(curText) as { detail?: string; error?: string };
        currentErr = j.detail ?? j.error ?? curText.slice(0, 200);
      } catch {
        currentErr = curText.slice(0, 200);
      }
    }
  } catch (e) {
    currentErr = e instanceof Error ? e.message : String(e);
  }

  const pubs = listBody?.publications ?? [];
  const scopedByIdentity = identity_id.trim().length > 0;
  const hasFilters = scopedByIdentity || Boolean(visibility) || (limitRaw && limitRaw !== "20");
  const currentPubId = current?.publication_snapshot_id ?? null;

  return (
    <>
      <h1 className="pub-page-title">Publication</h1>

      {listUnimplemented || currentUnimplemented ? (
        <p className="op-banner op-banner--warn" role="status">
          <strong>Publication read API not fully available on this orchestrator build.</strong>{" "}
          {listBody?.message ??
            "List and/or current publication require GET /orchestrator/publication and GET /orchestrator/publication/current."}
        </p>
      ) : null}

      <p className="op-banner op-banner--canon">
        <strong>Canon / live read surface</strong> — immutable snapshots created when you publish an
        approved staging row. This index is not staging review and not LangGraph runtime state.
        {scopedByIdentity ? (
          <span className="muted">
            {" "}
            List and &quot;current&quot; below use the filtered <code>identity_id</code>.
          </span>
        ) : null}
      </p>

      <form method="get" action="/publication" className="debug-panel op-runs-filters">
        <h2 className="op-section-title">Filters</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Optional <code>identity_id</code> (UUID) scopes list and &quot;current&quot; to one
          identity. Invalid UUIDs return HTTP 400 from the orchestrator.
        </p>
        <div className="op-runs-filters__row">
          <label className="op-field">
            <span>identity_id</span>
            <input
              name="identity_id"
              type="text"
              defaultValue={identity_id}
              placeholder="UUID — optional"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="op-field">
            <span>visibility</span>
            <select name="visibility" defaultValue={visibility}>
              <option value="">Any</option>
              <option value="private">private</option>
              <option value="public">public</option>
            </select>
          </label>
          <label className="op-field">
            <span>limit</span>
            <input name="limit" type="number" min={1} max={200} defaultValue={limitRaw || "20"} />
          </label>
          <div className="op-field op-field--filter-submit">
            <span>&nbsp;</span>
            <button type="submit" className="op-btn op-btn--primary">
              Apply
            </button>
          </div>
        </div>
        <p className="muted small">
          <Link href="/publication">Clear filters</Link>
          {" · "}
          <Link href="/runs">Runs</Link> · <Link href="/review">Review</Link>
        </p>
      </form>

      {listErr ? (
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load publication list</p>
          <p className="pub-empty__body mono small">{listErr}</p>
        </div>
      ) : null}

      {currentStatus === 404 && !currentUnimplemented && (
        <div className="pub-empty" style={{ marginBottom: "1.5rem" }}>
          <p className="pub-empty__title">No &quot;current&quot; publication yet</p>
          <p className="pub-empty__body">
            {scopedByIdentity
              ? "There is no latest publication snapshot for this identity in the current scope."
              : "Nothing has been published yet, or your filters exclude the latest row."}
            {" "}
            Approve staging and publish once to create canon.
          </p>
        </div>
      )}

      {current && !currentErr && currentStatus !== 404 && (
        <div className="pub-index-current-wrap">
          <h2 className="op-section-title">Current publication</h2>
          <p className="pub-index-current-meta">
            Latest in this scope{scopedByIdentity ? " for the selected identity" : ""} — also
            appears in the list below with a <span className="pub-index-row__badge">Current</span>{" "}
            tag when present.
          </p>
          <dl className="debug-kv" style={{ marginBottom: "0.75rem" }}>
            <dt>publication</dt>
            <dd className="mono">
              <Link
                href={`/publication/${encodeURIComponent(current.publication_snapshot_id ?? "")}`}
              >
                {shortId(current.publication_snapshot_id ?? "")}
              </Link>
              <span className="muted small"> · full id in detail</span>
            </dd>
            <dt>visibility</dt>
            <dd>
              <span className="op-badge op-badge--canon">{current.visibility}</span>
            </dd>
            <dt>published_at</dt>
            <dd>{formatWhen(current.published_at)}</dd>
            <dt>published_by</dt>
            <dd>{current.published_by ?? "—"}</dd>
            <dt>source staging</dt>
            <dd className="mono small">{current.source_staging_snapshot_id ?? "—"}</dd>
            {current.identity_id ? (
              <>
                <dt>identity</dt>
                <dd className="mono small">
                  <Link href={identityOverviewPath(current.identity_id)} title="Identity overview">
                    {current.identity_id}
                  </Link>
                  <span className="muted small"> · </span>
                  <IdentityContextLinks identityId={current.identity_id} />
                </dd>
              </>
            ) : null}
          </dl>
          <p style={{ margin: 0 }}>
            <Link
              className="op-btn op-btn--primary"
              href={`/publication/${encodeURIComponent(current.publication_snapshot_id ?? "")}`}
            >
              Open full detail →
            </Link>
          </p>
        </div>
      )}

      {currentErr && currentStatus !== 404 ? (
        <div className="pub-empty" role="alert" style={{ marginBottom: "1.25rem" }}>
          <p className="pub-empty__title">Current publication could not be loaded</p>
          <p className="pub-empty__body mono small">{currentErr}</p>
        </div>
      ) : null}

      <div className="debug-panel">
        <h2 className="op-section-title">All publications</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Newest first. Rows marked <span className="pub-index-row__badge">Current</span> match the
          &quot;Current publication&quot; card above (same scope).
        </p>
        {listErr ? (
          <p className="muted">List unavailable.</p>
        ) : pubs.length === 0 ? (
          <div className="pub-empty">
            <p className="pub-empty__title">
              {hasFilters ? "No publications match these filters" : "No publications yet"}
            </p>
            <p className="pub-empty__body">
              {hasFilters
                ? "Try clearing filters or widening visibility / limit."
                : "When you publish from an approved staging snapshot, canon snapshots will appear here."}
            </p>
          </div>
        ) : (
          <ul className="op-list op-list--compact">
            {pubs.map((p) => {
              const isCurrent = Boolean(
                currentPubId && p.publication_snapshot_id === currentPubId,
              );
              return (
                <li
                  key={p.publication_snapshot_id}
                  className={`op-card op-card--compact pub-index-row${isCurrent ? " pub-index-row--current" : ""}`}
                >
                  <p className="op-card__title" style={{ marginBottom: "0.25rem" }}>
                    <Link href={`/publication/${encodeURIComponent(p.publication_snapshot_id)}`}>
                      {shortId(p.publication_snapshot_id)}
                    </Link>
                    {isCurrent ? (
                      <span className="pub-index-row__badge" title="Matches current publication">
                        Current
                      </span>
                    ) : null}
                  </p>
                  <p className="pub-index-row__meta-line mono small">{p.publication_snapshot_id}</p>
                  <dl className="debug-kv op-card__dl">
                    <dt>visibility</dt>
                    <dd>
                      <span className="op-badge op-badge--canon">{p.visibility}</span>
                    </dd>
                    <dt>published</dt>
                    <dd>{formatWhen(p.published_at)}</dd>
                    <dt>by</dt>
                    <dd>{p.published_by ?? "—"}</dd>
                    <dt>staging</dt>
                    <dd className="mono small">{p.source_staging_snapshot_id ?? "—"}</dd>
                    <dt>identity</dt>
                    <dd className="mono small">
                      {p.identity_id ? (
                        <>
                          <Link href={identityOverviewPath(p.identity_id)} title="Identity overview">
                            {shortId(p.identity_id)}
                          </Link>
                          <span className="muted small"> · </span>
                          <IdentityContextLinks identityId={p.identity_id} />
                        </>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </dl>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <p className="muted small cp-crumb-line" style={{ marginBottom: 0 }}>
        <Link href="/review">← Staging review</Link>
      </p>
    </>
  );
}
