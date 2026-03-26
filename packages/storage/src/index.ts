import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Supabase client factory for KMBL persistence.
 *
 * TODO: After migrations exist for docs/07_DATA_MODEL_AND_STACK_MAP.md §1,
 * add typed queries or generated types; orchestrator may use supabase-py instead in Python.
 */
export function createKmblSupabaseClient(
  url: string,
  serviceRoleKey: string
): SupabaseClient {
  return createClient(url, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

/** Placeholder — wire to real tables when schema lands. */
export async function healthCheckStorage(_client: SupabaseClient): Promise<{
  ok: boolean;
  detail?: string;
}> {
  // TODO: select 1 from a lightweight table or use Supabase health endpoint policy you choose.
  return { ok: true, detail: "not_implemented" };
}
