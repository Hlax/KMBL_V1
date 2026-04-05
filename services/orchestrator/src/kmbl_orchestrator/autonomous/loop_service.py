"""Autonomous loop service — one URL → identity → repeated LangGraph runs until done or proposal."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from kmbl_orchestrator.persistence.repository import Repository

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import AutonomousLoopRecord
from kmbl_orchestrator.identity.extract import extract_identity_from_url
from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
from kmbl_orchestrator.seeds import build_identity_url_static_frontend_event_input
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

    event_input = build_identity_url_static_frontend_event_input(
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

def _advance_crawl_frontier(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    graph_result: dict[str, Any],
) -> None:
    """Advance the crawl frontier after a graph run — grounded in reality.

    Only marks URLs as visited if they were actually referenced by the planner
    in the build_spec output. Falls back to marking the first offered URL if
    the planner didn't reference any (to ensure forward progress).

    Optionally fetches real page data for visited URLs when possible.
    """
    from kmbl_orchestrator.identity.crawl_state import (
        get_next_urls_to_crawl,
        record_page_visit,
    )
    from kmbl_orchestrator.identity.page_fetch import (
        extract_urls_from_build_spec,
        filter_crawl_urls,
    )

    try:
        state = repo.get_crawl_state(loop.identity_id)
        if state is None:
            return

        # Get the URLs that were offered to the planner
        offered_urls = get_next_urls_to_crawl(state, batch_size=5)
        if not offered_urls:
            _maybe_seed_external(repo, loop)
            return

        # --- Grounded URL selection ---
        # Extract URLs the planner actually referenced in build_spec
        build_spec = graph_result.get("build_spec") or {}
        planner_referenced = extract_urls_from_build_spec(build_spec)
        actually_used = filter_crawl_urls(planner_referenced, offered_urls)

        # Fallback: if planner didn't reference any offered URL, mark the first
        # one as visited to guarantee forward progress (prevents infinite loops)
        if not actually_used:
            actually_used = [offered_urls[0]]
            _log.info(
                "Loop %s: planner did not reference any offered URLs; "
                "marking first offered URL for forward progress: %s",
                loop.loop_id,
                offered_urls[0],
            )

        _log.info(
            "Loop %s: grounded crawl advance — offered=%d, planner_referenced=%d, marking=%d",
            loop.loop_id,
            len(offered_urls),
            len(planner_referenced),
            len(actually_used),
        )

        # --- Visit each URL with real page data when possible ---
        for url in actually_used:
            page_data = _try_fetch_page(url)
            if page_data is not None:
                state = record_page_visit(
                    repo,
                    loop.identity_id,
                    url,
                    summary=_build_page_summary(page_data),
                    design_signals=page_data.get("design_signals"),
                    tone_keywords=page_data.get("tone_keywords"),
                    discovered_links=page_data.get("links"),
                )
            else:
                # No real fetch possible — record with synthetic summary
                state = record_page_visit(
                    repo,
                    loop.identity_id,
                    url,
                    summary=f"Referenced in build_spec (run_id={graph_result.get('graph_run_id', 'unknown')})",
                )

        # Activate external inspiration when internal crawl is exhausted
        if state.crawl_status == "exhausted":
            _maybe_seed_external(repo, loop)

    except Exception as exc:
        _log.warning(
            "Loop %s: crawl frontier advance failed: %s",
            loop.loop_id,
            str(exc)[:200],
        )


def _try_fetch_page(url: str) -> dict[str, Any] | None:
    """Attempt to fetch real page data, returning None on any failure.

    This is best-effort — network failures, timeouts, non-HTML pages
    all result in None. The crawl loop still advances regardless.
    """
    from kmbl_orchestrator.identity.page_fetch import fetch_page_data

    try:
        return fetch_page_data(url, timeout=5.0)
    except Exception:
        return None


def _build_page_summary(page_data: dict[str, Any]) -> str:
    """Build a one-line page summary from fetched page data."""
    title = page_data.get("title", "")
    desc = page_data.get("description", "")
    if title and desc:
        return f"{title} — {desc}"[:300]
    return (title or desc or "Page fetched")[:300]


def _maybe_seed_external(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> None:
    """Seed external inspiration URLs when internal crawl is exhausted.

    Derives inspiration sources from the identity profile when available,
    falling back to defaults only if needed.
    """
    from kmbl_orchestrator.identity.crawl_state import seed_external_inspiration

    try:
        state = repo.get_crawl_state(loop.identity_id)
        if state is None or state.crawl_status != "exhausted":
            return
        # Already seeded?
        if state.external_inspiration_urls:
            return

        # Try to derive identity-aware inspiration URLs
        inspiration_urls = _derive_inspiration_urls_for_identity(repo, loop.identity_id)
        seed_external_inspiration(repo, loop.identity_id, urls=inspiration_urls or None)
        _log.info(
            "Loop %s: seeded external inspiration for identity %s (%d urls)",
            loop.loop_id,
            loop.identity_id,
            len(inspiration_urls) if inspiration_urls else 3,  # 3 = default count
        )
    except Exception as exc:
        _log.warning(
            "Loop %s: external inspiration seeding failed: %s",
            loop.loop_id,
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
        }

        urls: list[str] = []
        for theme in themes:
            for key, theme_urls in _THEME_INSPIRATION.items():
                if key in theme.lower():
                    urls.extend(u for u in theme_urls if u not in urls)
        return urls if urls else None
    except Exception:
        return None
