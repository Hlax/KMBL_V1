-- Lightweight per-run execution timeline (orchestrator runtime hardening).

create table public.graph_run_event (
  graph_run_event_id uuid primary key default gen_random_uuid(),
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  event_type text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index graph_run_event_graph_run_id_created_idx on public.graph_run_event (
  graph_run_id,
  created_at desc
);
