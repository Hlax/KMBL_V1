"""Autonomous loop service — one URL → identity → repeated LangGraph runs until done or proposal."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from kmbl_orchestrator.domain import CrawlStateRecord
    from kmbl_orchestrator.identity.crawl_evidence import FetchVerification
    from kmbl_orchestrator.persistence.repository import Repository

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import AutonomousLoopRecord
from kmbl_orchestrator.identity.extract import extract_identity_from_url
from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
from kmbl_orchestrator.seeds import build_identity_url_bundle_event_input
from kmbl_orchestrator.autonomous.directions import (
    build_initial_directions_for_identity,
    direction_to_retry_context,
    validate_direction,
)

_log = logging.getLogger(__name__)


class LoopTickResult:
    """Result of a single loop tick."""

    def __init__(
        self,
        *,
        loop_id: UUID,
        action: str,
        phase_after: str,
        iteration: int,
        graph_run_id: UUID | None = None,
        staging_snapshot_id: UUID | None = None,
        proposed: bool = False,
        completed: bool = False,
        error: str | None = None,
    ):
        self.loop_id = loop_id
        self.action = action
        self.phase_after = phase_after
        self.iteration = iteration
        self.graph_run_id = graph_run_id
        self.staging_snapshot_id = staging_snapshot_id
        self.proposed = proposed
        self.completed = completed
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": str(self.loop_id),
            "action": self.action,
            "phase_after": self.phase_after,
            "iteration": self.iteration,
            "graph_run_id": str(self.graph_run_id) if self.graph_run_id else None,
            "staging_snapshot_id": str(self.staging_snapshot_id) if self.staging_snapshot_id else None,
            "proposed": self.proposed,
            "completed": self.completed,
            "error": self.error,
        }


def start_autonomous_loop(
    repo: "Repository",
    identity_url: str,
    *,
    max_iterations: int = 50,
    auto_publish_threshold: float = 0.85,
) -> AutonomousLoopRecord:
    """Start a new autonomous loop for an identity URL."""
    identity_id = uuid4()
    loop = AutonomousLoopRecord(
        loop_id=uuid4(),
        identity_id=identity_id,
        identity_url=identity_url,
        status="pending",
        phase="identity_fetch",
        max_iterations=max_iterations,
        auto_publish_threshold=auto_publish_threshold,
    )
    repo.save_autonomous_loop(loop)
    _log.info("Started autonomous loop %s for %s", loop.loop_id, identity_url)
    return loop


async def tick_loop(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    *,
    run_graph_fn: Any = None,
) -> LoopTickResult:
    """
    Execute one tick of the autonomous loop.

    Phases (one graph invocation = ``graph_cycle`` per tick, not separate planner/generator/evaluator phases):
    - identity_fetch: extract identity from URL and persist under ``loop.identity_id``
    - graph_cycle: run full LangGraph (planner → generator → evaluator → decision → staging)
    - proposing: decide auto-publish vs continue
    - idle: optional exploration / completion
    """
    loop_id = loop.loop_id

    try:
        if loop.phase == "identity_fetch":
            return await _tick_identity_fetch(repo, loop)

        if loop.phase == "graph_cycle":
            return await _tick_graph_run(repo, loop, run_graph_fn=run_graph_fn)

        if loop.phase == "proposing":
            return await _tick_proposing(repo, loop)

        if loop.phase == "idle":
            return await _tick_idle(repo, loop)

        return LoopTickResult(
            loop_id=loop_id,
            action="unknown_phase",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error=f"Unknown phase: {loop.phase}",
        )

    except Exception as e:
        _log.exception("Loop %s tick failed: %s", loop_id, e)
        repo.update_loop_state(
            loop_id,
            status="failed",
            last_error=str(e)[:2000],
        )
        return LoopTickResult(
            loop_id=loop_id,
            action="error",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error=str(e),
        )


async def _tick_identity_fetch(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Fetch identity from URL and persist under the loop's pre-assigned ``identity_id``."""
    settings = get_settings()
    _log.info("Loop %s: fetching identity from %s", loop.loop_id, loop.identity_url)

    seed = await asyncio.to_thread(
        lambda: extract_identity_from_url(loop.identity_url, deep_crawl=True),
    )

    # ── Playwright enrichment ──────────────────────────────────────────
    # When the Playwright wrapper is configured, fetch the landing page (and
    # optionally a few internal pages) via a real browser so JS-rendered
    # portfolio content is captured.  Results are merged into the seed's
    # crawl state below; the seed itself is not replaced (httpx-based
    # extraction still provides the baseline).
    pw_enriched_pages: list[dict[str, Any]] = []
    pw_url = (settings.kmbl_playwright_wrapper_url or "").strip()
    if pw_url and settings.kmbl_playwright_max_pages_per_loop > 0:
        try:
            from kmbl_orchestrator.browser.playwright_client import (
                visit_page_via_wrapper,
                wrapper_payload_to_fetch_parts,
            )

            pw_urls = [loop.identity_url]
            # Also try internal pages the httpx crawl discovered.
            # Cap total Playwright visits to max_pages (landing counts as 1).
            max_extra = max(0, settings.kmbl_playwright_max_pages_per_loop - 1)
            for extra in (seed.crawled_pages or [])[1: max_extra + 1]:
                if extra not in pw_urls:
                    pw_urls.append(extra)

            for visit_url in pw_urls[: settings.kmbl_playwright_max_pages_per_loop]:
                try:
                    data = await asyncio.to_thread(
                        lambda u=visit_url: visit_page_via_wrapper(
                            {"url": u, "identity_id": str(loop.identity_id)},
                            settings=settings,
                        ),
                    )
                    ok, parts = wrapper_payload_to_fetch_parts(data)
                    if ok:
                        pw_enriched_pages.append({"url": visit_url, **parts})
                except Exception as pw_exc:
                    _log.debug(
                        "Loop %s: Playwright fetch for %s failed (non-fatal): %s",
                        loop.loop_id, visit_url, type(pw_exc).__name__,
                    )
        except Exception as pw_setup_exc:
            _log.info(
                "Loop %s: Playwright enrichment skipped: %s",
                loop.loop_id, type(pw_setup_exc).__name__,
            )

    if (
        settings.identity_minimum_confidence > 0
        and float(seed.confidence) < settings.identity_minimum_confidence
    ):
        msg = (
            f"identity confidence {seed.confidence:.3f} below "
            f"identity_minimum_confidence {settings.identity_minimum_confidence}"
        )
        repo.update_loop_state(
            loop.loop_id,
            status="failed",
            phase="identity_fetch",
            last_error=msg,
        )
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="identity_fetch_failed",
            phase_after="identity_fetch",
            iteration=0,
            error=msg,
        )

    persist_identity_from_seed(repo, seed, identity_id=loop.identity_id)

    # Initialize crawl state from the extraction results.
    # This records the initial page visit(s) and seeds the unvisited frontier
    # so that future runs can resume crawling from where we left off.
    from kmbl_orchestrator.identity.crawl_state import (
        _MAX_SUMMARY_LENGTH,
        get_or_create_crawl_state,
        record_page_visit,
    )
    get_or_create_crawl_state(repo, loop.identity_id, loop.identity_url)
    # Record each page the extraction already crawled
    for page_url in seed.crawled_pages or [seed.source_url]:
        record_page_visit(
            repo,
            loop.identity_id,
            page_url,
            summary=seed.to_profile_summary()[:_MAX_SUMMARY_LENGTH] if page_url == seed.source_url else "",
            tone_keywords=list(seed.tone_keywords or []),
            design_signals=list(seed.aesthetic_keywords or []),
        )

    # Record Playwright-enriched pages (JS-rendered content) into crawl state.
    # These carry richer summaries, design signals, and tone keywords from the
    # actual rendered DOM — complementing the httpx-only baseline.
    from kmbl_orchestrator.identity.crawl_evidence import EvidenceTier

    for pw_page in pw_enriched_pages:
        record_page_visit(
            repo,
            loop.identity_id,
            pw_page["url"],
            summary=(pw_page.get("summary") or "")[:_MAX_SUMMARY_LENGTH],
            tone_keywords=list(pw_page.get("tone_keywords") or []),
            design_signals=list(pw_page.get("design_signals") or []),
            discovered_links=list(pw_page.get("discovered_links") or []),
            provenance_source="playwright_identity_fetch",
            provenance_tier=EvidenceTier.VERIFIED_FETCH,
            run_id=str(loop.loop_id),
        )

    # Build initial typed exploration directions from the identity brief.
    # This replaces the previous untyped list[dict] with no schema.
    from kmbl_orchestrator.identity.brief import build_identity_brief_from_repo
    brief = build_identity_brief_from_repo(repo, loop.identity_id)
    initial_directions = build_initial_directions_for_identity(
        identity_brief=brief.to_generator_payload() if brief else None,
    )

    repo.update_loop_state(
        loop.loop_id,
        phase="graph_cycle",
        status="running",
        reset_loop_error=True,
        exploration_directions=initial_directions,
    )

    return LoopTickResult(
        loop_id=loop.loop_id,
        action="identity_fetched",
        phase_after="graph_cycle",
        iteration=0,
    )


