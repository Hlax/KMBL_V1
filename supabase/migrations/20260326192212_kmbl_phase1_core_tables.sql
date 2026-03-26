create extension if not exists "pgcrypto";

create table public.thread (
  thread_id uuid primary key default gen_random_uuid(),
  identity_id uuid,
  thread_kind text not null,
  status text not null,
  current_checkpoint_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.graph_run (
  graph_run_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  trigger_type text not null,
  status text not null,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.checkpoint (
  checkpoint_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  checkpoint_kind text not null,
  state_json jsonb not null default '{}'::jsonb,
  context_compaction_json jsonb,
  created_at timestamptz not null default now()
);

create table public.role_invocation (
  role_invocation_id uuid primary key default gen_random_uuid(),
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  role_type text not null,
  provider text not null,
  provider_config_key text not null,
  input_payload_json jsonb not null default '{}'::jsonb,
  output_payload_json jsonb,
  status text not null,
  iteration_index integer not null default 0,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  constraint role_invocation_role_type_check check (
    role_type in ('planner', 'generator', 'evaluator')
  )
);

create table public.build_spec (
  build_spec_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  planner_invocation_id uuid not null references public.role_invocation (role_invocation_id) on delete restrict,
  spec_json jsonb not null default '{}'::jsonb,
  constraints_json jsonb not null default '{}'::jsonb,
  success_criteria_json jsonb not null default '[]'::jsonb,
  evaluation_targets_json jsonb not null default '[]'::jsonb,
  raw_payload_json jsonb,
  status text not null,
  created_at timestamptz not null default now()
);

create table public.build_candidate (
  build_candidate_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  generator_invocation_id uuid not null references public.role_invocation (role_invocation_id) on delete restrict,
  build_spec_id uuid not null references public.build_spec (build_spec_id) on delete cascade,
  candidate_kind text not null,
  working_state_patch_json jsonb not null default '{}'::jsonb,
  artifact_refs_json jsonb not null default '[]'::jsonb,
  sandbox_ref text,
  preview_url text,
  raw_payload_json jsonb,
  status text not null,
  created_at timestamptz not null default now()
);

create table public.evaluation_report (
  evaluation_report_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  graph_run_id uuid not null references public.graph_run (graph_run_id) on delete cascade,
  evaluator_invocation_id uuid not null references public.role_invocation (role_invocation_id) on delete restrict,
  build_candidate_id uuid not null references public.build_candidate (build_candidate_id) on delete cascade,
  status text not null,
  summary text,
  issues_json jsonb not null default '[]'::jsonb,
  metrics_json jsonb not null default '{}'::jsonb,
  artifacts_json jsonb not null default '[]'::jsonb,
  raw_payload_json jsonb,
  created_at timestamptz not null default now(),
  constraint evaluation_report_status_check check (
    status in ('pass', 'partial', 'fail', 'blocked')
  )
);

create index graph_run_thread_id_idx on public.graph_run (thread_id);

create index checkpoint_graph_run_id_idx on public.checkpoint (graph_run_id);
create index checkpoint_thread_id_idx on public.checkpoint (thread_id);

create index role_invocation_graph_run_id_idx on public.role_invocation (graph_run_id);
create index role_invocation_thread_id_idx on public.role_invocation (thread_id);
create index role_invocation_graph_run_iteration_idx on public.role_invocation (
  graph_run_id,
  iteration_index,
  role_type
);

create index build_spec_graph_run_id_idx on public.build_spec (graph_run_id);
create index build_spec_thread_id_idx on public.build_spec (thread_id);

create index build_candidate_graph_run_id_idx on public.build_candidate (graph_run_id);
create index build_candidate_thread_id_idx on public.build_candidate (thread_id);

create index evaluation_report_graph_run_id_idx on public.evaluation_report (graph_run_id);
create index evaluation_report_thread_id_idx on public.evaluation_report (thread_id);
