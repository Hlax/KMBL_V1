# CLAUDE.md

## KMBL Orchestrator Reference

This document is a reference for how agents working in the KMBL ecosystem should think about the system, its intent, and the style of harness architecture it is aiming toward.

It is not a changelog, not an implementation audit, and not a source of truth for what is already complete. Agents should investigate the current repository state, tests, contracts, and runtime behavior on their own. This file exists to provide architectural direction and judgment guidance so that future work stays aligned with the kind of system KMBL is meant to become.

The architecture described here is inspired by long-running multi-agent harness design, but adapted for KMBL’s actual problem: not expanding a short prompt into a spec, but extracting taste, tone, judgment, structure, and experience signals from an Identity URL and using those signals to drive autonomous generation.

---

## Local system paths

These paths are part of the broader working environment and may be relevant when tracing how the full system is intended to operate:

- **Workspace**
  - `C:\Users\guestt\OneDrive\Desktop\KMBL\KMBL_WORKSPACE`

- **OpenClaw repo**
  - `C:\Users\guestt\.openclaw`

- **Copy of OpenClaw agent docs kept near the orchestrator**
  - `C:\Users\guestt\OneDrive\Desktop\KMBL\KMBL_V1\docs\openclaw-agents`

Agents should treat these as neighboring system references, not assumptions. Inspect them when needed, but do not assume this file fully describes their current implementation.

---

## What KMBL is trying to do

KMBL is aiming for a harnessed orchestration system that can study an identity source, form a grounded point of view, generate work against that point of view, evaluate the result with skepticism, and iterate until the result is strong enough to stage, review, and eventually publish.

The central idea is simple:

1. **Ground first**
   - Begin from the Identity URL, not from a large handcrafted brief.
   - Extract taste, tone, creative direction, interaction patterns, signals of judgment, and evidence of what the identity appears to value.

2. **Generate with direction, not with rigid over-specification**
   - Convert the grounded understanding into a working plan or build direction.
   - Keep deliverables clear, but avoid overcommitting to brittle low-level implementation details too early.

3. **Evaluate from the outside**
   - Judge the output as a user would experience it, not only as code or static artifacts.
   - Make the evaluator skeptical enough to catch mediocrity, generic defaults, broken interactions, shallow implementations, and false confidence.

4. **Iterate toward stronger work**
   - Improve the current direction when it is promising.
   - Pivot when the result is technically functional but creatively weak, generic, or misaligned with the identity.

The goal is not merely “a completed build.” The goal is a build that feels intentionally shaped by the identity it came from.

---

## The north star

KMBL should behave less like a single-pass code generator and more like a long-running creative and technical harness.

The aspiration is that repeated evaluation and iteration can produce results that make meaningful jumps in originality and quality. In the same way that an iterative design harness can move from a safe but predictable layout into something spatial, surprising, and distinctive, KMBL should be capable of evolving from obvious first-pass interpretations into more ambitious experiences when the evidence supports that move.

That does **not** mean random novelty for its own sake. It means the system should be able to move beyond generic portfolio defaults, stock component compositions, and shallow frontend polish, and instead find forms, interaction models, layouts, and experiential structures that feel like they belong to the studied identity.

The most valuable creative leap is one that is both surprising and grounded.

---

## Why this needs a harness

Naive implementations tend to fall short for two main reasons.

### 1. Long tasks lose coherence

Agents often drift on long-running work. As context grows, they can become less coherent, wrap up prematurely, or narrow their ambition in order to “finish.” This means KMBL should prefer structures that preserve direction across long runs, including summaries, handoff artifacts, stateful records, staged checkpoints, or other mechanisms that allow continuity without requiring every decision to remain in raw conversational context.

The exact implementation may vary over time. The principle does not: long tasks need structure.

### 2. Self-evaluation is too lenient

The same model that builds a thing is often a poor judge of that thing. It tends to praise its own work, excuse missing depth, and accept outputs that a human would immediately recognize as generic, incomplete, or only superficially impressive.

KMBL should therefore preserve a meaningful separation between:
- the agent or process that proposes or builds, and
- the agent or process that evaluates.

The evaluator does not need to be hostile. But it must be independent enough to be skeptical, concrete, and hard to impress.

---

## The KMBL architecture shape

KMBL is best understood as a three-part harness:

- **Planner**
- **Generator**
- **Evaluator**

These roles may be implemented through OpenClaw agents, orchestration nodes, structured contracts, file-based artifacts, database-backed state, or future variants. The exact wiring may change. The role boundaries are still useful.

---

## Planner

### The planner’s job

In KMBL, the planner does not begin from a one-sentence product prompt. It begins from an **Identity URL** and whatever grounded evidence can be collected from it.

Its role is to transform raw identity evidence into a build direction that is ambitious, coherent, and useful to downstream agents.

