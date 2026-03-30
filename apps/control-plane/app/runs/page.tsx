import Link from "next/link";
import type { GraphRunListItem, GraphRunListResponse } from "@/lib/api-types";
import { identityOverviewPath, runsIndexWithIdentity } from "@/lib/identity-nav";
import { scenarioBadgeLabel } from "@/lib/gallery-strip-visibility";
import { graphRunAttentionBadgeClass } from "@/lib/operator-attention";
import { serverOriginFromHeaders } from "@/lib/server-origin";

export const dynamic = "force-dynamic";

function pick(
  sp: Record<string, string | string[] | undefined>,
  k: string,
): string | undefined {
  const v = sp[k];
  if (Array.isArray(v)) return v[0];
  return v;
}

function formatWhen(iso: string | null | undefined) {
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

function outputsLine(r: GraphRunListItem): string {
  const roles = r.role_invocation_count ?? 0;
  const staging = r.latest_staging_snapshot_id;
  const parts: string[] = [];
  parts.push(`${roles} role run${roles === 1 ? "" : "s"}`);
  if (staging) parts.push("staging linked");
  else parts.push("no staging snapshot");
  return parts.join(" · ");
}

function RunCard({ r }: { r: GraphRunListItem }) {
  const href = `/runs/${encodeURIComponent(r.graph_run_id)}`;
  const scen = scenarioBadgeLabel(r.scenario_badge);
  return (
    <li className="op-card op-card--compact">
      <div className="runs-run-card__top">
        <h2 className="op-card__title">
          <Link href={href}>Run {shortId(r.graph_run_id)}</Link>
        </h2>
        <span className="runs-run-card__when">{formatWhen(r.started_at)}</span>
      </div>
      <div className="runs-run-card__badges">
        <span className="op-badge op-badge--neutral">{r.status}</span>
        <span className="op-badge op-badge--neutral" title="Trigger">
          {r.trigger_type}
        </span>
        {scen ? (
          <span className={scen.className} title={r.scenario_tag ?? "scenario"}>
            {scen.label}
          </span>
        ) : null}
        <span
          className={graphRunAttentionBadgeClass(r.attention_state)}
          title={r.attention_reason ?? ""}
        >
          {r.attention_state ?? "—"}
        </span>
      </div>
      <p className="runs-run-card__meta mono small">{r.graph_run_id}</p>
      <p className="muted small" style={{ margin: "0 0 0.45rem" }}>
        {outputsLine(r)}
      </p>
      <p className="review-proposal-card__identity" style={{ marginBottom: "0.35rem" }}>
        {r.identity_id ? (
          <>
            <Link href={identityOverviewPath(r.identity_id)} title="Identity overview">
              {r.identity_id}
            </Link>
            <span className="muted small"> · </span>
            <Link href={runsIndexWithIdentity(r.identity_id)} className="small">
              filter runs
            </Link>
          </>
        ) : (
          <span className="muted">No identity on thread</span>
        )}
      </p>
      <p className="op-card__foot" style={{ marginTop: 0 }}>
        <Link href={href}>Open run detail →</Link>
      </p>
    </li>
  );
}

function filterParts(args: {
  status: string;
  trigger_type: string;
  identity_id: string;
  limitRaw: string;
}): { active: boolean; parts: string[] } {
  const parts: string[] = [];
  if (args.status) parts.push(`status=${args.status}`);
  if (args.trigger_type) parts.push(`trigger=${args.trigger_type}`);
  if (args.identity_id.trim()) parts.push(`identity_id=${args.identity_id.trim()}`);
  if (args.limitRaw && args.limitRaw !== "50") parts.push(`limit=${args.limitRaw}`);
  return { active: parts.length > 0, parts };
}

export default async function RunsIndexPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const status = pick(searchParams, "status") ?? "";
  const trigger_type = pick(searchParams, "trigger_type") ?? "";
  const identity_id = pick(searchParams, "identity_id") ?? "";
  const limitRaw = pick(searchParams, "limit") ?? "50";

  const origin = serverOriginFromHeaders();
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (trigger_type) params.set("trigger_type", trigger_type);
  if (identity_id) params.set("identity_id", identity_id);
  if (limitRaw && limitRaw !== "50") params.set("limit", limitRaw);

  const url = `${origin}/api/runs${params.toString() ? `?${params}` : ""}`;

  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    return (
      <>
        <h1 className="pub-page-title">Runs</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not reach the server</p>
          <p className="pub-empty__body">
            {e instanceof Error ? e.message : String(e)}
          </p>
        </div>
      </>
    );
  }

  const text = await res.text();
  let data: GraphRunListResponse | null = null;
  try {
    data = JSON.parse(text) as GraphRunListResponse;
  } catch {
    /* handled below */
  }

  if (!res.ok) {
    const err =
      typeof data?.error === "string"
        ? data.error
        : text.slice(0, 400);
    return (
      <>
        <h1 className="pub-page-title">Runs</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load runs</p>
          <p className="pub-empty__body mono small">
            HTTP {res.status}. {err}
          </p>
        </div>
      </>
    );
  }

  if (!data) {
    return (
      <>
        <h1 className="pub-page-title">Runs</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Invalid response</p>
          <p className="pub-empty__body mono small">{text.slice(0, 400)}</p>
        </div>
      </>
    );
  }

  const rows = Array.isArray(data.runs) ? data.runs : [];
  const backendUnimplemented = data.backend_unimplemented === true;
  const { active: filtersActive, parts: filterSummaryParts } = filterParts({
    status,
    trigger_type,
    identity_id,
    limitRaw,
  });

  return (
    <>
      <h1 className="pub-page-title">Runs</h1>
      <p className="muted" style={{ marginTop: "-0.25rem", marginBottom: "1rem" }}>
        Persisted graph executions — what the orchestrator stored for each run (not a live
        stream).
      </p>

      {backendUnimplemented ? (
        <p className="op-banner op-banner--warn" role="status">
          <strong>Read API not available on this orchestrator build.</strong>{" "}
          {data.message ??
            "The control plane shows an empty list until GET /orchestrator/runs is available."}
        </p>
      ) : null}

      <p className="op-banner op-banner--neutral">
        <strong>Index</strong> — newest start time first. Status and outputs come from stored
        rows only; refresh to update. Use{" "}
        <Link href="/review">Review</Link> for staging and <Link href="/publication">Publication</Link>{" "}
        for canon.
      </p>

      <div className="op-banner op-banner--neutral review-filter-context">
        <strong>Active filters.</strong>{" "}
        {filtersActive ? (
          <span className="mono small">{filterSummaryParts.join(" · ")}</span>
        ) : (
          <span className="muted">None — default list (all runs in fetch window).</span>
        )}
      </div>

      <form method="get" action="/runs" className="debug-panel op-runs-filters">
        <h2 className="op-section-title">Narrow the list</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Same <code>identity_id</code> as staging and publication lineage. Invalid UUID → HTTP
          400.
        </p>
        <div className="op-runs-filters__row">
          <label className="op-field">
            <span>Status</span>
            <select name="status" defaultValue={status}>
              <option value="">Any</option>
              <option value="running">running</option>
              <option value="paused">paused</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
          </label>
          <label className="op-field">
            <span>Trigger</span>
            <select name="trigger_type" defaultValue={trigger_type}>
              <option value="">Any</option>
              <option value="prompt">prompt</option>
              <option value="resume">resume</option>
              <option value="schedule">schedule</option>
              <option value="system">system</option>
            </select>
          </label>
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
            <span>limit</span>
            <input name="limit" type="number" min={1} max={200} defaultValue={limitRaw || "50"} />
          </label>
          <div className="op-field op-field--filter-submit">
            <span>&nbsp;</span>
            <button type="submit" className="op-btn op-btn--primary">
              Apply
            </button>
          </div>
        </div>
        <p className="muted small">
          <Link href="/runs">Clear filters</Link>
          {" · "}
          <Link href="/review">Review</Link>
          {" · "}
          <Link href="/publication">Publication</Link>
        </p>
      </form>

      {rows.length === 0 && !backendUnimplemented ? (
        <div className="pub-empty">
          <p className="pub-empty__title">
            {filtersActive ? "No runs match these filters" : "No runs in the index"}
          </p>
          <p className="pub-empty__body">
            {filtersActive
              ? "Try clearing filters or changing status / trigger."
              : "Start a run from the orchestrator or home flow; completed runs appear here when persisted."}
          </p>
        </div>
      ) : null}

      {rows.length > 0 ? (
        <>
          <p className="muted small" style={{ marginBottom: "0.75rem" }}>
            Showing <strong>{data.count ?? rows.length}</strong> run
            {(data.count ?? rows.length) === 1 ? "" : "s"}
            {filtersActive ? " (filtered)" : ""}.
          </p>
          <ul className="op-list op-list--compact">
            {rows.map((r) => (
              <RunCard key={r.graph_run_id} r={r} />
            ))}
          </ul>
        </>
      ) : null}

      <details className="debug-panel" style={{ marginTop: "1.5rem" }}>
        <summary>Raw JSON (debug)</summary>
        <pre className="op-pre">{JSON.stringify(data, null, 2)}</pre>
      </details>
    </>
  );
}
