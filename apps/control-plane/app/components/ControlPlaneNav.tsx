import Link from "next/link";
import { LiveStagingNavLink } from "./LiveStagingNavLink";

export function ControlPlaneNav() {
  return (
    <nav className="cp-nav" aria-label="Control plane">
      <Link href="/">Home</Link>
      <LiveStagingNavLink />
      <Link href="/autonomous" style={{ background: "#9b59b6", color: "#fff", borderRadius: 4, padding: "0.25rem 0.5rem" }}>Autonomous</Link>
      <Link href="/runs">Runs</Link>
      <Link href="/review">Review</Link>
      <Link href="/publication">Publication</Link>
      <Link href="/status">Status (debug)</Link>
    </nav>
  );
}
