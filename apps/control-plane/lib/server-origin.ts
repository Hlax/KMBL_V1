import { headers } from "next/headers";

/**
 * Build same-origin base URL for server-side fetch to this app's /api routes.
 */
export function serverOriginFromHeaders(): string {
  const h = headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  return `${proto}://${host}`;
}
