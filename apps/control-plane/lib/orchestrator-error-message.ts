/**
 * Extract a human-readable error string from JSON bodies returned by FastAPI
 * (`detail` string or validation array) or Next proxies (`error` string).
 */
export function parseOrchestratorErrorMessage(
  body: unknown,
  httpStatus: number,
): string {
  if (body === null || body === undefined) {
    return `HTTP ${httpStatus}`;
  }
  if (typeof body === "string") {
    return body.trim() || `HTTP ${httpStatus}`;
  }
  if (typeof body !== "object") {
    return `HTTP ${httpStatus}`;
  }
  const o = body as Record<string, unknown>;
  if (typeof o.error === "string" && o.error.trim()) {
    return o.error.trim();
  }
  const d = o.detail;
  if (typeof d === "string" && d.trim()) {
    return d.trim();
  }
  if (Array.isArray(d)) {
    const parts = d
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          const m = (item as { msg?: unknown }).msg;
          return typeof m === "string" ? m : JSON.stringify(item);
        }
        return typeof item === "string" ? item : JSON.stringify(item);
      })
      .filter(Boolean);
    if (parts.length > 0) {
      return parts.join("; ");
    }
  }
  if (typeof d === "object" && d !== null) {
    try {
      return JSON.stringify(d);
    } catch {
      return `HTTP ${httpStatus}`;
    }
  }
  return `HTTP ${httpStatus}`;
}
