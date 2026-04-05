/**
 * One in-flight POST run-start per browser tab (shared across Autonomous, Run debug, etc.).
 * Prevents overlapping starts before React disables buttons or before the orchestrator responds.
 */

export const RUN_START_IN_FLIGHT_MESSAGE =
  "A run start is already in progress. Wait for it to finish before starting another.";

export type RunStartBlocked = {
  blocked: true;
  message: string;
};

let inFlight = false;

export function isRunStartRequestInFlight(): boolean {
  return inFlight;
}

export function isRunStartBlocked(
  r: Response | RunStartBlocked,
): r is RunStartBlocked {
  return (
    typeof r === "object" &&
    r !== null &&
    "blocked" in r &&
    (r as RunStartBlocked).blocked === true
  );
}

/**
 * POST JSON to a run-start API route. Returns immediately if another start is still in flight.
 */
export async function fetchRunStartExclusive(
  input: string,
  body: unknown,
  init?: RequestInit,
): Promise<Response | RunStartBlocked> {
  if (inFlight) {
    return { blocked: true, message: RUN_START_IN_FLIGHT_MESSAGE };
  }
  inFlight = true;
  try {
    const headers = new Headers(init?.headers);
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return await fetch(input, {
      ...init,
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } finally {
    inFlight = false;
  }
}
