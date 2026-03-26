/**
 * Placeholder contracts aligned with docs/07_DATA_MODEL_AND_STACK_MAP.md.
 * Python orchestrator uses equivalent field names via Pydantic in services/orchestrator.
 */

import { z } from "zod";

/** UUID string — validated loosely for scaffold; tighten in production. */
export const UuidString = z.string().uuid();

export const RoleType = z.enum(["planner", "generator", "evaluator"]);

export const RoleInvocationStatus = z.enum([
  "queued",
  "running",
  "completed",
  "failed",
]);

/**
 * role_invocation — execution boundary between KMBL and KiloClaw (docs §1.7).
 */
export const RoleInvocation = z.object({
  role_invocation_id: UuidString,
  graph_run_id: UuidString,
  thread_id: UuidString,
  role_type: RoleType,
  provider: z.literal("kiloclaw"),
  provider_config_key: z.string(),
  input_payload_json: z.record(z.unknown()),
  output_payload_json: z.record(z.unknown()).nullable(),
  status: RoleInvocationStatus,
  iteration_index: z.number().int().nonnegative(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
});

/**
 * graph_run — one KMBL runtime pass over a thread (docs §1.6).
 */
export const GraphRun = z.object({
  graph_run_id: UuidString,
  thread_id: UuidString,
  trigger_type: z.enum(["prompt", "resume", "schedule", "system"]),
  status: z.enum(["running", "paused", "completed", "failed"]),
  started_at: z.string(),
  ended_at: z.string().nullable(),
});

/**
 * checkpoint — saved runtime state within a thread (docs §1.5).
 */
export const Checkpoint = z.object({
  checkpoint_id: UuidString,
  thread_id: UuidString,
  checkpoint_kind: z.enum(["pre_role", "post_role", "interrupt", "manual"]),
  state_json: z.record(z.unknown()),
  context_compaction_json: z.record(z.unknown()).nullable(),
  created_at: z.string(),
});

export const BuildSpecStatus = z.enum(["active", "superseded", "accepted"]);

/**
 * build_spec — planner output record (docs §1.8).
 */
export const BuildSpec = z.object({
  build_spec_id: UuidString,
  thread_id: UuidString,
  graph_run_id: UuidString,
  planner_invocation_id: UuidString,
  spec_json: z.record(z.unknown()),
  constraints_json: z.record(z.unknown()),
  success_criteria_json: z.array(z.unknown()),
  evaluation_targets_json: z.array(z.unknown()),
  status: BuildSpecStatus,
  created_at: z.string(),
});

export const BuildCandidateStatus = z.enum([
  "generated",
  "applied",
  "under_review",
  "superseded",
  "accepted",
]);

/**
 * build_candidate — generator-produced candidate (docs §1.9).
 */
export const BuildCandidate = z.object({
  build_candidate_id: UuidString,
  thread_id: UuidString,
  graph_run_id: UuidString,
  generator_invocation_id: UuidString,
  build_spec_id: UuidString,
  candidate_kind: z.enum(["habitat", "content", "full_app"]),
  working_state_patch_json: z.record(z.unknown()),
  artifact_refs_json: z.array(z.unknown()),
  sandbox_ref: z.string().nullable(),
  preview_url: z.string().nullable(),
  status: BuildCandidateStatus,
  created_at: z.string(),
});

export const EvaluationReportStatus = z.enum(["pass", "partial", "fail", "blocked"]);

/**
 * evaluation_report — evaluator output (docs §1.10).
 */
export const EvaluationReport = z.object({
  evaluation_report_id: UuidString,
  thread_id: UuidString,
  graph_run_id: UuidString,
  evaluator_invocation_id: UuidString,
  build_candidate_id: UuidString,
  status: EvaluationReportStatus,
  summary: z.string().nullable(),
  issues_json: z.array(z.unknown()),
  metrics_json: z.record(z.unknown()),
  artifacts_json: z.array(z.unknown()),
  created_at: z.string(),
});

/** KiloClaw wrapper envelope (docs/12_API_AND_SERVICE_LAYER.md §6). */
export const InvokeRoleRequest = z.object({
  role_type: RoleType,
  payload: z.record(z.unknown()),
});

export type RoleInvocationT = z.infer<typeof RoleInvocation>;
export type GraphRunT = z.infer<typeof GraphRun>;
export type CheckpointT = z.infer<typeof Checkpoint>;
export type BuildSpecT = z.infer<typeof BuildSpec>;
export type BuildCandidateT = z.infer<typeof BuildCandidate>;
export type EvaluationReportT = z.infer<typeof EvaluationReport>;
export type InvokeRoleRequestT = z.infer<typeof InvokeRoleRequest>;