The planner should answer questions like:

- What kind of experience is this identity asking for, even if indirectly?
- What seems central versus incidental?
- What interaction patterns, tone, pacing, materials, references, or moods recur?
- What does this identity appear to value aesthetically?
- What would count as a faithful interpretation without being derivative?
- Where are the opportunities for ambition?
- What should be preserved as constraints, and what should remain open for invention?

### What the planner should avoid

The planner should avoid becoming a brittle technical spec writer.

Its job is not to guess every implementation detail in advance. Over-specifying low-level technical choices too early can cause downstream work to inherit bad assumptions. It is better to be clear about outcomes, experiential goals, constraints, and quality bars than to lock the whole system into a premature implementation path.

### The planner’s output

A strong planner output should provide:

- a grounded interpretation of the identity
- a clear build direction
- the key experiential and aesthetic priorities
- the major deliverables or goals
- the suggested level of ambition
- evidence-backed references to what informed those judgments
- room for the generator to solve the problem creatively

The planner should not merely summarize the crawled pages. It should synthesize them into direction.

### The planner’s stance

The planner should be ambitious, but not arbitrary.

It should not flatten the identity into a generic website category. It should not assume the safest possible form. It should also not invent a disconnected concept that has no grounding in the source material.

Its best work is high-level, evidence-based, creatively open-ended direction.

---

## Generator

### The generator’s job

The generator turns the planner’s direction into a real working artifact.

It should build with a strong sense of authorship, but remain accountable to the grounded identity and the evaluator’s critique. The generator should be capable of making deliberate decisions about layout, interaction, motion, structure, hierarchy, mood, and technical implementation without needing every detail pre-specified.

### How the generator should work

The generator should behave like a craft-focused implementer operating within an iterative harness.

That means:

- take one meaningful step at a time
- keep the current direction legible
- build real functionality, not placeholders masquerading as depth
- prefer coherent systems over disconnected flourishes
- leave enough evidence in outputs, artifacts, or summaries for later evaluation and continuation
- respond to critique with intention, not defensive restatement

The generator should be willing to do one of two things after evaluation:

- **refine** when the current direction is promising and improving
- **pivot** when the direction is technically competent but creatively weak, generic, shallow, or poorly aligned with the identity

### What the generator should avoid

The generator should avoid:

- default portfolio patterns unless the identity clearly warrants them
- shallow “looks polished” outputs with weak interaction depth
- stock layouts dressed up with gradients or trendy effects
- adding complexity that does not improve the experience
- treating passing superficial checks as success
- forcing the result into the most common AI-generated visual tropes

The generator should not confuse movement with originality. Distinctive work comes from judgment, not decoration.

---

## Evaluator

### The evaluator’s job

The evaluator exists to independently judge the output and provide critique that can drive a better next iteration.

Its role is not to admire the artifact. Its role is to inspect it, exercise it, compare it against the intended direction, and decide whether it is truly strong enough.

The evaluator should operate as close to real usage as possible:
- inspect live output when possible
- navigate the experience
- test primary flows and critical interactions
- verify that the implementation is not merely presentational
- identify where the build is generic, incomplete, or misaligned
- produce actionable feedback

### The evaluator’s stance

The evaluator should be skeptical, concrete, and difficult to satisfy with surface-level polish.

It should not pass work just because:
- the UI looks modern
- the code compiles
- the page loads
- there is some animation
- there is some 3D or canvas presence
- the output resembles a familiar site category

The evaluator should be specifically alert to:
- generic templates
- shallow interactivity
- broken or confusing user flows
- identity misreadings
- overuse of library defaults
- “AI slop” patterns
- impressive-looking but low-depth implementations
- evidence-free claims by the generator

### The evaluator’s output

A strong evaluator output should include:

- what is working
- what is not working
- what feels generic
- what feels identity-aligned
- what is underbuilt or stubbed
- what user-facing behaviors fail
- whether the current direction should be refined or abandoned
- what specific changes would materially improve the next iteration

It should judge both technical quality and experiential quality.

---

## KMBL quality criteria

Because some of KMBL’s work is subjective, quality needs to be made more gradable. The following criteria are meant to guide judgment for both generator and evaluator.

### 1. Identity coherence

Does the output feel like a coherent interpretation of the studied identity rather than a generic build with a few borrowed cues?

Strong work here means the structure, tone, interaction model, visual language, pacing, and content choices all feel shaped by the same point of view.

### 2. Originality

Is there evidence of custom thinking, or is this mostly composed from templates, defaults, and predictable AI habits?

Strong work here means the result contains deliberate, grounded decisions. It should feel authored rather than assembled from the safest familiar parts.

### 3. Craft

Is the work competently executed?

This includes hierarchy, spacing, contrast, responsiveness, typography, motion discipline, interaction clarity, code organization, and implementation soundness. Craft is not the highest bar, but weak craft undermines everything else.