async def _tick_graph_run(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    *,
    run_graph_fn: Any = None,
) -> LoopTickResult:
    """Run one full graph (single LangGraph invocation)."""
    settings = get_settings()
    if run_graph_fn is None:
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="no_graph_runner",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error="No graph runner provided",
        )

    iteration = loop.iteration_count + 1

    if iteration > loop.max_iterations:
        repo.update_loop_state(loop.loop_id, status="completed", phase="idle")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="max_iterations_reached",
            phase_after="idle",
            iteration=iteration,
            completed=True,
        )

    _log.info("Loop %s: starting graph iteration %d", loop.loop_id, iteration)

    event_input = build_identity_url_bundle_event_input(
        identity_url=loop.identity_url,
    )

    # Determine retry_context from current pending direction (if any).
    # The direction queue is processed in order; the orchestrator picks the
    # first pending direction and translates it into a retry_context for the graph.
    directions = loop.exploration_directions or []
    completed_ids = {d.get("id") for d in (loop.completed_directions or []) if d.get("id")}
    pending = [d for d in directions if validate_direction(d) and d.get("id") not in completed_ids]
    current_direction = pending[0] if pending else None

    retry_context: dict[str, Any] | None = None
    if current_direction and iteration > 1:
        # iteration 1 = fresh start (no retry_context); subsequent iterations use directions
        retry_context = direction_to_retry_context(
            current_direction,
            iteration_index=iteration,
            prior_alignment_score=loop.last_alignment_score,
        )
        _log.info(
            "Loop %s: applying direction_id=%s type=%s for iteration %d",
            loop.loop_id,
            current_direction.get("id"),
            current_direction.get("type"),
            iteration,
        )

    try:
        result = await run_graph_fn(
            identity_url=loop.identity_url,
            identity_id=loop.identity_id,
            event_input=event_input,
            thread_id=loop.current_thread_id,
            retry_context=retry_context,
        )

        graph_run_id = result.get("graph_run_id")
        thread_id = result.get("thread_id")
        staging_snapshot_id = result.get("staging_snapshot_id")
        evaluator_status = result.get("evaluator_status")
        # alignment_score is now returned from run_graph_fn (graph final state)
        alignment_score: float | None = result.get("last_alignment_score")
        # last_evaluator_score is alignment_score when present, else None
        evaluator_score = alignment_score  # this is the real score now

        # --- Close the crawl feedback loop ---
        # After each graph run, advance the crawl frontier so the next run
        # sees updated visited/unvisited state.  This is the orchestrator's
        # responsibility — we do NOT rely on the LLM to manage crawl state.
        _advance_crawl_frontier(repo, loop, result)

        staging_count = loop.total_staging_count
        if staging_snapshot_id:
            staging_count += 1

        # Mark the current direction as completed if alignment improved
        # or if we've run at least one graph_cycle for this direction.
        updated_completed = list(loop.completed_directions or [])
        if current_direction:
            prior_score = loop.last_alignment_score or 0.0
            current_score = alignment_score or 0.0
            # Mark direction complete when: alignment improved, or evaluator pass
            if evaluator_status == "pass" or (
                alignment_score is not None and current_score >= prior_score + 0.05
            ):
                updated_completed.append(current_direction)
                _log.info(
                    "Loop %s: direction %s marked complete (alignment %.3f → %.3f)",
                    loop.loop_id,
                    current_direction.get("id"),
                    prior_score,
                    current_score,
                )

        repo.update_loop_state(
            loop.loop_id,
            iteration_count=iteration,
            current_thread_id=UUID(thread_id) if thread_id else None,
            current_graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            last_staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
            last_evaluator_status=evaluator_status,
            last_evaluator_score=evaluator_score,
            last_alignment_score=alignment_score,
            total_staging_count=staging_count,
            completed_directions=updated_completed if updated_completed != list(loop.completed_directions or []) else None,
            phase="proposing" if evaluator_status == "pass" else "graph_cycle",
            reset_loop_error=True,
        )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_completed",
            phase_after="proposing" if evaluator_status == "pass" else "graph_cycle",
            iteration=iteration,
            graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
        )

    except Exception as e:
        _log.exception("Loop %s graph run failed: %s", loop.loop_id, e)
        new_fail = (loop.consecutive_graph_failures or 0) + 1
        err_msg = str(e)[:2000]
        max_c = settings.autonomous_loop_max_consecutive_failures

        if new_fail >= max_c:
            repo.update_loop_state(
                loop.loop_id,
                phase="graph_cycle",
                status="failed",
                last_error=err_msg,
                consecutive_graph_failures=new_fail,
            )
        else:
            repo.update_loop_state(
                loop.loop_id,
                phase="graph_cycle",
                last_error=err_msg,
                consecutive_graph_failures=new_fail,
            )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_failed",
            phase_after="graph_cycle",
            iteration=iteration,
            error=err_msg,
        )


