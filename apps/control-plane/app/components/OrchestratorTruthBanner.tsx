"use client";

import { useEffect, useState } from "react";

import {
  deriveSystemMode,
  systemModeLabel,
  type SystemMode,
} from "@/lib/system-mode";

type HealthProbe = {
  reachable: boolean;
  httpStatus: number | null;
  error: string | null;
  body: Record<string, unknown> | null;
};

type SystemModePayload = {
  mode: SystemMode;
  title: string;
  detail: string;
};

function readKiloclawStub(body: unknown): boolean | null {
  if (!body || typeof body !== "object") return null;
  const o = body as Record<string, unknown>;
  const res = o.kiloclaw_resolution;
  if (!res || typeof res !== "object") return null;
  const r = res as Record<string, unknown>;
  if (r.configuration_valid === false) return null;
  if (r.kiloclaw_stub_mode === true) return true;
  return false;
}

export function OrchestratorTruthBanner() {
  const [probe, setProbe] = useState<HealthProbe | null>(null);
  const [modePayload, setModePayload] = useState<SystemModePayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [hRes, mRes] = await Promise.all([
          fetch("/api/orchestrator-health", { cache: "no-store" }),
          fetch("/api/system-mode", { cache: "no-store" }),
        ]);
        const hj = await hRes.json();
        const mj = await mRes.json();
        if (cancelled) return;
        setProbe({
          reachable: Boolean(hj?.reachable),
          httpStatus: typeof hj?.httpStatus === "number" ? hj.httpStatus : null,
          error: typeof hj?.error === "string" ? hj.error : null,
          body:
            hj?.body && typeof hj.body === "object"
              ? (hj.body as Record<string, unknown>)
              : null,
        });
        if (mj && typeof mj.mode === "string") {
          setModePayload(mj as SystemModePayload);
        }
      } catch {
        if (!cancelled) {
          setProbe({
            reachable: false,
            httpStatus: null,
            error: "probe_failed",
            body: null,
          });
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!probe) return null;

  const derivedMode =
    modePayload?.mode ??
    deriveSystemMode({
      orchestratorUrlSet: true,
      healthReachable: probe.reachable,
      healthBody: probe.body,
      directOrchestratorRunsListHealthy: probe.reachable,
      controlPlaneProxyRunsResponseOk: true,
      proxyUsedFallback: false,
    });

  const modeInfo = systemModeLabel(derivedMode);
  const stub = readKiloclawStub(probe.body);

  const bannerClass =
    derivedMode === "fully_connected" && stub !== true
      ? "cp-truth-banner cp-truth-banner--mode-ok"
      : derivedMode === "fallback"
        ? "cp-truth-banner cp-truth-banner--fallback"
        : derivedMode === "degraded"
          ? "cp-truth-banner cp-truth-banner--error"
          : stub === true
            ? "cp-truth-banner cp-truth-banner--warn"
            : "cp-truth-banner cp-truth-banner--mode-ok";

  return (
    <aside className={bannerClass} role="status" aria-live="polite">
      <div>
        <strong>{modePayload?.title ?? modeInfo.title}</strong> —{" "}
        {modePayload?.detail ?? modeInfo.detail}
      </div>
      {!probe.reachable && (
        <div className="cp-truth-banner__sub">
          Orchestrator probe: {probe.error ?? `HTTP ${probe.httpStatus ?? "—"}`}. Set{" "}
          <code>NEXT_PUBLIC_ORCHESTRATOR_URL</code>.
        </div>
      )}
      {probe.reachable && stub === true && (
        <div className="cp-truth-banner__sub">
          <strong>Stub KiloClaw transport.</strong> Planner/generator/evaluator are not real OpenClaw HTTP
          calls until you configure <code>KILOCLAW_API_KEY</code> and gateway URL (see orchestrator{" "}
          <code>/health</code>).
        </div>
      )}
    </aside>
  );
}