### 4. Functionality

Can a real user understand what to do and successfully use the experience?

This includes interaction correctness, navigation clarity, reliable behavior, and whether major intended features are genuinely implemented.

### 5. Experiential depth

Does the experience go beyond surface presentation?

Strong work here means there is meaningful interaction, spatial or narrative logic when appropriate, and enough depth that the artifact feels like a real experience rather than a visual mockup with a few clickable zones.

### 6. Grounding fidelity

Can the connection back to the identity evidence be felt?

This does not mean direct imitation. It means the build shows evidence that it was actually informed by the identity source instead of merely using it as a label.

---

## Relative importance of the criteria

KMBL should not overweight “it works” at the expense of “it means something.”

In many cases, baseline craft and baseline functionality are easier for models to achieve than originality, identity coherence, and experiential depth. Because of that, the system should be especially attentive to whether the result is distinctive, grounded, and intentional.

A technically competent but generic output should not be treated as a strong success.

---

## What “good” looks like in practice

A good KMBL result usually has these traits:

- It feels anchored in the identity source.
- It has a clear point of view.
- It makes choices a generic scaffold would not make.
- It avoids obvious AI-default aesthetics.
- Its interaction model supports the concept instead of merely decorating it.
- It is usable.
- It is technically real enough to survive skeptical inspection.
- It leaves a future agent enough state, artifacts, or summaries to continue iterating coherently.

---

## What “bad” looks like in practice

A weak KMBL result often looks like one of these:

- a default portfolio shell with minor styling changes
- a library demo wearing the identity as a skin
- a visually trendy page that says little about the source
- a polished landing page with almost no experiential depth
- a 3D or animated treatment that adds spectacle but not meaning
- a build that gestures toward complexity but stubs major behaviors
- an output that mistakes reference gathering for interpretation

---

## Refinement versus pivot

A central harness behavior is deciding whether to continue the current direction or change it materially.

### Refine when:
- the core interpretation feels right
- the output is becoming more coherent
- the quality is improving
- the gaps are mostly executional
- the identity signal is present but under-realized

### Pivot when:
- the output is generic despite competence
- the structure itself is limiting the concept
- the identity reading feels shallow or wrong
- the build has plateaued into safe patterns
- there is no path from “slightly better” to “actually distinctive”

A pivot should not be random. It should be a better interpretation of the same grounded evidence.

---

## On state, memory, and continuity

KMBL is intended for long-running work. Agents should preserve enough structure that later work can continue without re-deriving everything from scratch.

Useful continuity can come from:
- structured planner outputs
- contracts
- summaries
- evidence records
- crawl memory
- evaluation artifacts
- staging state
- snapshots
- concise descriptions of why prior decisions were made

The exact medium may differ. The important thing is that continuity should preserve judgment, not just raw data.

---

## On compaction, resets, and task duration

There is no single mandated strategy here.

Some systems benefit from continuous runs with compaction. Others require resets and structured handoffs. KMBL should use whatever combination best preserves coherence, ambition, and evaluability for the current model/runtime stack.

The architectural lesson is more important than the implementation detail:
- long-running autonomous work needs mechanisms that prevent drift
- the system should prefer structured continuity over accidental context accumulation

---

## On tools and external grounding

When relevant, agents should use the available system tools to observe the real artifact, not just reason from code or intention.

That includes:
- inspecting live output
- browsing pages
- validating interactions
- reviewing structured artifacts
- comparing implementation against grounded identity evidence

When judging quality, real observation should carry more weight than generator self-description.

---

## On neighboring repos and docs

This repository is part of a larger operating environment.

Agents should be aware that:
- the workspace may contain generated or staged artifacts
- the OpenClaw repo may define or influence agent behavior
- the copied OpenClaw agent docs near this repo may reflect the intended role design more closely than assumptions made from code alone

These are resources for investigation, not substitutes for inspection.

---

## Working posture for future agents

When working in KMBL:

- Start by understanding the current system honestly.
- Use this file as direction, not evidence.
- Investigate before proposing major changes.
- Preserve the planner / generator / evaluator role clarity where possible.
- Keep the planner grounded and high level.
- Keep the generator ambitious but accountable.
- Keep the evaluator skeptical and concrete.
- Optimize for grounded originality, not generic completion.
- Prefer real experiential quality over checkbox success.
- Leave behind structured outputs that help the next iteration.

---

## Final principle

KMBL should not aim to be a system that merely produces websites from URLs.

It should aim to be a system that studies an identity, forms judgment, generates an experience from that judgment, tests that experience against reality, and iterates until the result feels meaningfully shaped rather than merely produced.

The best version of this system will not just finish builds.

It will develop taste-backed, evidence-grounded, technically real work that becomes more distinctive through the loop.