async def _tick_proposing(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Check if we should propose this build for publication."""
    score = loop.last_evaluator_score or 0.0

    if score >= loop.auto_publish_threshold and loop.last_staging_snapshot_id:
        _log.info(
            "Loop %s: proposing staging %s for publication (score %.2f >= %.2f)",
            loop.loop_id,
            loop.last_staging_snapshot_id,
            score,
            loop.auto_publish_threshold,
        )

        repo.update_loop_state(
            loop.loop_id,
            proposed_staging_id=loop.last_staging_snapshot_id,
            phase="idle",
        )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="proposed_for_publication",
            phase_after="idle",
            iteration=loop.iteration_count,
            staging_snapshot_id=loop.last_staging_snapshot_id,
            proposed=True,
        )

    repo.update_loop_state(loop.loop_id, phase="graph_cycle")
    return LoopTickResult(
        loop_id=loop.loop_id,
        action="continuing_iteration",
        phase_after="graph_cycle",
        iteration=loop.iteration_count,
    )


async def _tick_idle(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Idle — exploration directions or completion when nothing pending."""
    directions = loop.exploration_directions or []
    completed = {d.get("id") for d in (loop.completed_directions or []) if d.get("id")}

    pending = [d for d in directions if d.get("id") not in completed]

    if not pending:
        if loop.iteration_count >= loop.max_iterations:
            repo.update_loop_state(loop.loop_id, status="completed")
            return LoopTickResult(
                loop_id=loop.loop_id,
                action="completed",
                phase_after="idle",
                iteration=loop.iteration_count,
                completed=True,
            )

        repo.update_loop_state(loop.loop_id, phase="graph_cycle")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="exploring_new_direction",
            phase_after="graph_cycle",
            iteration=loop.iteration_count,
        )

    next_direction = pending[0]
    new_completed = (loop.completed_directions or []) + [next_direction]
    repo.update_loop_state(
        loop.loop_id,
        completed_directions=new_completed,
        phase="graph_cycle",
    )

    return LoopTickResult(
        loop_id=loop.loop_id,
        action="exploring_direction",
        phase_after="graph_cycle",
        iteration=loop.iteration_count,
    )


