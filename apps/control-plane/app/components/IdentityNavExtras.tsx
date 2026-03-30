import Link from "next/link";
import {
  identityOverviewPath,
  publicationIndexWithIdentity,
  reviewIndexWithIdentity,
  runsIndexWithIdentity,
} from "@/lib/identity-nav";

/** Pass R — filtered index shortcuts (same wording across surfaces). */
export function IdentityContextLinks({ identityId }: { identityId: string }) {
  return (
    <span className="muted small">
      <Link href={runsIndexWithIdentity(identityId)}>runs</Link>
      {" · "}
      <Link href={reviewIndexWithIdentity(identityId)}>queue</Link>
      {" · "}
      <Link href={publicationIndexWithIdentity(identityId)}>list</Link>
    </span>
  );
}

/**
 * Pass R — breadcrumb line: overview + filtered indexes (use when identity is context, not the UUID row).
 */
export function IdentityNavExtras({ identityId }: { identityId: string }) {
  return (
    <span className="muted small">
      <Link href={identityOverviewPath(identityId)}>overview</Link>
      {" · "}
      <Link href={runsIndexWithIdentity(identityId)}>runs</Link>
      {" · "}
      <Link href={reviewIndexWithIdentity(identityId)}>queue</Link>
      {" · "}
      <Link href={publicationIndexWithIdentity(identityId)}>list</Link>
    </span>
  );
}
