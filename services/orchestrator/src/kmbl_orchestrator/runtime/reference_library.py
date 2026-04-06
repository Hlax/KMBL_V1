"""
Curated reference library (JSON) + selective slices for planner/generator.

- Curated cards are versioned in-package (``data/reference_library_v1.json``).
- Planner-observed cards are distilled from crawl_context / Playwright summaries — not full HTML.
- Selection caps keep payloads small (no full-library dumps).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import importlib.resources as ir

from kmbl_orchestrator.runtime.reference_patterns import _lane_bucket

REFERENCE_LIBRARY_VERSION: int = 1

# Selection caps (hard limits — tests enforce)
PLANNER_MAX_IMPLEMENTATION_CARDS: int = 4
PLANNER_MAX_INSPIRATION_CARDS: int = 3
PLANNER_MAX_OBSERVED_CARDS: int = 5
GENERATOR_MAX_IMPLEMENTATION_CARDS: int = 4
GENERATOR_MAX_INSPIRATION_CARDS: int = 2
GENERATOR_MAX_OBSERVED_CARDS: int = 3


@lru_cache(maxsize=1)
def _load_library_raw() -> dict[str, Any]:
    path = ir.files("kmbl_orchestrator.data") / "reference_library_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_curated_reference_cards() -> list[dict[str, Any]]:
    raw = _load_library_raw()
    cards = raw.get("cards")
    if not isinstance(cards, list):
        return []
    return [c for c in cards if isinstance(c, dict)]


def _card_lane(c: dict[str, Any]) -> str:
    return str(c.get("lane") or "").strip().lower()


def _stable_pick_inspiration(cards: list[dict[str, Any]], *, seed: str, k: int) -> list[dict[str, Any]]:
    pool = [c for c in cards if _card_lane(c) == "design_taste"]
    pool.sort(key=lambda x: str(x.get("id") or ""))
    if not pool or k <= 0:
        return []
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    start = h % len(pool)
    out: list[dict[str, Any]] = []
    for i in range(min(k, len(pool))):
        out.append(pool[(start + i) % len(pool)])
    return out


def _structured_identity_text(si: dict[str, Any] | None) -> str:
    if not si or not isinstance(si, dict):
        return ""
    try:
        return json.dumps(si, ensure_ascii=False).lower()
    except Exception:
        return ""


def _planner_preferred_lane(si: dict[str, Any] | None, crawl: dict[str, Any] | None) -> str:
    blob = _structured_identity_text(si)
    if any(x in blob for x in ("gaussian", "splat", "photogrammetry", "lidar", "point cloud")):
        return "gaussian_splat"
    if "pixi" in blob or ("2d" in blob and "canvas" in blob):
        return "pixi_2d"
    if any(x in blob for x in ("wgsl", "webgpu", "compute shader")):
        return "wgsl_webgpu"
    if any(x in blob for x in ("ogl", "twgl", "regl")) and "three" not in blob:
        return "shader_first_minimal"
    if crawl and str(crawl.get("crawl_phase") or "") == "inspiration_expansion":
        return "default_three_gsap"
    return "default_three_gsap"


def select_planner_reference_slice(
    *,
    structured_identity: dict[str, Any] | None,
    crawl_context: dict[str, Any] | None,
    graph_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Curated slice for planner (lane selection + taste) — capped counts.

    Does not include full crawl text; inspiration count bumps slightly in inspiration_expansion.
    """
    cards = load_curated_reference_cards()
    crawl = crawl_context if isinstance(crawl_context, dict) else None
    preferred = _planner_preferred_lane(
        structured_identity if isinstance(structured_identity, dict) else None,
        crawl,
    )

    impl: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take_from_lane(lane: str, n: int) -> None:
        nonlocal impl
        for c in cards:
            if n <= 0 or len(impl) >= PLANNER_MAX_IMPLEMENTATION_CARDS:
                return
            if _card_lane(c) != lane:
                continue
            cid = str(c.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            impl.append(c)
            n -= 1

    if preferred == "gaussian_splat":
        _take_from_lane("gaussian_splat", 2)
        _take_from_lane("default_three_gsap", PLANNER_MAX_IMPLEMENTATION_CARDS)
    elif preferred == "wgsl_webgpu":
        _take_from_lane("wgsl_webgpu", 2)
        _take_from_lane("default_three_gsap", PLANNER_MAX_IMPLEMENTATION_CARDS)
    elif preferred == "pixi_2d":
        _take_from_lane("pixi_2d", 2)
        _take_from_lane("default_three_gsap", PLANNER_MAX_IMPLEMENTATION_CARDS)
    elif preferred == "shader_first_minimal":
        _take_from_lane("shader_first_minimal", 2)
        _take_from_lane("default_three_gsap", PLANNER_MAX_IMPLEMENTATION_CARDS)
    else:
        _take_from_lane("default_three_gsap", PLANNER_MAX_IMPLEMENTATION_CARDS)

    impl = impl[:PLANNER_MAX_IMPLEMENTATION_CARDS]

    seed = graph_run_id or "default"
    insp_n = PLANNER_MAX_INSPIRATION_CARDS
    if crawl and str(crawl.get("crawl_phase") or "") == "inspiration_expansion":
        insp_n = min(PLANNER_MAX_INSPIRATION_CARDS, 3)
    inspiration = _stable_pick_inspiration(cards, seed=seed, k=insp_n)

    return {
        "kmbl_implementation_reference_cards": impl,
        "kmbl_inspiration_reference_cards": inspiration,
        "kmbl_reference_selection_meta": {
            "curated_library_version": REFERENCE_LIBRARY_VERSION,
            "role": "planner",
            "preferred_lane_hint": preferred,
            "implementation_card_count": len(impl),
            "inspiration_card_count": len(inspiration),
            "persistence": "inline_only",
            "note": (
                "Curated cards are bundled in orchestrator; observed crawl cards are separate "
                "and may be rebuilt each run from crawl_context."
            ),
        },
    }


def select_generator_reference_slice(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    *,
    graph_run_id: str | None = None,
) -> dict[str, Any]:
    """Implementation + inspiration slice from execution_contract + experience_mode."""
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    cards = load_curated_reference_cards()
    bucket = _lane_bucket(ec, build_spec if isinstance(build_spec, dict) else {})

    impl: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Primary lane matches
    for c in cards:
        if len(impl) >= GENERATOR_MAX_IMPLEMENTATION_CARDS:
            break
        if _card_lane(c) == "design_taste":
            continue
        if _card_lane(c) != bucket:
            continue
        cid = str(c.get("id") or "")
        if cid and cid not in seen:
            seen.add(cid)
            impl.append(c)

    # If gaussian bucket, never silently mix default Three docs beyond what matches bucket
    if bucket == "gaussian_splat":
        impl = [c for c in impl if _card_lane(c) == "gaussian_splat"][:GENERATOR_MAX_IMPLEMENTATION_CARDS]
    elif len(impl) < GENERATOR_MAX_IMPLEMENTATION_CARDS:
        for c in cards:
            if len(impl) >= GENERATOR_MAX_IMPLEMENTATION_CARDS:
                break
            if _card_lane(c) != "default_three_gsap":
                continue
            cid = str(c.get("id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                impl.append(c)

    impl = impl[:GENERATOR_MAX_IMPLEMENTATION_CARDS]
    seed = graph_run_id or str(build_spec.get("title") or "gen")
    inspiration = _stable_pick_inspiration(cards, seed=seed, k=GENERATOR_MAX_INSPIRATION_CARDS)

    observed = build_planner_observed_reference_cards(
        event_input.get("crawl_context") if isinstance(event_input, dict) else None,
        max_cards=GENERATOR_MAX_OBSERVED_CARDS,
    )

    return {
        "implementation_reference_cards": impl,
        "inspiration_reference_cards": inspiration,
        "planner_observed_reference_cards": observed,
        "reference_selection_meta": {
            "curated_library_version": REFERENCE_LIBRARY_VERSION,
            "role": "generator",
            "lane_bucket": bucket,
            "implementation_card_count": len(impl),
            "inspiration_card_count": len(inspiration),
            "planner_observed_card_count": len(observed),
            "persistence": "inline_only",
        },
    }


def build_planner_observed_reference_cards(
    crawl_context: dict[str, Any] | None,
    *,
    max_cards: int = PLANNER_MAX_OBSERVED_CARDS,
) -> list[dict[str, Any]]:
    """
    Compact cards from crawl summaries (Playwright or verified fetch) — no raw HTML.

    Safe to treat as ephemeral; durable crawl state stores only short fields.
    """
    if not isinstance(crawl_context, dict):
        return []
    items: list[dict[str, Any]] = []

    for key in ("recent_portfolio_summaries", "recent_inspiration_summaries"):
        block = crawl_context.get(key)
        if isinstance(block, list):
            items.extend([x for x in block if isinstance(x, dict)])

    # De-dupe URLs preserving order
    seen_url: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for it in items:
        u = str(it.get("url") or "").strip()
        if not u or u in seen_url:
            continue
        seen_url.add(u)
        uniq.append(it)

    out: list[dict[str, Any]] = []
    for it in uniq[:max_cards]:
        url = str(it.get("url") or "").strip()
        host = urlparse(url).hostname or url
        summary = str(it.get("summary") or "").strip().replace("\n", " ")[:220]
        origin = str(it.get("origin") or "portfolio")
        design = it.get("design_signals") if isinstance(it.get("design_signals"), list) else []
        tone = it.get("tone_keywords") if isinstance(it.get("tone_keywords"), list) else []
        sketch = it.get("reference_sketch") if isinstance(it.get("reference_sketch"), dict) else {}
        tags = [origin] + [str(x) for x in design[:4] if isinstance(x, str)] + [str(x) for x in tone[:3] if isinstance(x, str)]
        oid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        card = {
            "id": f"planner_observed_{oid}",
            "title": f"Observed: {host}",
            "lane": "planner_observed",
            "source_type": "planner_observed",
            "source_url": url,
            "tags": tags[:10],
            "why_it_matters": (
                "Ground-truth page visit distilled for this run — use for taste/layout/motion alignment; "
                "does not override identity seed truth."
            ),
            "use_when": "Mirroring interaction density, tone, or layout rhythm grounded in a visited URL.",
            "avoid_when": "Treating inspiration URLs as brand facts — see crawl evidence_contract.",
            "implementation_notes": summary or "No summary captured for this URL.",
            "design_notes": "",
            "reference_sketch": sketch if sketch else None,
        }
        if sketch:
            ln = sketch.get("layout_notes") if isinstance(sketch.get("layout_notes"), list) else []
            mn = sketch.get("motion_interaction_notes") if isinstance(sketch.get("motion_interaction_notes"), list) else []
            if ln or mn:
                card["design_notes"] = " ".join(
                    [str(x) for x in (ln + mn)[:6] if isinstance(x, str)]
                )[:300]
        out.append(card)
    return out


def build_reference_sketch_from_wrapper(data: dict[str, Any]) -> dict[str, Any]:
    """
    Distilled observation from Playwright wrapper JSON (no HTML stored).

    Used for crawl_state.page_summaries enrichment and planner-observed cards.
    """
    raw_sk = data.get("reference_sketch")
    if isinstance(raw_sk, dict) and raw_sk:
        def _sl(lkey: str, max_n: int) -> list[str]:
            v = raw_sk.get(lkey)
            if not isinstance(v, list):
                return []
            out: list[str] = []
            for x in v[:max_n]:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip()[:120])
            return out

        return {
            "page_focus": str(raw_sk.get("page_focus") or "")[:280],
            "taste_notes": _sl("taste_notes", 6),
            "layout_notes": _sl("layout_notes", 6),
            "motion_interaction_notes": _sl("motion_interaction_notes", 6),
        }
    title = str(data.get("page_title") or "").strip()
    meta = str(data.get("meta_description") or "").strip()
    summary = str(data.get("summary") or "").strip()
    traits = data.get("traits") if isinstance(data.get("traits"), dict) else {}
    design = traits.get("design_signals") if isinstance(traits.get("design_signals"), list) else []
    tone = traits.get("tone_keywords") if isinstance(traits.get("tone_keywords"), list) else []
    ds = [str(x).lower() for x in design if isinstance(x, str)]
    layout_markers = ("grid", "flex", "hero", "carousel")
    motion_markers = ("animation", "parallax", "video")
    layout_notes = [f"structure:{m}" for m in layout_markers if m in ds][:4]
    motion_notes = [f"motion:{m}" for m in motion_markers if m in ds][:4]
    taste_notes = [f"tone:{t}" for t in tone if isinstance(t, str)][:5]
    focus_bits = [b for b in (title[:80], meta[:120], summary[:160]) if b]
    return {
        "page_focus": " | ".join(focus_bits)[:280] if focus_bits else "",
        "taste_notes": taste_notes,
        "layout_notes": layout_notes,
        "motion_interaction_notes": motion_notes,
    }


def attach_reference_cards_to_lane_context(
    ilc: dict[str, Any],
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    *,
    graph_run_id: str | None = None,
) -> dict[str, Any]:
    """Merge generator reference slices into interactive lane context (evaluator parity)."""
    block = select_generator_reference_slice(
        build_spec,
        event_input,
        graph_run_id=graph_run_id,
    )
    out = dict(ilc)
    out["implementation_reference_cards"] = block["implementation_reference_cards"]
    out["inspiration_reference_cards"] = block["inspiration_reference_cards"]
    out["planner_observed_reference_cards"] = block["planner_observed_reference_cards"]
    out["reference_selection_meta"] = block["reference_selection_meta"]
    out["reference_library_version"] = REFERENCE_LIBRARY_VERSION
    return out


def build_planner_reference_payload(
    *,
    structured_identity: dict[str, Any] | None,
    crawl_context: dict[str, Any] | None,
    graph_run_id: str | None = None,
) -> dict[str, Any]:
    """Top-level keys merged into planner input_payload."""
    slice_ = select_planner_reference_slice(
        structured_identity=structured_identity,
        crawl_context=crawl_context,
        graph_run_id=graph_run_id,
    )
    observed = build_planner_observed_reference_cards(
        crawl_context if isinstance(crawl_context, dict) else None,
        max_cards=PLANNER_MAX_OBSERVED_CARDS,
    )
    return {
        "kmbl_implementation_reference_cards": slice_["kmbl_implementation_reference_cards"],
        "kmbl_inspiration_reference_cards": slice_["kmbl_inspiration_reference_cards"],
        "kmbl_planner_observed_reference_cards": observed,
        "kmbl_reference_selection_meta": {
            **slice_["kmbl_reference_selection_meta"],
            "planner_observed_card_count": len(observed),
        },
        "kmbl_reference_library_version": REFERENCE_LIBRARY_VERSION,
    }


def reference_payload_json_size_estimate(payload_keys: dict[str, Any]) -> int:
    """Best-effort char count for explosion guards (tests)."""
    try:
        return len(json.dumps(payload_keys, ensure_ascii=False, default=str))
    except Exception:
        return -1


def summarize_reference_cards_for_operator(
    implementation: list[Any] | None,
    inspiration: list[Any] | None,
    observed: list[Any] | None,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Tiny summary for read models / UI."""
    impl = implementation if isinstance(implementation, list) else []
    insp = inspiration if isinstance(inspiration, list) else []
    obs = observed if isinstance(observed, list) else []
    m = meta if isinstance(meta, dict) else {}
    return {
        "implementation_reference_count": len(impl),
        "inspiration_reference_count": len(insp),
        "planner_observed_reference_count": len(obs),
        "curated_library_version": m.get("curated_library_version"),
        "lane_bucket": m.get("lane_bucket"),
        "preferred_lane_hint": m.get("preferred_lane_hint"),
        "implementation_ids": [str(x.get("id")) for x in impl if isinstance(x, dict)][:12],
        "inspiration_ids": [str(x.get("id")) for x in insp if isinstance(x, dict)][:12],
        "observed_urls": [str(x.get("source_url")) for x in obs if isinstance(x, dict)][:8],
    }
