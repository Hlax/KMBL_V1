# CLAUDE.md

Targeted runtime-debug pass.

Prioritize:
- planner runs once per autonomous start session
- generator/evaluator iterate without re-planning
- remove portfolio-shell defaults for immersive runs
- persist crawl/reference state across sessions
- identity pages exhaust before inspiration crawling starts
- give evaluator a reachable preview URL
- fix non-elevated artifact write path
- enforce workspace-first artifact flow (no full inline HTML echo)
- verify whether batching/multi-zone is real in runtime or only in docs/tests
- keep OpenClaw SOUL short; use read-on-demand refs

Do not:
- solve this with more prose alone
- re-plan during the normal iteration loop
- treat selected_urls as same-session planner feedback
- keep grading immersive runs by portfolio section selectors
- rely on localhost-only preview for evaluator
- use giant inline python -c file writes
- allow large code blobs back into session when workspace refs exist
- bloat SOUL.md

For this pass, report:
- Root causes from the log
- Files changed
- What changed
- Why
- Tests
- Remaining blockers