# ---------------------------------------------------------------------------
# Crawl feedback helpers (FIX 2 + FIX 3)
# ---------------------------------------------------------------------------

def _latest_planner_invocation_id(
    repo: "Repository",
    graph_run_id: UUID | None,
) -> UUID | None:
    if graph_run_id is None:
        return None
    rows = repo.list_role_invocations_for_graph_run(graph_run_id)
    planners = [r for r in rows if r.role_type == "planner"]
    if not planners:
        return None
    return planners[-1].role_invocation_id


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_page_summary_from_wrapper_parts(parts: dict[str, Any]) -> str:
    summ = (parts.get("summary") or "").strip()
    if summ:
        return summ[:300]
    title = parts.get("title") or ""
    desc = parts.get("description") or ""
    if title and desc:
        return f"{title} — {desc}"[:300]
    return (title or desc or "Page fetched")[:300]


def advance_crawl_frontier_after_graph(
    repo: "Repository",
    graph_result: dict[str, Any],
    *,
    identity_id: UUID,
    thread_id: UUID | None = None,
    context_label: str | None = None,
) -> None:
    """Advance the crawl frontier after any completed graph run (loop tick or ``POST /runs/start``).

    Uses tiered evidence to decide which URLs to mark visited:
      1. verified_fetch        (strongest — requires successful HTTP fetch)
      2. selected_by_planner   (explicit ``selected_urls`` in build_spec)
      3. build_spec_structured (URLs from structured build_spec ∩ offered)
      4. raw_payload_text      (from BuildSpecRecord, capped + domain-filtered)
      5. frontier_fallback     (first offered URL — guarantees progress)

    After tier resolution, each URL is optionally verified via real fetch.
    If fetch succeeds the evidence upgrades to ``verified_fetch``; otherwise
    the original tier is kept and the failure is recorded.

    Records provenance for every URL marked visited and emits a
    CRAWL_FRONTIER_ADVANCED event for full observability.
    """
    from kmbl_orchestrator.identity.crawl_evidence import (
        EvidenceTier,
        compute_planner_compliance,
        extract_planner_selected_urls,
        match_planner_selections_to_offered,
        resolve_evidence,
        try_upgrade_to_verified,
    )
    from kmbl_orchestrator.identity.crawl_state import (
        get_next_urls_to_crawl,
        record_page_visit,
    )
    from kmbl_orchestrator.identity.page_fetch import (
        extract_urls_from_build_spec,
    )
    from kmbl_orchestrator.identity.url_normalize import normalize_url
    from kmbl_orchestrator.runtime.run_events import (
        RunEventType,
        append_graph_run_event,
    )

    _label = context_label or str(identity_id)

    try:
        state = repo.get_crawl_state(identity_id)
        if state is None:
            return

        # Get the URLs that were offered to the planner
        offered_urls = get_next_urls_to_crawl(state, batch_size=5)
        if not offered_urls:  # empty list is falsy — covers both None and []
            _maybe_seed_external(repo, identity_id, context_label=_label)
            return

        # --- Collect evidence from each source ---
        build_spec = graph_result.get("build_spec") or {}

        # Capture raw selected_urls before resolution for compliance tracking
        raw_planner_selected = list(build_spec.get("selected_urls") or [])

        # FIX 1: extract explicit planner-selected URLs
        # FIX 2: resolve relative URLs against root_url before matching
        planner_selected = extract_planner_selected_urls(
            build_spec, root_url=state.root_url,
        )

        build_spec_urls = extract_urls_from_build_spec(build_spec)
        raw_payload_urls = _extract_raw_payload_urls(repo, graph_result)

        # --- Resolve using tiered priority ---
        report = resolve_evidence(
            offered_urls=offered_urls,
            planner_selected_urls=planner_selected,
            build_spec_urls=build_spec_urls,
            raw_payload_urls=raw_payload_urls,
            root_url=state.root_url,
            allowed_domains=_collect_allowed_domains(state),
        )

        run_id = str(graph_result.get("graph_run_id", "unknown"))

        # --- Planner compliance metrics (FIX 2 + FIX 3) ---
        # Count how many resolved planner-selected URLs actually matched offered
        offered_norm = {normalize_url(u) for u in offered_urls}
        ps_matched_count = sum(
            1 for u in planner_selected if normalize_url(u) in offered_norm
        )
        compliance = compute_planner_compliance(
            offered_urls=offered_urls,
            raw_planner_selected=raw_planner_selected,
            resolved_planner_selected=planner_selected,
            matched_count=ps_matched_count,
            build_spec_urls=build_spec_urls,
            evidence_tier_used=report.evidence_tier_used,
            root_url=state.root_url,
        )
        report.planner_compliance = compliance

        if compliance.get("omitted_despite_frontier"):
            _log.warning(
                "Crawl context=%s: planner omitted selected_urls despite %d offered frontier URLs — "
                "crawl evidence degraded to %s",
                _label,
                len(offered_urls),
                report.evidence_tier_used,
            )

        settings = get_settings()
        from kmbl_orchestrator.browser.crawl_guardrails import (
            cap_planner_urls_for_playwright,
            classify_source_kind,
            url_passes_grounded_visit,
        )
        from kmbl_orchestrator.browser.playwright_client import (
            visit_page_via_wrapper,
            wrapper_payload_to_fetch_parts,
        )
        from kmbl_orchestrator.domain import PageVisitLogRecord

        planner_matched = match_planner_selections_to_offered(
            planner_selected,
            offered_urls,
        )
        use_playwright = (
            bool(settings.kmbl_playwright_wrapper_url.strip())
            and bool(planner_matched)
            and settings.kmbl_playwright_max_pages_per_loop > 0
        )

        if use_playwright:
            urls_batch = cap_planner_urls_for_playwright(
                planner_matched,
                max_pages=settings.kmbl_playwright_max_pages_per_loop,
            )
            gid_u: UUID | None = None
            try:
                gid_u = _to_uuid(graph_result.get("graph_run_id"))
            except Exception:
                gid_u = None
            thread_id_raw = graph_result.get("thread_id")
            try:
                tid_u = UUID(str(thread_id_raw)) if thread_id_raw else thread_id
            except Exception:
                tid_u = thread_id
            rid = _latest_planner_invocation_id(repo, gid_u)

            for visit_url in urls_batch:
                sk = classify_source_kind(state, visit_url)
                ok_policy, block_reason = url_passes_grounded_visit(
                    state,
                    visit_url,
                    source_kind=sk,
                    settings=settings,
                )
                if not ok_policy:
                    repo.append_page_visit_log(
                        PageVisitLogRecord(
                            identity_id=identity_id,
                            thread_id=tid_u,
                            run_id=run_id,
                            graph_run_id=gid_u,
                            role_invocation_id=rid,
                            requested_url=visit_url,
                            resolved_url=None,
                            source_kind=sk,
                            status="blocked",
                            error=block_reason,
                            evidence_source="playwright_wrapper",
                        )
                    )
                    continue

                payload = {
                    "identity_id": str(identity_id),
                    "thread_id": str(tid_u) if tid_u else "",
                    "run_id": run_id,
                    "role_invocation_id": str(rid) if rid else "",
                    "graph_run_id": str(gid_u) if gid_u else "",
                    "url": visit_url,
                    "source_kind": sk,
                }
                data = visit_page_via_wrapper(payload, settings=settings)
                ok, parts = wrapper_payload_to_fetch_parts(data)
                same_dom = data.get("same_domain_links")
                if not isinstance(same_dom, list):
                    same_dom = []
                dl = data.get("discovered_links")
                if not isinstance(dl, list):
                    dl = []
                traits = data.get("traits") if isinstance(data.get("traits"), dict) else {}

                st = "ok" if ok else "error"
                err = None if ok else (data.get("error") or "visit_failed")

                repo.append_page_visit_log(
                    PageVisitLogRecord(
                        identity_id=identity_id,
                        thread_id=tid_u,
                        run_id=run_id,
                        graph_run_id=gid_u,
                        role_invocation_id=rid,
                        requested_url=str(data.get("requested_url") or visit_url),
                        resolved_url=data.get("resolved_url") if isinstance(data.get("resolved_url"), str) else None,
                        source_kind=sk,
                        status=st,
                        http_status=_safe_int(data.get("http_status")),
                        page_title=data.get("page_title") if isinstance(data.get("page_title"), str) else None,
                        meta_description=data.get("meta_description")
                        if isinstance(data.get("meta_description"), str)
                        else None,
                        summary=data.get("summary") if isinstance(data.get("summary"), str) else None,
                        discovered_links=[str(x) for x in dl if isinstance(x, str)],
                        same_domain_links=[str(x) for x in same_dom if isinstance(x, str)],
                        traits_json=dict(traits),
                        evidence_source="playwright_wrapper",
                        timing_ms=_safe_int(data.get("timing_ms")),
                        error=err,
                        snapshot_path=data.get("snapshot_path")
                        if isinstance(data.get("snapshot_path"), str)
                        else None,
                    )
                )

                if ok:
                    report.verified_urls.append(visit_url)
                    from kmbl_orchestrator.runtime.reference_library import (
                        build_reference_sketch_from_wrapper,
                    )

                    _sketch = build_reference_sketch_from_wrapper(data)
                    state = record_page_visit(
                        repo,
                        identity_id,
                        visit_url,
                        summary=_build_page_summary_from_wrapper_parts(parts),
                        design_signals=parts.get("design_signals") or None,
                        tone_keywords=parts.get("tone_keywords") or None,
                        discovered_links=parts.get("discovered_links") or None,
                        provenance_source="playwright_wrapper",
                        provenance_tier=EvidenceTier.VERIFIED_FETCH,
                        run_id=run_id,
                        reference_sketch=_sketch,
                    )
        else:
            # --- FIX 2: attempt verified fetch for each resolved URL ---
            upgraded_visited: list[tuple] = []
            for ev in report.final_visited:
                upgraded_ev, vf = try_upgrade_to_verified(ev, report, timeout=5.0)
                upgraded_visited.append((upgraded_ev, vf))

            # --- Visit each URL with provenance ---
            for upgraded_ev, vf in upgraded_visited:
                if vf.success:
                    state = record_page_visit(
                        repo,
                        identity_id,
                        upgraded_ev.url,
                        summary=_build_page_summary_from_verification(vf),
                        design_signals=vf.design_signals or None,
                        tone_keywords=vf.tone_keywords or None,
                        discovered_links=vf.discovered_links or None,
                        provenance_source=upgraded_ev.source,
                        provenance_tier=upgraded_ev.tier,
                        run_id=run_id,
                    )
                else:
                    state = record_page_visit(
                        repo,
                        identity_id,
                        upgraded_ev.url,
                        summary=f"Referenced in build_spec (run_id={run_id})",
                        provenance_source=upgraded_ev.source,
                        provenance_tier=upgraded_ev.tier,
                        run_id=run_id,
                    )

        _log.info(
            "Crawl context=%s: crawl advance — offered=%d, planner_selected=%d, "
            "mentioned=%d, final=%d, verified=%d, tier=%s, playwright=%s",
            _label,
            len(report.offered_urls),
            len(report.planner_selected_urls),
            len(report.mentioned_urls),
            len(report.final_visited),
            len(report.verified_urls),
            report.evidence_tier_used,
            use_playwright,
        )

        # Update evidence_tier_used to reflect any upgrades
        if report.verified_urls:
            report.evidence_tier_used = "verified_fetch"

        # --- Observability: emit events ---
        graph_run_id = graph_result.get("graph_run_id")
        if graph_run_id:
            try:
                gid = _to_uuid(graph_run_id)
                append_graph_run_event(
                    repo,
                    gid,
                    RunEventType.CRAWL_FRONTIER_ADVANCED,
                    payload=report.to_dict(),
                )
                # Emit planner compliance event for monitoring
                append_graph_run_event(
                    repo,
                    gid,
                    RunEventType.PLANNER_CRAWL_COMPLIANCE,
                    payload=compliance,
                )
            except Exception as exc:
                _log.debug("crawl frontier event emit failed: %s", str(exc)[:200])

        # Operational visit-log retention (0 = disabled). Keeps Supabase from growing unbounded.
        rd = settings.kmbl_page_visit_log_retention_days
        if rd > 0:
            try:
                repo.prune_page_visit_logs_older_than(older_than_days=rd)
            except Exception as exc:
                _log.debug("page_visit_log prune failed: %s", str(exc)[:160])

        # Activate external inspiration when internal crawl is exhausted
        if state.crawl_status == "exhausted":
            _maybe_seed_external(repo, identity_id, context_label=_label)

    except Exception as exc:
        _log.warning(
            "Crawl context=%s: crawl frontier advance failed: %s",
            _label,
            str(exc)[:200],
        )


