/**
 * Typed environment for JS/TS apps (control-plane, storage).
 * Mirrors .env.example — TODO: align with pydantic-settings in orchestrator when deploying.
 */

import { z } from "zod";

const EnvSchema = z.object({
  NEXT_PUBLIC_ORCHESTRATOR_URL: z.string().url().optional(),
  SUPABASE_URL: z.string().url().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().optional(),
});

export type KmblPublicEnv = z.infer<typeof EnvSchema>;

export function parseBrowserEnv(
  env: Record<string, string | undefined>
): KmblPublicEnv {
  return EnvSchema.parse({
    NEXT_PUBLIC_ORCHESTRATOR_URL: env.NEXT_PUBLIC_ORCHESTRATOR_URL,
    SUPABASE_URL: env.SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY: env.SUPABASE_SERVICE_ROLE_KEY,
  });
}
