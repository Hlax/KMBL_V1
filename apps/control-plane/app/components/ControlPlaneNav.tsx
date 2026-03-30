import Link from "next/link";

export function ControlPlaneNav() {
  return (
    <nav className="cp-nav" aria-label="Control plane">
      <Link href="/">Home</Link>
      <Link href="/runs">Runs</Link>
      <Link href="/review">Review</Link>
      <Link href="/publication">Publication</Link>
      <Link href="/status">Status (debug)</Link>
    </nav>
  );
}
