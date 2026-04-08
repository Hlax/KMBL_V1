"""
Deterministic metrics and light status adjustment for ``interactive_frontend_app_v1`` evaluations.
"""

from __future__ import annotations

import re
from typing import Any

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.interactive_scene_grammar import (
    GENERIC_THREEJS_DEMO_PATTERNS,
    PORTFOLIO_SHELL_SECTIONS,
)
from kmbl_orchestrator.runtime.literal_success_gate import collect_static_artifact_raw_concat
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    IMMERSIVE_IDENTITY_ARCHETYPE,
    PRIMARY_SURFACE_HERO_SCENE_FIRST,
    is_interactive_frontend_vertical,
)
from kmbl_orchestrator.staging.integrity import scan_interactive_bundle_preview_risks

#: Issue code for required-library compliance.  Must survive feedback sanitisation
#: (generator can and should fix missing library imports).
REQUIRED_LIBRARY_MISSING_CODE = "required_library_missing"

#: Issue codes for new identity/evolution checks.
PORTFOLIO_SHELL_REGRESSION_CODE = "portfolio_shell_regression"
GENERIC_DEMO_PATTERN_CODE = "generic_demo_pattern"
WEAK_IDENTITY_GROUNDING_CODE = "weak_identity_grounding"
WEAK_ITERATION_DELTA_CODE = "weak_iteration_delta"
LANE_MIX_MISMATCH_CODE = "lane_mix_mismatch"
LITERAL_REUSE_REGRESSION_CODE = "literal_reuse_regression"
WEAK_MEDIA_TRANSFORMATION_CODE = "weak_media_transformation"


# Event / DOM hooks — not exhaustive; enough to separate "static gimmick" from wired behavior.
_INTERACTION_SIGNAL_RE = re.compile(
    r"addEventListener\s*\(|\.on\s*\(\s*['\"]click|onclick\s*=|onchange\s*=|oninput\s*=|"
    r"onkeydown\s*=|onkeyup\s*=|pointerdown|touchstart|preventDefault\s*\(|"
    r"requestAnimationFrame\s*\(",
    re.IGNORECASE,
)

_AFFORDANCE_RE = re.compile(
    r"<button\b|<input\b[^>]*\btype\s*=\s*['\"]?(?:button|submit|range|checkbox)",
    re.IGNORECASE,
)

