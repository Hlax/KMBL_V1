-- At most one non-terminal graph_run per thread at a time (starting / running / interrupt_requested).
-- Eliminates a race where two concurrent POST /orchestrator/runs/start both pass the read check
-- before either row is visible, yielding duplicate planners and OpenClaw sessions.

create unique index if not exists graph_run_one_active_per_thread
  on public.graph_run (thread_id)
  where (status = any (array['starting'::text, 'running'::text, 'interrupt_requested'::text]));

comment on index public.graph_run_one_active_per_thread is
  'Enforces cooperative single-flight per thread; aligns with ACTIVE_GRAPH_RUN_STATUSES in orchestrator.';
