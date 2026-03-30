-- KMBL generator model-routing / hourly budget observability (additive).
alter table public.role_invocation
  add column if not exists routing_metadata_json jsonb not null default '{}'::jsonb;

comment on column public.role_invocation.routing_metadata_json is
  'KMBL routing and budget decisions for this invocation (not KiloClaw model output).';