_CANVAS_OR_WEBGL_RE = re.compile(
    r"<canvas\b|getContext\s*\(\s*['\"]webgl|three\.|THREE\.",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Portfolio-shell regression detection
# ---------------------------------------------------------------------------

# HTML section id/class patterns that indicate stock portfolio structure
_PORTFOLIO_SECTION_RE = re.compile(
    r'\bid\s*=\s*["\'](?P<id>hero|projects|projects[_-]grid|about|contact|timeline|'
    r'recognitions|selected.work|work|services|testimonials)["\']|'
    r'\bclass\s*=\s*["\'][^"\']*(?P<cls>hero-section|projects-section|about-section|'
    r'contact-section|portfolio-section)[^"\']*["\']',
    re.IGNORECASE,
)

# Section heading text patterns indicating portfolio IA
_PORTFOLIO_HEADING_RE = re.compile(
    r"<h[1-6][^>]*>\s*(?:selected\s+projects?|projects?\s+grid|about\s+me|"
    r"contact\s+me|my\s+work|timeline\s*&?\s*recognitions?|get\s+in\s+touch)\s*</h[1-6]>",
    re.IGNORECASE,
)

# Generic Three.js demo patterns — case-sensitive for class names, insensitive for prose
_GENERIC_DEMO_RE = re.compile(
    r"TorusKnotGeometry|IcosahedronGeometry|OctahedronGeometry|"
    r"OrbitControls|AxesHelper|GridHelper|"
    r"spinning\s+cube|torus\s+knot|icosahedron",
    re.IGNORECASE,
)


def _count_portfolio_shell_sections(html_blob: str) -> int:
    """Count how many distinct portfolio-shell section markers appear in the HTML."""
    if not html_blob:
        return 0
    matches = set()
    for m in _PORTFOLIO_SECTION_RE.finditer(html_blob):
        gd = m.group("id") or m.group("cls") or ""
        if gd:
            matches.add(gd.lower())
    for m in _PORTFOLIO_HEADING_RE.finditer(html_blob):
        matches.add(m.group(0)[:30].lower())
    return len(matches)


def _detect_generic_demo_patterns(raw_text: str) -> list[str]:
    """Return list of generic Three.js demo pattern names found in artifacts."""
    found = []
    for m in _GENERIC_DEMO_RE.finditer(raw_text):
        token = m.group(0).strip()
        if token not in found:
            found.append(token)
    return found


def _is_portfolio_ia_explicitly_requested(build_spec: dict[str, Any]) -> bool:
    """True when the planner explicitly flagged portfolio IA (archetype or mode)."""
    sa = (build_spec.get("site_archetype") or "").strip().lower()
    em = (build_spec.get("experience_mode") or "").strip().lower()
    return sa == "portfolio" or em == "webgl_3d_portfolio"


def _has_scene_grammar_evidence(build_spec: dict[str, Any]) -> bool:
    """True when the build_spec carries identity-derived scene grammar signals."""
    cb = build_spec.get("creative_brief")
    if not isinstance(cb, dict):
        return False
    return bool(cb.get("scene_metaphor") or cb.get("motion_language") or cb.get("material_hint"))


def _detect_identity_grounding_in_artifacts(
    raw_text: str,
    build_spec: dict[str, Any],
    build_candidate: dict[str, Any] | None = None,
) -> bool:
    """
    Check whether the generator produced identity-grounded output.

    Primary signal: ``kmbl_scene_manifest_v1`` in the build candidate — structured,
    never rendered to users, and the authoritative grounding proof.

    Fallback: HTML markers (legacy; generators should stop emitting these since they
    leak into user-facing HTML).
    """
    # Primary: scene manifest in build_candidate (structured grounding, not HTML)
    bc = build_candidate or {}
    sm = bc.get("kmbl_scene_manifest_v1")
    if isinstance(sm, dict):
        if sm.get("scene_metaphor") or sm.get("identity_signals_used"):
            return True

    # Fallback: legacy HTML markers (still accepted for backwards compat)
    marker_re = re.compile(
        r"kmbl-scene-metaphor|kmbl-motion-language|kmbl-identity-grounded|"
        r"data-kmbl-scene|data-kmbl-motion",
        re.IGNORECASE,
    )
    return bool(marker_re.search(raw_text))


def _compute_iteration_delta_score(
    build_spec: dict[str, Any],
    build_candidate: dict[str, Any],
    iteration_hint: int,
) -> dict[str, Any]:
    """
    Compute iteration delta score from scene evolution data.

    Priority:
    1. Use ``kmbl_build_candidate_summary_v1.scene_evolution_delta`` (from scene manifest
       or artifact-observable fingerprint comparison — computed by summary builder when
       prior_summary was available; cannot silently skip when wired correctly).
    2. Fall back to ``_kmbl_prior_candidate_fingerprint`` if set externally.
    3. Fall back to simple library+h1 comparison from summary.

    Returns dict with: delta_score, change_categories, weak_delta, source.
    """
    if iteration_hint <= 0:
        return {"delta_score": None, "change_categories": [], "weak_delta": False, "source": "n/a"}

    current_summary = build_candidate.get("kmbl_build_candidate_summary_v1") or {}

    # Path 1: scene_evolution_delta computed by summary builder (preferred — durable wiring)
    scene_evo = current_summary.get("scene_evolution_delta")
    if isinstance(scene_evo, dict) and not scene_evo.get("skipped"):
        return {
            "delta_score": scene_evo.get("delta_score"),
            "change_categories": scene_evo.get("delta_categories") or [],
            "weak_delta": bool(scene_evo.get("weak_delta")),
            "prior_fingerprint": scene_evo.get("prior_fingerprint"),
            "current_fingerprint": scene_evo.get("current_fingerprint"),
            "source": "scene_evolution_delta",
        }

    # Path 2: _kmbl_prior_candidate_fingerprint set externally (legacy / explicit wiring)
    prior = build_candidate.get("_kmbl_prior_candidate_fingerprint")
    if isinstance(prior, dict):
        current_libs = set(current_summary.get("libraries_detected") or [])
        prior_libs = set(prior.get("libraries_detected") or [])
        prior_h1 = (prior.get("h1_text") or "").lower().strip()
        outline = current_summary.get("sections_or_modules") or {}
        # h1: prefer sections_or_modules.h1_text; fall back to top-level h1_text
        current_h1 = str(
            outline.get("h1_text") or current_summary.get("h1_text") or ""
        ).lower().strip()
        # section topology: compare section_ids lists
        prior_sections = set(str(s).lower() for s in (prior.get("section_ids") or []))
        current_sections = set(
            str(s).lower()
            for s in (
                current_summary.get("section_ids")
                or list(outline.keys())
                or []
            )
        )

        changes: list[str] = []
        if current_libs != prior_libs:
            changes.append("libraries")
        if prior_h1 and current_h1 and prior_h1 != current_h1:
            changes.append("h1_copy")
        if prior.get("geometry_mode") and prior["geometry_mode"] != current_summary.get(
            "experience_summary", {}
        ).get("experience_mode"):
            changes.append("geometry_mode")
        if prior_sections and current_sections and prior_sections != current_sections:
            changes.append("section_topology")

        # Score over 4 comparison categories (libs, h1, geometry_mode, section_topology)
        delta = min(1.0, len(changes) / 4.0)
        return {
            "delta_score": round(delta, 2),
            "change_categories": changes,
            "weak_delta": delta < 0.34,
            "source": "prior_candidate_fingerprint",
        }

    # Path 3: no prior data — cannot determine delta for this iteration
    return {
        "delta_score": None,
        "change_categories": [],
        "weak_delta": False,
        "source": "no_prior_data",
    }


def _lane_signal_count(raw_text: str, html_blob: str, lane_name: str) -> int:
    lane = lane_name.strip().lower()
    if not lane:
        return 0
    checks: list[str]
    if lane in ("spatial_gallery", "immersive_canvas"):
        checks = ["<canvas", "webgl", "three", "figure", "gallery", "data-kmbl-scene"]
    elif lane in ("editorial_story", "story_chapters"):
        checks = ["chapter", "narrative", "<article", "<section", "<h2", "story"]
    elif lane in ("media_archive", "index_atlas"):
        checks = ["archive", "atlas", "index", "<img", "<video", "caption"]
    elif lane == "hero_index":
        checks = ["hero", "index", "nav", "<main", "data-route"]
    else:
        checks = [lane.replace("_", "-")]

    blob = (raw_text + "\n" + html_blob).lower()
    return sum(1 for c in checks if c in blob)


def _extract_lane_mix(build_spec: dict[str, Any]) -> tuple[str | None, list[str]]:
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    lm = ec.get("lane_mix") if isinstance(ec.get("lane_mix"), dict) else {}
    primary = lm.get("primary_lane") if isinstance(lm.get("primary_lane"), str) else None
    secondary_raw = lm.get("secondary_lanes") if isinstance(lm.get("secondary_lanes"), list) else []
    secondary = [str(x).strip().lower() for x in secondary_raw if str(x).strip()]
    return (primary.strip().lower() if isinstance(primary, str) and primary.strip() else None, secondary[:3])


def _literal_reuse_count(raw_text: str, build_spec: dict[str, Any]) -> int:
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    srcp = ec.get("source_transformation_policy") if isinstance(ec.get("source_transformation_policy"), dict) else {}
    needles = srcp.get("literal_source_needles")
    if not isinstance(needles, list):
        return 0
    low = raw_text.lower()
    return sum(1 for n in needles[:20] if isinstance(n, str) and n.strip() and n.strip().lower() in low)


def _planned_required_interactions(build_spec: dict[str, Any]) -> int:
    ec = build_spec.get("execution_contract")
    if not isinstance(ec, dict):
        return 0
    ri = ec.get("required_interactions")
    if not isinstance(ri, list):
        return 0
    n = 0
    for x in ri:
        if isinstance(x, dict) and (x.get("id") or x.get("mechanism")):
            n += 1
        elif isinstance(x, str) and x.strip():
            n += 1
    return n


def _html_blob_for_affordances(build_candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for art in build_candidate.get("artifact_outputs") or []:
        if not isinstance(art, dict):
            continue
        path = str(art.get("file_path") or art.get("path") or "").lower()
        c = art.get("content")
        if not isinstance(c, str) or not c.strip():
            continue
        head = c[:2000].lower()
        if path.endswith((".html", ".htm")) or "<html" in head or "<!doctype" in head:
            parts.append(c)
    return "\n".join(parts)


def apply_interactive_lane_evaluator_gate(
    report: EvaluationReportRecord,
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    Merge deterministic ``interactive_lane_metrics``; optionally downgrade ``pass`` when evidence gaps
    or preview-risky module patterns conflict with a lenient LLM verdict.
    """
    if not is_interactive_frontend_vertical(build_spec, event_input):
        return report

    raw_text = collect_static_artifact_raw_concat(build_candidate)
    signal_matches = len(_INTERACTION_SIGNAL_RE.findall(raw_text))
    html_blob = _html_blob_for_affordances(build_candidate)
    affordance_matches = len(_AFFORDANCE_RE.findall(html_blob)) if html_blob else 0
    canvas_hits = len(_CANVAS_OR_WEBGL_RE.findall(raw_text))

    ao = build_candidate.get("artifact_outputs")
    mod_risks = scan_interactive_bundle_preview_risks(ao if isinstance(ao, list) else [])
    mod_risk_count = len(mod_risks)

    planned = _planned_required_interactions(build_spec)
    evidence_ok = signal_matches > 0 or canvas_hits > 0
    hollow_controls = affordance_matches > 0 and signal_matches == 0 and canvas_hits == 0

    m = dict(report.metrics_json or {})
    m["interactive_lane_metrics"] = {
        "planned_required_interactions": planned,
        "js_dom_signal_hits": signal_matches,
        "html_interactive_affordance_hits": affordance_matches,
        "canvas_or_webgl_hint_hits": canvas_hits,
        "relative_module_preview_risks": mod_risk_count,
        "interactive_evidence_ok": bool(evidence_ok),
        "hollow_control_affordances_without_js": bool(hollow_controls),
    }

    ec_b = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    em_s = (build_spec.get("experience_mode") or "").strip().lower()
    sa_s = (build_spec.get("site_archetype") or "").strip().lower()
    psm_s = str(ec_b.get("primary_surface_mode") or "").strip().lower()
    immersive_identity = (
        sa_s == IMMERSIVE_IDENTITY_ARCHETYPE
        or em_s == IMMERSIVE_IDENTITY_ARCHETYPE
        or psm_s == PRIMARY_SURFACE_HERO_SCENE_FIRST
    )
    if immersive_identity:
        head_blob = (html_blob[:12000] if html_blob else raw_text[:12000]).lower()
        hero_fold = ("<canvas" in head_blob) or ("webgl" in head_blob and "getcontext" in head_blob)
        scroll_ptr = bool(
            _INTERACTION_SIGNAL_RE.search(raw_text)
            and (
                re.search(r"scroll|wheel|pointer", raw_text, re.I) is not None
            )
        )
        reduced_ok = "prefers-reduced-motion" in raw_text.lower() or "matchmedia" in raw_text.lower()
        m["immersive_identity_metrics"] = {
            "hero_canvas_or_webgl_fold_hint": bool(hero_fold or canvas_hits > 0),
            "pointer_or_scroll_affects_scene_hint": bool(scroll_ptr and (canvas_hits > 0 or hero_fold)),
            "reduced_motion_fallback_hint": reduced_ok,
        }

    issues = list(report.issues_json or [])
    status = report.status
    summary = (report.summary or "").strip()
    scene_manifest = _scene_manifest_from_candidate(build_candidate)
    manifest_lane_mix = (
        scene_manifest.get("lane_mix") if isinstance(scene_manifest.get("lane_mix"), dict) else {}
    )
    manifest_canvas = (
        scene_manifest.get("canvas_model") if isinstance(scene_manifest.get("canvas_model"), dict) else {}
    )
    manifest_media = (
        scene_manifest.get("media_transformation_summary")
        if isinstance(scene_manifest.get("media_transformation_summary"), dict)
        else {}
    )
    manifest_source = (
        scene_manifest.get("source_transformation_summary")
        if isinstance(scene_manifest.get("source_transformation_summary"), dict)
        else {}
    )

    def _has_code(c: str) -> bool:
        for it in issues:
            if isinstance(it, dict) and it.get("code") == c:
                return True
        return False

    new_issues: list[dict[str, Any]] = []

    if planned > 0 and not evidence_ok and status in ("pass", "partial"):
        if not _has_code("interactive_lane_evidence_gap"):
            new_issues.append(
                {
                    "severity": "high",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_evidence_gap",
                    "message": (
                        f"build_spec.execution_contract lists {planned} required interaction(s) but "
                        "artifact text shows no addEventListener/onclick/canvas/WebGL hooks — "
                        "verify real interactivity or adjust the plan."
                    ),
                }
            )

    if hollow_controls and status in ("pass", "partial"):
        if not _has_code("interactive_lane_hollow_affordances"):
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_hollow_affordances",
                    "message": (
                        "HTML shows interactive affordances (buttons/inputs) but no JS event hooks "
                        "were found in artifacts — likely a static gimmick for this lane."
                    ),
                }
            )

    if mod_risk_count > 0 and status in ("pass", "partial"):
        if not _has_code("interactive_lane_module_preview_risk"):
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_module_preview_risk",
                    "message": (
                        "Relative ES module imports detected in JS artifacts — preview assembly "
                        "does not resolve cross-file module graphs; expect broken runtime unless refactored."
                    ),
                }
            )

    # ── Required-library compliance gate ─────────────────────────────────
    # Deterministic: compare build_spec required_libraries (or allowed_libraries
    # when no explicit required set) against libraries actually detected in
    # artifact source code.  Missing libraries → actionable issue for generator.
    req_libs, detected_libs, missing_libs = _required_library_compliance(
        build_spec, build_candidate,
    )
    if missing_libs and status in ("pass", "partial"):
        if not _has_code(REQUIRED_LIBRARY_MISSING_CODE):
            new_issues.append(
                {
                    "severity": "high",
                    "category": "interactive_lane_deterministic",
                    "code": REQUIRED_LIBRARY_MISSING_CODE,
                    "message": (
                        f"required_libraries {req_libs!r} specified in execution contract but "
                        f"artifacts only contain evidence of {detected_libs!r}. "
                        f"Missing: {missing_libs!r}. Add CDN <script> tags or ES module imports."
                    ),
                }
            )
    m["required_libraries_compliance"] = {
        "required": req_libs,
        "detected": detected_libs,
        "missing": missing_libs,
        "satisfied": len(missing_libs) == 0,
    }

    # ── Portfolio-shell regression gate ─────────────────────────────────────
    # Flag when an interactive/identity-led build regresses into portfolio IA
    # (hero/projects/about/contact) without the planner explicitly requesting it.
    portfolio_ia_requested = _is_portfolio_ia_explicitly_requested(build_spec)
    if not portfolio_ia_requested and status in ("pass", "partial"):
        shell_count = _count_portfolio_shell_sections(html_blob)
        m["portfolio_shell_section_count"] = shell_count
        # 3+ distinct portfolio sections without explicit portfolio intent = regression
        if shell_count >= 3:
            if not _has_code(PORTFOLIO_SHELL_REGRESSION_CODE):
                new_issues.append(
                    {
                        "severity": "high",
                        "category": "interactive_lane_identity",
                        "code": PORTFOLIO_SHELL_REGRESSION_CODE,
                        "message": (
                            f"Interactive build contains {shell_count} portfolio-shell sections "
                            "(hero/projects/about/contact/timeline) but site_archetype is not 'portfolio' "
                            "and experience_mode is not 'webgl_3d_portfolio'. "
                            "Remove stock portfolio structure; use scene_metaphor from creative_brief "
                            "as the organizing principle instead."
                        ),
                    }
                )
    else:
        m["portfolio_shell_section_count"] = None

    # ── Generic demo pattern gate ────────────────────────────────────────────
    # Flag when artifacts use stock Three.js tutorial geometry without identity justification.
    if status in ("pass", "partial"):
        generic_patterns = _detect_generic_demo_patterns(raw_text)
        m["generic_threejs_demo_patterns_detected"] = generic_patterns
        if generic_patterns:
            # Check if creative_brief has scene_grammar evidence to justify the primitives
            has_grammar = _has_scene_grammar_evidence(build_spec)
            # Check if identity grounding markers appear in the output
            identity_grounded = _detect_identity_grounding_in_artifacts(raw_text, build_spec, build_candidate)
            if not identity_grounded:
                if not _has_code(GENERIC_DEMO_PATTERN_CODE):
                    new_issues.append(
                        {
                            "severity": "medium",
                            "category": "interactive_lane_identity",
                            "code": GENERIC_DEMO_PATTERN_CODE,
                            "message": (
                                f"Artifacts contain generic Three.js demo patterns "
                                f"({', '.join(generic_patterns[:3])}) without evidence of "
                                "identity grounding (missing kmbl-scene-metaphor or "
                                "data-kmbl-scene marker). "
                                "Replace stock tutorial shapes with geometry justified by "
                                "the identity brief's scene_metaphor and creative direction."
                            ),
                        }
                    )
    else:
        m["generic_threejs_demo_patterns_detected"] = []

    # ── Iteration delta gate ─────────────────────────────────────────────────
    # For iteration > 0: require noticeable change across categories.
    iteration_hint = build_candidate.get("_kmbl_iteration_hint") or 0
    if isinstance(iteration_hint, int) and iteration_hint <= 0:
        # Also check report's iteration context (passed via metrics by evaluator node)
        iteration_hint = int(m.get("_iteration_hint") or 0)
    delta_result = _compute_iteration_delta_score(build_spec, build_candidate, iteration_hint)
    m["iteration_delta"] = delta_result

    if delta_result.get("weak_delta") and status in ("pass", "partial"):
        if not _has_code(WEAK_ITERATION_DELTA_CODE):
            changes = delta_result.get("change_categories") or []
            source = delta_result.get("source", "unknown")
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_evolution",
                    "code": WEAK_ITERATION_DELTA_CODE,
                    "message": (
                        f"Iteration {iteration_hint}: only {len(changes)} measurable change "
                        f"categor{'y' if len(changes) == 1 else 'ies'} detected "
                        f"({', '.join(changes) or 'none'}) [source: {source}]. "
                        "Require noticeable change in at least 2 of: "
                        "geometry_mode, scene_topology, library_stack, primitive_set, "
                        "composition_rules, interaction_rules, h1_copy. "
                        "'More polished version of same page' is not sufficient evolution. "
                        "Emit kmbl_scene_manifest_v1 in response for structured delta tracking."
                    ),
                }
            )

    # ── Lane-mix coherence + source transformation gates ───────────────────
    primary_lane, secondary_lanes = _extract_lane_mix(build_spec)
    lane_mix_scores: dict[str, int] = {}
    if primary_lane:
        lane_mix_scores[primary_lane] = _lane_signal_count(raw_text, html_blob, primary_lane)
    for lane in secondary_lanes:
        lane_mix_scores[lane] = _lane_signal_count(raw_text, html_blob, lane)

    man_primary = str(manifest_lane_mix.get("primary_lane") or "").strip().lower()
    man_secondary = {
        str(x).strip().lower()
        for x in (manifest_lane_mix.get("secondary_lanes") or [])
        if str(x).strip()
    }
    if primary_lane and man_primary == primary_lane:
        lane_mix_scores[primary_lane] = max(2, lane_mix_scores.get(primary_lane, 0))
    for lane in secondary_lanes:
        if lane in man_secondary:
            lane_mix_scores[lane] = max(2, lane_mix_scores.get(lane, 0))

    m["lane_mix_signals"] = lane_mix_scores
    if scene_manifest:
        m["manifest_first_signals"] = {
            "scene_manifest_present": True,
            "manifest_primary_lane": man_primary or None,
            "manifest_secondary_lanes": sorted(man_secondary)[:3],
            "manifest_zone_model": str(manifest_canvas.get("zone_model") or "") or None,
        }

    if primary_lane and status in ("pass", "partial"):
        pscore = lane_mix_scores.get(primary_lane, 0)
        secondary_score = max((lane_mix_scores.get(x, 0) for x in secondary_lanes), default=0)
        if pscore == 0 or (secondary_lanes and secondary_score == 0):
            if not _has_code(LANE_MIX_MISMATCH_CODE):
                new_issues.append(
                    {
                        "severity": "medium",
                        "category": "interactive_lane_coherence",
                        "code": LANE_MIX_MISMATCH_CODE,
                        "message": (
                            "Artifacts do not show enough evidence for planned lane mix "
                            f"(primary={primary_lane}, secondary={secondary_lanes or []}). "
                            "Strengthen zone-level realization of the lane blend without inflating app scope."
                        ),
                    }
                )

    literal_reuse_hits = _literal_reuse_count(raw_text, build_spec)
    if isinstance(manifest_source.get("literal_reuse_hits"), int):
        literal_reuse_hits = max(literal_reuse_hits, int(manifest_source.get("literal_reuse_hits") or 0))
    elif manifest_source.get("literal_reuse_detected") is True:
        literal_reuse_hits = max(literal_reuse_hits, 2)
    m["literal_source_reuse_hits"] = literal_reuse_hits
    if literal_reuse_hits >= 2 and status in ("pass", "partial"):
        if not _has_code(LITERAL_REUSE_REGRESSION_CODE):
            new_issues.append(
                {
                    "severity": "high",
                    "category": "interactive_lane_identity",
                    "code": LITERAL_REUSE_REGRESSION_CODE,
                    "message": (
                        "Detected repeated literal source text reuse from planner-provided needles. "
                        "Transform source material into habitat-native composition and avoid near-verbatim restatement."
                    ),
                }
            )

    ec_media = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    canvas_system = ec_media.get("canvas_system") if isinstance(ec_media.get("canvas_system"), dict) else {}
    media_modes = canvas_system.get("media_modes") if isinstance(canvas_system.get("media_modes"), list) else []
    wants_media = any(str(x).lower() in ("image", "video", "ambient", "captioned") for x in media_modes)
    media_hits = sum(1 for tok in ("<img", "<video", "figure", "track") if tok in raw_text.lower())
    if isinstance(manifest_media.get("transformed_media_assets"), int):
        media_hits = max(media_hits, int(manifest_media.get("transformed_media_assets") or 0))
    m["canvas_media_hits"] = media_hits
    if wants_media and media_hits == 0 and status in ("pass", "partial"):
        if not _has_code(WEAK_MEDIA_TRANSFORMATION_CODE):
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_media",
                    "code": WEAK_MEDIA_TRANSFORMATION_CODE,
                    "message": (
                        "Canvas contract requests media modes but artifacts contain no transformed media composition "
                        "signals (img/video/figure)."
                    ),
                }
            )

    if new_issues:
        issues = issues + new_issues
        if status == "pass":
            status = "partial"
            suffix = "[Adjusted: pass→partial — interactive lane deterministic checks.]"
            if suffix not in summary:
                summary = f"{summary} {suffix}".strip() if summary else suffix

    return report.model_copy(
        update={
            "status": status,
            "summary": summary,
            "issues_json": issues,
            "metrics_json": m,
        }
    )


# ---------------------------------------------------------------------------
# Required-library compliance helpers
# ---------------------------------------------------------------------------

def _required_library_compliance(
    build_spec: dict[str, Any],
    build_candidate: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(required, detected, missing)`` library name lists.

    ``required`` is drawn from ``execution_contract.required_libraries`` first;
    if that field is absent/empty, falls back to ``execution_contract.allowed_libraries``
    so that the primary interactive lane default (three + gsap) is enforced even when
    the planner did not produce the newer ``required_libraries`` field.

    ``detected`` comes from the build-candidate summary_v1 or, if unavailable,
    from the raw artifact text using the same regex detection as the summary builder.
    """
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    req_raw = ec.get("required_libraries")
    if not isinstance(req_raw, list) or not req_raw:
        req_raw = ec.get("allowed_libraries")
    if not isinstance(req_raw, list):
        return [], [], []
    required = sorted({str(x).strip().lower() for x in req_raw if isinstance(x, str) and x.strip()})
    if not required:
        return [], [], []

    # Prefer the orchestrator-built summary (already computed); fall back to raw artifact scan.
    summ = build_candidate.get("kmbl_build_candidate_summary_v1")
    if isinstance(summ, dict):
        detected_raw = summ.get("libraries_detected")
    else:
        detected_raw = None
    if isinstance(detected_raw, list):
        detected = sorted({str(x).strip().lower() for x in detected_raw if isinstance(x, str) and x.strip()})
    else:
        # Inline detection fallback
        from kmbl_orchestrator.runtime.build_candidate_summary_v1 import _detect_libraries_artifact, _concat_text

        arts = build_candidate.get("artifact_outputs") or []
        blob = _concat_text([a for a in arts if isinstance(a, dict)])
        detected = _detect_libraries_artifact(blob)

    missing = [lib for lib in required if lib not in detected]
    return required, detected, missing


def _scene_manifest_from_candidate(build_candidate: dict[str, Any]) -> dict[str, Any]:
    summ = build_candidate.get("kmbl_build_candidate_summary_v1")
    if not isinstance(summ, dict):
        return {}
    manifest = summ.get("kmbl_scene_manifest_v1")
    return manifest if isinstance(manifest, dict) else {}
