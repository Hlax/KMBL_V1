-- Non-mutating RPC canary for orchestrator repository preflight.
-- Exercises the same PostgREST /rest/v1/rpc/<name> channel and service_role grants
-- as kmbl_atomic_* persistence RPCs, without INSERT/UPDATE/DELETE or durable side effects.

CREATE OR REPLACE FUNCTION public.kmbl_repository_write_path_canary()
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  SELECT jsonb_build_object(
    'ok', true,
    'channel', 'postgrest_rpc',
    'canary_version', 1
  );
$$;

COMMENT ON FUNCTION public.kmbl_repository_write_path_canary() IS
  'Preflight-only: proves RPC invocation path (same route family as kmbl_atomic_*). '
  'STABLE, no writes. Does not prove advisory-lock behavior or specific atomic RPC bodies.';

GRANT EXECUTE ON FUNCTION public.kmbl_repository_write_path_canary() TO service_role;