def _advance_crawl_frontier(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    graph_result: dict[str, Any],
) -> None:
    """Backward-compatible wrapper: autonomous loop tick uses ``AutonomousLoopRecord``."""
    advance_crawl_frontier_after_graph(
        repo,
        graph_result,
        identity_id=loop.identity_id,
        thread_id=loop.current_thread_id,
        context_label=str(loop.loop_id),
    )


def _to_uuid(value: Any) -> UUID:
    """Coerce a string or UUID to UUID."""
    return value if isinstance(value, UUID) else UUID(value)


def _extract_raw_payload_urls(
    repo: "Repository",
    graph_result: dict[str, Any],
) -> list[str]:
    """Extract URLs from BuildSpecRecord.raw_payload_json (heuristic source)."""
    from kmbl_orchestrator.identity.page_fetch import extract_urls_from_build_spec

    build_spec_id = graph_result.get("build_spec_id")
    if not build_spec_id:
        return []

    try:
        record = repo.get_build_spec(
            _to_uuid(build_spec_id),
        )
        if record is None or not record.raw_payload_json:
            return []
        return extract_urls_from_build_spec(record.raw_payload_json)
    except Exception as exc:
        _log.debug(
            "raw_payload URL extraction failed build_spec_id=%s: %s",
            build_spec_id,
            str(exc)[:200],
        )
        return []


