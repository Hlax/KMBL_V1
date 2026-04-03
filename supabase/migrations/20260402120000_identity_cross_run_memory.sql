-- Cross-run memory: typed, provenance-aware rows per identity (merge by identity_id + category + memory_key).

create table public.identity_cross_run_memory (
  identity_cross_run_memory_id uuid primary key default gen_random_uuid(),
  identity_id uuid not null,
  category text not null,
  memory_key text not null,
  payload_json jsonb not null default '{}'::jsonb,
  strength double precision not null default 0,
  provenance text not null default '',
  source_graph_run_id uuid,
  operator_signal text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint identity_cross_run_memory_category_check check (
    category in ('identity_derived', 'run_outcome', 'operator_confirmed')
  )
);

create unique index identity_cross_run_memory_identity_cat_key_idx
  on public.identity_cross_run_memory (identity_id, category, memory_key);

create index identity_cross_run_memory_identity_id_idx
  on public.identity_cross_run_memory (identity_id, updated_at desc);

create index identity_cross_run_memory_source_graph_run_idx
  on public.identity_cross_run_memory (source_graph_run_id)
  where source_graph_run_id is not null;
