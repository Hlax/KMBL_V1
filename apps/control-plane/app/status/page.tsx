import Link from "next/link";
import { OrchestratorHealth } from "./OrchestratorHealth";
import { RunDebugPanel } from "./RunDebugPanel";

export default function StatusPage() {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "";

  return (
    <>
      <h1>Status</h1>
      <p className="muted">
        Developer-only: orchestrator health, then start a graph run and inspect
        persisted status (Supabase-backed when the orchestrator env is set). Not
        a product surface.
      </p>
      <OrchestratorHealth configuredBaseUrl={configuredBaseUrl} />
      <RunDebugPanel />
      <p className="muted" style={{ marginTop: "1.25rem" }}>
        Operator review / publication flow: <Link href="/review">Review</Link>,{" "}
        <Link href="/publication">Publication</Link>.
      </p>
      <p style={{ marginTop: "1.5rem" }}>
        <Link href="/">Home</Link>
      </p>
    </>
  );
}
