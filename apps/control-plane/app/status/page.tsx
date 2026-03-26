import Link from "next/link";
import { OrchestratorHealth } from "./OrchestratorHealth";

export default function StatusPage() {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "";

  return (
    <>
      <h1>Status</h1>
      <p className="muted">
        Graph run history is not wired yet; this page checks orchestrator reachability
        only.
      </p>
      <OrchestratorHealth configuredBaseUrl={configuredBaseUrl} />
      <p style={{ marginTop: "1.5rem" }}>
        <Link href="/">Home</Link>
      </p>
    </>
  );
}
