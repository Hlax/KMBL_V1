-- Cooperative interrupt: operator request timestamp + audit for run lifecycle hardening.

alter table public.graph_run
  add column if not exists interrupt_requested_at timestamptz;

comment on column public.graph_run.interrupt_requested_at is
  'Set when operator requests cooperative interrupt; cleared when run reaches terminal state.';
