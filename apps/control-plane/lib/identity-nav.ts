/**
 * Pass P — identity-scoped index links (exact UUID filter via query params).
 * Pass Q — lightweight identity overview route + UUID parsing for the same semantics.
 */

const UUID_RE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Normalize and validate a route/query identity id; invalid → null (do not call APIs). */
export function parseIdentityUuidParam(raw: string | undefined): string | null {
  if (raw == null) return null;
  const t = raw.trim();
  if (!t || !UUID_RE.test(t)) return null;
  return t.toLowerCase();
}

/** Pass Q — one-page overview composed from existing filtered APIs. */
export function identityOverviewPath(identityId: string): string {
  return `/identity/${encodeURIComponent(identityId)}`;
}

export function runsIndexWithIdentity(identityId: string): string {
  return `/runs?identity_id=${encodeURIComponent(identityId)}`;
}

export function reviewIndexWithIdentity(identityId: string): string {
  return `/review?identity_id=${encodeURIComponent(identityId)}`;
}

export function publicationIndexWithIdentity(identityId: string): string {
  return `/publication?identity_id=${encodeURIComponent(identityId)}`;
}
