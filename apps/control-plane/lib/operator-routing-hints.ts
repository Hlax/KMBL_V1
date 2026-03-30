import type { RoleInvocationDetailItem } from "@/lib/api-types";

const DEFAULT_GEN_KEY = "kmbl-generator";

export type RoutingFactSource = "persisted" | "heuristic" | "mixed";

function fmtBool(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  return "—";
}

function persistedGeneratorLines(inv: RoleInvocationDetailItem): string[] {
  const h = inv.routing_hints;
  if (!h || inv.routing_fact_source !== "persisted") {
    return [];
  }
  const lines: string[] = [];
  const kind = h.generator_route_kind;
  if (typeof kind === "string" && kind) {
    lines.push(`generator_route_kind: ${kind}`);
  }
  if ("image_generation_intent_kind" in h) {
    lines.push(`image_generation_intent_kind: ${String(h.image_generation_intent_kind)}`);
  }
  lines.push(`openai_image_route_applied: ${fmtBool(h.openai_image_route_applied)}`);
  if (h.budget_denial_reason != null && String(h.budget_denial_reason).length > 0) {
    lines.push(`budget_denial_reason: ${String(h.budget_denial_reason)}`);
  }
  if (typeof h.route_reason === "string" && h.route_reason) {
    lines.push(`route_reason: ${h.route_reason}`);
  }
  return lines;
}

/**
 * Scenario-tag-based notes (not stored as routing_metadata) — labeled heuristic in UI.
 */
function heuristicScenarioLines(scenarioTag: string | null | undefined): string[] {
  const tag = scenarioTag ?? "";
  if (!tag.includes("gallery_strip") && !tag.includes("seeded_gallery")) {
    return [];
  }
  return [
    "Scenario tag mentions gallery / seeded gallery — use persisted routing hints and staging gallery counts to confirm image output.",
  ];
}

/**
 * Provider config key lines from persisted role rows (not routing_metadata JSON).
 */
function providerConfigLines(invocations: RoleInvocationDetailItem[]): string[] {
  const gens = invocations.filter((r) => r.role_type === "generator");
  const lines: string[] = [];
  for (const g of gens) {
    const key = (g.provider_config_key || "").trim();
    if (!key || key === DEFAULT_GEN_KEY) {
      lines.push(
        `Generator (iter ${g.iteration_index}): default OpenClaw config (${DEFAULT_GEN_KEY}).`,
      );
    } else {
      lines.push(
        `Generator (iter ${g.iteration_index}): OpenClaw config "${key}" (persisted provider_config_key).`,
      );
    }
  }
  if (gens.length === 0) {
    lines.push("No generator invocation recorded yet.");
  }
  return lines;
}

export type GeneratorRoutingView = {
  /** Lines from persisted routing_metadata_json (generator rows). */
  persistedRoutingLines: string[];
  /** OpenClaw config key per generator iteration — persisted columns. */
  providerConfigLines: string[];
  /** Scenario tag only — labeled heuristic in UI. */
  heuristicScenarioLines: string[];
  /** Overall labeling for the panel. */
  routingFactSource: RoutingFactSource;
};

/**
 * Operator-facing routing copy: persisted routing_metadata and provider keys where available;
 * scenario tag notes are explicitly heuristic.
 */
export function buildGeneratorRoutingView(
  scenarioTag: string | null | undefined,
  invocations: RoleInvocationDetailItem[],
): GeneratorRoutingView {
  const gens = invocations.filter((r) => r.role_type === "generator");
  const persistedRoutingLines: string[] = [];
  for (const g of gens) {
    const sub = persistedGeneratorLines(g);
    if (sub.length === 0) {
      continue;
    }
    persistedRoutingLines.push(`Generator iteration ${g.iteration_index}`);
    persistedRoutingLines.push(...sub.map((s) => `  ${s}`));
  }
  const hScenario = heuristicScenarioLines(scenarioTag);
  const pConf = providerConfigLines(invocations);

  let routingFactSource: RoutingFactSource = "persisted";
  if (
    (persistedRoutingLines.length > 0 && hScenario.length > 0) ||
    (persistedRoutingLines.length === 0 && hScenario.length > 0)
  ) {
    routingFactSource = "mixed";
  }

  return {
    persistedRoutingLines,
    providerConfigLines: pConf,
    heuristicScenarioLines: hScenario,
    routingFactSource,
  };
}
