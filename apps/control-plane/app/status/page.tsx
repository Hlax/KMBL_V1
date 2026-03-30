import Link from "next/link";
import { OrchestratorHealth } from "./OrchestratorHealth";
import { RecentRunsStatus } from "./RecentRunsStatus";
import { RunDebugPanel } from "./RunDebugPanel";
import { VerificationSmokePanel } from "./VerificationSmokePanel";

export default function StatusPage() {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "";

  return (
    <>
      <h1 className="pub-page-title">Status</h1>
      <p className="muted">
        Operator health check, quick verification smokes, and recent runs. Advanced raw proxy
        debugging is folded below — use only when something fails.
      </p>
      <OrchestratorHealth configuredBaseUrl={configuredBaseUrl} />
      <VerificationSmokePanel />
      <RecentRunsStatus />
      <details className="cp-debug-details">
        <summary className="cp-debug-details__summary">
          Advanced: graph run debug (raw orchestrator proxy responses)
        </summary>
        <RunDebugPanel />
      </details>
      <p className="muted" style={{ marginTop: "1.25rem" }}>
        Primary surfaces: <Link href="/runs">Runs</Link>, <Link href="/review">Review</Link>,{" "}
        <Link href="/publication">Publication</Link>.
      </p>
      <p style={{ marginTop: "1.5rem" }}>
        <Link href="/">Home</Link>
      </p>
    </>
  );
}