def _collect_allowed_domains(state: "CrawlStateRecord") -> set[str]:
    """Build the set of allowed domains from external inspiration URLs."""
    from urllib.parse import urlparse

    allowed: set[str] = set()
    for u in state.external_inspiration_urls:
        try:
            host = (urlparse(u).hostname or "").lower().removeprefix("www.")
            if host:
                allowed.add(host)
        except Exception:
            pass
    return allowed


def _build_page_summary_from_verification(vf: "FetchVerification") -> str:
    """Build a one-line page summary from a FetchVerification result."""
    title = vf.title or ""
    desc = vf.description or ""
    if title and desc:
        return f"{title} — {desc}"[:300]
    return (title or desc or "Page fetched")[:300]


def _maybe_seed_external(
    repo: "Repository",
    identity_id: UUID,
    *,
    context_label: str | None = None,
) -> None:
    """Seed external inspiration URLs when internal crawl is exhausted.

    Derives inspiration sources from the identity profile when available,
    falling back to defaults only if needed.
    """
    from kmbl_orchestrator.identity.crawl_state import seed_external_inspiration

    label = context_label or str(identity_id)
    try:
        state = repo.get_crawl_state(identity_id)
        if state is None:
            return
        # Inspiration URLs are only seeded after internal grounding completes (phase gate).
        if state.crawl_phase != "inspiration_expansion":
            return
        if state.external_inspiration_urls:
            return
        if state.crawl_status != "exhausted":
            return

        # Try to derive identity-aware inspiration URLs
        inspiration_urls = _derive_inspiration_urls_for_identity(repo, identity_id)
        seed_external_inspiration(repo, identity_id, urls=inspiration_urls or None)
        _log.info(
            "Crawl context=%s: seeded external inspiration for identity %s (%d urls)",
            label,
            identity_id,
            len(inspiration_urls) if inspiration_urls else 3,  # 3 = default count
        )
    except Exception as exc:
        _log.warning(
            "Crawl context=%s: external inspiration seeding failed: %s",
            label,
            str(exc)[:200],
        )


