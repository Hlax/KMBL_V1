/**
 * Loose shapes for orchestrator JSON consumed by the control plane (Pass E/F).
 * Fields are optional where the UI defensively handles absence.
 */

export type ReviewReadiness = {
  ready?: boolean;
  approved?: boolean;
  rejected?: boolean;
  basis?: string;
  staging_status?: string;
};

export type ProposalRow = {
  proposal_id?: string;
  staging_snapshot_id: string;
  thread_id?: string;
  identity_id?: string | null;
  identity_hint?: string | null;
  preview_url?: string | null;
  title?: string;
  summary?: string;
  evaluation_summary?: string;
  created_at?: string;
  /** Derived: gallery_strip when payload includes ui_gallery_strip_v1 */
  content_kind?: string | null;
  has_gallery_strip?: boolean;
  gallery_strip_item_count?: number;
  gallery_image_artifact_count?: number;
  gallery_items_with_artifact_key?: number;
  has_static_frontend?: boolean;
  has_previewable_html?: boolean;
  review_readiness?: ReviewReadiness;
  staging_status?: string;
  /** Pass J — persisted derivation */
  linked_publication_count?: number;
  review_action_state?: string;
  review_action_reason?: string;
  /** Pass M — audit columns from staging row when present */
  approved_at?: string | null;
  approved_by?: string | null;
};

export type ProposalsResponse = {
  proposals?: ProposalRow[];
  count?: number;
  basis?: string;
  error?: string;
  /** Control-plane stub when orchestrator route returns 404 Not Found */
  backend_unimplemented?: boolean;
  message?: string;
};

/** Pass O — GET /orchestrator/operator-summary */
export type OperatorHomeSummary = {
  basis?: "persisted_rows_only";
  /** Control-plane stub when orchestrator route is missing */
  backend_unimplemented?: boolean;
  message?: string;
  runtime: {
    runs_in_window: number;
    runs_needing_attention: number;
    failed_count: number;
    paused_count: number;
  };
  review_queue: {
    ready_for_review: number;
    ready_to_publish: number;
    published: number;
    not_actionable: number;
  };
  canon: {
    has_current_publication: boolean;
    latest_publication_snapshot_id?: string | null;
    latest_published_at?: string | null;
  };
  error?: string;
  detail?: unknown;
};

export type LinkedPublicationItem = {
  publication_snapshot_id: string;
  published_at: string;
  published_by?: string | null;
  visibility: string;
};

export type LifecycleTimelineItem = {
  kind: string;
  label: string;
  at?: string | null;
  ref_publication_snapshot_id?: string | null;
};

export type StagingLineage = {
  thread_id: string;
  graph_run_id?: string | null;
  build_candidate_id: string;
  evaluation_report_id?: string | null;
  identity_id?: string | null;
  /** Previous staging on same thread (amend chain); artifact URLs may repeat (e.g. image gen). */
  prior_staging_snapshot_id?: string | null;
};

export type StagingEvaluationDetail = {
  present?: boolean;
  status?: string | null;
  summary?: string;
  issue_count?: number;
  artifact_count?: number;
  metrics_key_count?: number;
  metrics_preview?: Record<string, unknown>;
};

export type StagingDetail = {
  staging_snapshot_id: string;
  thread_id?: string;
  build_candidate_id?: string;
  graph_run_id?: string | null;
  identity_id?: string | null;
  identity_hint?: string | null;
  snapshot_payload_json?: Record<string, unknown>;
  content_kind?: string | null;
  has_gallery_strip?: boolean;
  gallery_strip_item_count?: number;
  gallery_image_artifact_count?: number;
  gallery_items_with_artifact_key?: number;
  /** Static HTML/CSS/JS (derived from static_frontend_file_v1) */
  has_static_frontend?: boolean;
  static_frontend_file_count?: number;
  static_frontend_bundle_count?: number;
  has_previewable_html?: boolean;
  /** Assembled static preview vs hosted URL primary surface (from snapshot payload metadata). */
  preview_kind?: "static" | "external_url" | null;
  preview_url?: string | null;
  status: string;
  created_at?: string;
  approved_by?: string | null;
  approved_at?: string | null;
  rejected_by?: string | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  evaluation_summary?: string;
  short_title?: string | null;
  review_readiness?: ReviewReadiness;
  review_readiness_explanation?: string;
  payload_version?: number | null;
  lineage?: StagingLineage;
  evaluation?: StagingEvaluationDetail;
  linked_publications?: LinkedPublicationItem[];
  lifecycle_timeline?: LifecycleTimelineItem[];
  error?: string;
  detail?: unknown;
};

export type PublicationListItem = {
  publication_snapshot_id: string;
  source_staging_snapshot_id?: string;
  identity_id?: string | null;
  visibility: string;
  published_at: string;
  published_by?: string | null;
};

