"""Canvas + mixed-lane contracts for identity-shaped interactive habitats.

These contracts keep generation freedom while making composition and routing explicit.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SurfaceType = Literal["svg", "three", "canvas2d", "pixi", "hybrid"]
ZoneModel = Literal[
    "single_scene",
    "multi_zone",
    "multi_page",
    "hero_index",
    "scroll_chapters",
    "modal_gallery",
]
NavigationModel = Literal["continuous", "indexed", "chaptered", "branching", "free_roam"]


class CanvasContractV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    surface_type: SurfaceType = "hybrid"
    zone_model: ZoneModel = "multi_zone"
    navigation_model: NavigationModel = "indexed"
    media_modes: list[str] = Field(default_factory=list)
    interaction_model: list[str] = Field(default_factory=list)
    page_count_hint: int | None = None
    route_hints: list[str] = Field(default_factory=list)
    module_zones: list[str] = Field(default_factory=list)
    mixed_media_policy: str | None = None
    progressive_loading_policy: str | None = None

    def to_compact_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="python", exclude_none=True)
        return {k: v for k, v in d.items() if v not in ([], None, "")}


class MixedLaneContractV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_lane: str
    secondary_lanes: list[str] = Field(default_factory=list)
    lane_mix_policy: str = "bounded_blend"
    blend_rules: list[str] = Field(default_factory=list)
    lane_choice_rationale: str | None = None
    lane_proposal_scores: list[dict[str, Any]] = Field(default_factory=list)

    def to_compact_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="python", exclude_none=True)
        return {k: v for k, v in d.items() if v not in ([], None, "")}


_LANE_ORDER = (
    "spatial_gallery",
    "editorial_story",
    "story_chapters",
    "media_archive",
    "hero_index",
    "immersive_canvas",
    "index_atlas",
)


def _normalize_lane_name(s: str) -> str:
    return str(s or "").strip().lower().replace("-", "_")


def _infer_primary_lane(build_spec: dict[str, Any], structured_identity: dict[str, Any]) -> str:
    em = str(build_spec.get("experience_mode") or "").strip().lower()
    sa = str(build_spec.get("site_archetype") or "").strip().lower()
    cts = {str(x).strip().lower() for x in (structured_identity.get("content_types") or [])}

    if em in ("immersive_identity_experience", "immersive_spatial_portfolio"):
        return "immersive_canvas"
    if sa in ("gallery", "spatial_gallery") or "photography" in cts or "visual_art" in cts:
        return "spatial_gallery"
    if "writing" in cts:
        return "story_chapters"
    if "data" in cts or "research" in cts:
        return "index_atlas"
    if sa in ("archive", "atlas", "index"):
        return "index_atlas"
    return "hero_index"


def _lane_score_table(
    build_spec: dict[str, Any],
    structured_identity: dict[str, Any],
    identity_brief: dict[str, Any],
) -> list[tuple[str, int, str]]:
    em = str(build_spec.get("experience_mode") or "").strip().lower()
    sa = str(build_spec.get("site_archetype") or "").strip().lower()
    cts = {str(x).strip().lower() for x in (structured_identity.get("content_types") or [])}
    has_media = bool(identity_brief.get("image_refs") or identity_brief.get("video_refs"))

    scores: dict[str, int] = {k: 0 for k in _LANE_ORDER}
    rationale: dict[str, list[str]] = {k: [] for k in _LANE_ORDER}

    if em in ("immersive_identity_experience", "immersive_spatial_portfolio"):
        scores["immersive_canvas"] += 4
        rationale["immersive_canvas"].append("experience_mode_immersive")
    if sa in ("gallery", "spatial_gallery"):
        scores["spatial_gallery"] += 3
        rationale["spatial_gallery"].append("site_archetype_gallery")
    if "writing" in cts:
        scores["story_chapters"] += 3
        rationale["story_chapters"].append("content_types_writing")
    if "data" in cts or "research" in cts:
        scores["index_atlas"] += 3
        rationale["index_atlas"].append("content_types_data_research")
    if "photography" in cts or "visual_art" in cts:
        scores["spatial_gallery"] += 2
        rationale["spatial_gallery"].append("content_types_visual")
    if has_media:
        scores["media_archive"] += 2
        rationale["media_archive"].append("identity_media_present")
        scores["immersive_canvas"] += 1
        rationale["immersive_canvas"].append("identity_media_density")
    if sa in ("archive", "atlas", "index"):
        scores["index_atlas"] += 2
        rationale["index_atlas"].append("site_archetype_index")

    ordered = sorted(
        ((lane, val, ",".join(rationale[lane][:3]) or "baseline") for lane, val in scores.items()),
        key=lambda x: (x[1], -_LANE_ORDER.index(x[0])),
        reverse=True,
    )
    return ordered


def derive_mixed_lane_contract(
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
    build_spec: dict[str, Any] | None,
) -> MixedLaneContractV1:
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    si = structured_identity if isinstance(structured_identity, dict) else {}
    bs = build_spec if isinstance(build_spec, dict) else {}
    ec = bs.get("execution_contract") if isinstance(bs.get("execution_contract"), dict) else {}

    lane_mix_raw = ec.get("lane_mix") if isinstance(ec.get("lane_mix"), dict) else {}
    primary = _normalize_lane_name(str(lane_mix_raw.get("primary_lane") or ""))
    if not primary:
        primary = _infer_primary_lane(bs, si)

    secondary_raw = lane_mix_raw.get("secondary_lanes")
    secondary: list[str] = []
    if isinstance(secondary_raw, list):
        secondary = [_normalize_lane_name(str(x)) for x in secondary_raw if str(x).strip()]
    else:
        cts = {str(x).strip().lower() for x in (si.get("content_types") or [])}
        has_media = bool(ib.get("image_refs") or ib.get("video_refs"))
        if primary == "spatial_gallery":
            secondary = ["editorial_story"]
        elif primary == "story_chapters" and has_media:
            secondary = ["media_archive"]
        elif primary == "hero_index" and has_media:
            secondary = ["immersive_canvas"]
        elif primary == "index_atlas" and ("writing" in cts):
            secondary = ["editorial_story"]

    dedup_secondary: list[str] = []
    for lane in secondary:
        if lane and lane != primary and lane not in dedup_secondary:
            dedup_secondary.append(lane)

    policy = str(lane_mix_raw.get("lane_mix_policy") or "").strip().lower() or "bounded_blend"
    blend_rules = lane_mix_raw.get("blend_rules") if isinstance(lane_mix_raw.get("blend_rules"), list) else []
    if not blend_rules:
        blend_rules = [
            "Primary lane owns interaction grammar and navigation spine.",
            "Secondary lanes may shape modules/zones but must not create an everything-app.",
            "Source material must be transformed into habitat-native composition, not copied structure.",
        ]

    # Keep lane vocab compact and stable.
    allowed = set(_LANE_ORDER)
    dedup_secondary = [x for x in dedup_secondary if x in allowed][:3]
    if primary not in allowed:
        primary = "hero_index"

    ranked = _lane_score_table(bs, si, ib)
    proposal_scores = [
        {"lane": lane, "score": score, "rationale": why}
        for lane, score, why in ranked[:4]
    ]
    rationale = (
        f"primary={primary}; secondary={','.join(dedup_secondary) if dedup_secondary else 'none'}; "
        f"top_signal={proposal_scores[0]['rationale'] if proposal_scores else 'baseline'}"
    )

    return MixedLaneContractV1(
        primary_lane=primary,
        secondary_lanes=dedup_secondary,
        lane_mix_policy=policy,
        blend_rules=[str(x).strip() for x in blend_rules if str(x).strip()][:6],
        lane_choice_rationale=rationale,
        lane_proposal_scores=proposal_scores,
    )


def derive_canvas_contract(
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
    build_spec: dict[str, Any] | None,
    lane_mix: MixedLaneContractV1,
) -> CanvasContractV1:
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    si = structured_identity if isinstance(structured_identity, dict) else {}
    bs = build_spec if isinstance(build_spec, dict) else {}
    ec = bs.get("execution_contract") if isinstance(bs.get("execution_contract"), dict) else {}

    raw_surface = str(ec.get("surface_type") or "").strip().lower()
    if raw_surface in ("webgl_experience", "three"):
        surface_type: SurfaceType = "three"
    elif raw_surface in ("svg",):
        surface_type = "svg"
    elif raw_surface in ("pixi", "canvas2d"):
        surface_type = "pixi" if raw_surface == "pixi" else "canvas2d"
    else:
        surface_type = "hybrid"

    primary = lane_mix.primary_lane
    if primary == "immersive_canvas":
        zone_model: ZoneModel = "single_scene"
        navigation_model: NavigationModel = "free_roam"
    elif primary in ("story_chapters", "editorial_story"):
        zone_model = "scroll_chapters"
        navigation_model = "chaptered"
    elif primary in ("hero_index", "index_atlas"):
        zone_model = "hero_index"
        navigation_model = "indexed"
    elif primary == "spatial_gallery":
        zone_model = "multi_zone"
        navigation_model = "continuous"
    else:
        zone_model = "multi_zone"
        navigation_model = "indexed"

    media_modes: list[str] = []
    if isinstance(ib.get("image_refs"), list) and ib["image_refs"]:
        media_modes.append("image")
    if isinstance(ib.get("video_refs"), list) and ib["video_refs"]:
        media_modes.append("video")
    cts = {str(x).strip().lower() for x in (si.get("content_types") or [])}
    if "writing" in cts:
        media_modes.append("captioned")
    if primary in ("immersive_canvas", "spatial_gallery"):
        media_modes.append("ambient")
    if not media_modes:
        media_modes = ["image", "captioned"]

    im_raw = ec.get("interaction_model")
    interaction_model: list[str] = []
    if isinstance(im_raw, list):
        interaction_model = [str(x).strip().lower() for x in im_raw if str(x).strip()][:8]
    elif isinstance(bs.get("interaction_model"), str):
        interaction_model = [str(bs.get("interaction_model")).strip().lower()]
    if not interaction_model:
        interaction_model = ["pointer-reactive", "scroll", "click"]

    module_zones = ["hero_surface", "context_band", "media_zone"]
    if lane_mix.secondary_lanes:
        module_zones.extend([f"lane_{x}" for x in lane_mix.secondary_lanes])

    return CanvasContractV1(
        surface_type=surface_type,
        zone_model=zone_model,
        navigation_model=navigation_model,
        media_modes=list(dict.fromkeys(media_modes))[:5],
        interaction_model=list(dict.fromkeys(interaction_model))[:8],
        page_count_hint=2 if zone_model in ("hero_index", "multi_page") else 1,
        route_hints=["/", "/media"] if zone_model == "hero_index" else ["/"],
        module_zones=module_zones[:8],
        mixed_media_policy=(
            "transform_source_media"
            if "image" in media_modes or "video" in media_modes
            else "abstract_only"
        ),
        progressive_loading_policy="progressive_media_lazy_mount",
    )


__all__ = [
    "CanvasContractV1",
    "MixedLaneContractV1",
    "derive_canvas_contract",
    "derive_mixed_lane_contract",
]