def _derive_inspiration_urls_for_identity(
    repo: "Repository",
    identity_id: UUID,
) -> list[str] | None:
    """Derive inspiration URLs from identity profile themes.

    Returns None to use defaults if no identity-specific URLs can be derived.
    """
    try:
        profile = repo.get_identity_profile(identity_id)
        if profile is None:
            return None
        facets = profile.facets_json or {}
        themes: list[str] = facets.get("themes", [])
        if not themes:
            return None

        # Map identity themes to relevant inspiration sources
        _THEME_INSPIRATION: dict[str, list[str]] = {
            "editorial": [
                "https://www.typewolf.com",
                "https://www.readymag.com/explore",
            ],
            "artistic": [
                "https://www.behance.net",
                "https://www.are.na",
            ],
            "cinematic": [
                "https://www.studiomaertens.com",
                "https://www.awwwards.com/websites/film/",
            ],
            "experimental": [
                "https://experiments.withgoogle.com",
                "https://www.are.na",
            ],
            "minimal": [
                "https://www.siteinspire.com",
                "https://minimalissimo.com",
            ],
            # WebGL / creative-code adjacent — three.js docs + examples as reference crawl targets
            "technical": [
                "https://threejs.org/docs/",
                "https://threejs.org/examples/",
                "https://github.com/mrdoob/three.js",
            ],
        }

        urls: list[str] = []
        for theme in themes:
            tl = theme.lower()
            for key, theme_urls in _THEME_INSPIRATION.items():
                if key in tl:
                    urls.extend(u for u in theme_urls if u not in urls)
            if any(
                k in tl
                for k in (
                    "3d",
                    "webgl",
                    "three.js",
                    "threejs",
                    "spatial",
                    "immersive",
                )
            ):
                for u in _THEME_INSPIRATION["technical"]:
                    if u not in urls:
                        urls.append(u)
        return urls if urls else None
    except Exception:
        return None