export type PublicationListResponse = {
  /** Present on orchestrator GET /orchestrator/publication */
  basis?: "persisted_rows_only";
  publications?: PublicationListItem[];
  count?: number;
  error?: string;
  backend_unimplemented?: boolean;
  message?: string;
};

/** GET /orchestrator/staging (list rows without full payload) */
export type StagingListResponse = {
  basis?: "persisted_rows_only";
  snapshots?: Record<string, unknown>[];
  count?: number;
  error?: string;
  backend_unimplemented?: boolean;
  message?: string;
};

export type PublicationLineage = {
  source_staging_snapshot_id: string;
  parent_publication_snapshot_id?: string | null;
  identity_id?: string | null;
  thread_id?: string | null;
  graph_run_id?: string | null;
};

export type PublicationDetail = {
  publication_snapshot_id?: string;
  backend_unimplemented?: boolean;
  message?: string;
  source_staging_snapshot_id?: string;
  thread_id?: string | null;
  graph_run_id?: string | null;
  identity_id?: string | null;
  payload_json?: Record<string, unknown>;
  visibility?: string;
  published_by?: string | null;
  parent_publication_snapshot_id?: string | null;
  published_at?: string;
  publication_lineage?: PublicationLineage;
  error?: string;
  detail?: unknown;
};

/** Pass H — GET /orchestrator/runs/{id}/detail (persisted read model only). */
export type GraphRunSummaryBlock = {
  graph_run_id: string;
  thread_id: string;
  identity_id?: string | null;
  trigger_type: string;
  status: string;
  /** Set when operator requested cooperative interrupt (persisted). */
  interrupt_requested_at?: string | null;
  started_at: string;
  ended_at?: string | null;
  max_iteration_index?: number | null;
  latest_checkpoint_id?: string | null;
  run_state_hint: string;
  attention_state?: string;
  attention_reason?: string;
  resume_count?: number;
  last_resumed_at?: string | null;
};

export type RoleInvocationDetailItem = {
  role_invocation_id: string;
  role_type: string;
  status: string;
  iteration_index: number;
  started_at: string;
  ended_at?: string | null;
  provider: string;
  provider_config_key: string;
  /** Subset of persisted routing_metadata_json (generator rows). */
  routing_hints?: Record<string, unknown> | null;
  routing_fact_source?: "persisted" | "none";
};

export type AssociatedOutputsBlock = {
  build_spec_id?: string | null;
  build_candidate_id?: string | null;
  evaluation_report_id?: string | null;
  staging_snapshot_id?: string | null;
  publication_snapshot_id?: string | null;
};

export type RunTimelineItem = {
  kind: string;
  label: string;
  timestamp: string;
  related_id?: string | null;
  event_type: string;
  operator_triggered?: boolean;
};

export type OperatorActionItem = {
  kind: string;
  label: string;
  timestamp: string;
  details?: Record<string, unknown> | null;
};

/** Stable per-run links to live working staging (orchestrator + CP paths). */
export type SessionStagingLinks = {
  graph_run_id: string;
  thread_id: string;
  orchestrator_staging_preview_path: string;
  orchestrator_working_staging_json_path: string;
  control_plane_staging_preview_path: string;
  /** Control plane page: live mutable working habitat (not review snapshot). */
  control_plane_live_habitat_path?: string;
  note: string;
  orchestrator_staging_preview_url?: string | null;
  orchestrator_working_staging_json_url?: string | null;
};

export type GraphRunDetail = {
  backend_unimplemented?: boolean;
  message?: string;
  summary?: GraphRunSummaryBlock;
  operator_actions?: OperatorActionItem[];
  role_invocations: RoleInvocationDetailItem[];
  associated_outputs: AssociatedOutputsBlock;
  timeline: RunTimelineItem[];
  basis?: "persisted_rows_only";
  resume_eligible?: boolean;
  resume_operator_explanation?: string | null;
  retry_eligible?: boolean;
  retry_deferred_note?: string | null;
  scenario_tag?: string | null;
  scenario_badge?: string | null;
  session_staging?: SessionStagingLinks | null;
  error?: string;
  detail?: unknown;
};

/** Pass I — GET /orchestrator/runs */
export type GraphRunListItem = {
  graph_run_id: string;
  thread_id: string;
  identity_id?: string | null;
  trigger_type: string;
  status: string;
  started_at: string;
  ended_at?: string | null;
  max_iteration_index?: number | null;
  run_state_hint: string;
  role_invocation_count?: number;
  latest_staging_snapshot_id?: string | null;
  attention_state?: string;
  attention_reason?: string;
  scenario_tag?: string | null;
  /** gallery_strip | local_seed | other */
  scenario_badge?: string | null;
};

export type GraphRunListResponse = {
  runs?: GraphRunListItem[];
  count?: number;
  basis?: string;
  error?: string;
  detail?: unknown;
  backend_unimplemented?: boolean;
  message?: string;
};
