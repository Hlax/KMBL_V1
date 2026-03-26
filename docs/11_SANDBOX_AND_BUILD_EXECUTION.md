# Sandbox and Build Execution

## Purpose

Define how Generator outputs become:

- real code
- real environments
- testable systems
- previewable artifacts

This document specifies:

- sandbox structure
- build execution flow
- environment isolation
- preview generation
- evaluator integration

---

## Core Principle

Generator output must become a **testable system**.

If it cannot be evaluated, it is not a valid build.

---

## System Boundary

KMBL does not execute builds directly.

KMBL:

- sends build instructions
- receives build results
- stores artifacts
- orchestrates iteration

KiloClaw:

- executes build actions
- interacts with filesystem
- runs commands
- produces artifacts

---

# 1. Sandbox Model

## Definition

A sandbox is an isolated environment where a build is applied and executed.

---

## Requirements

Every sandbox must:

- be isolated from other runs
- be reproducible
- support build execution
- expose a preview target
- be accessible to evaluator

---

## v1 Options

### Option A — Git Worktree (Recommended)

- create isolated worktree per build_candidate
- apply generator changes
- run build locally or remotely

---

### Option B — Branch-Based Sandbox

- create temporary branch
- apply changes
- deploy preview

---

### Option C — Ephemeral Container (Future)

- spin up container per build
- fully isolated runtime
- destroy after evaluation

---

## Sandbox Identifier

Each sandbox must produce:

- `sandbox_ref` (internal reference)
- `preview_url` (external access point)

---

# 2. Build Execution Flow

## Generator Phase

Generator returns:

'''json
{
  "proposed_changes": {},
  "artifact_outputs": [],
  "updated_state": {},
  "sandbox_ref": "string",
  "preview_url": "string"
}
'''

---

## Execution Steps

1. create sandbox (worktree / branch / container)
2. apply proposed_changes
3. install dependencies (if needed)
4. run build commands
5. start preview server or deploy preview
6. return preview_url

---

## Output Requirements

Generator must ensure:

- system compiles (if applicable)
- system runs
- preview is accessible
- evaluator can connect

---

# 3. Proposed Changes Model

## Types of Changes

Generator may produce:

- file creation
- file modification
- file deletion
- dependency updates
- configuration changes

---

## Example Structure

'''json
{
  "files": [
    {
      "path": "app/page.tsx",
      "action": "create",
      "content": "..."
    }
  ],
  "commands": [
    "npm install",
    "npm run build"
  ]
}
'''

---

## Rule

Changes must be deterministic.

No hidden actions outside declared changes.

---

# 4. Artifact Outputs

Artifacts are additional outputs produced by Generator.

Examples:

- images
- generated content
- logs
- build outputs

---

## Storage

Artifacts should be:

- uploaded to storage
- referenced via URLs
- stored in `artifact_refs_json`

---

# 5. Preview System

## Definition

A preview is a live representation of the build_candidate.

---

## Requirements

Preview must:

- reflect current build_candidate
- be accessible via URL
- remain stable during evaluation

---

## Options

### Local Preview Server

- run dev server
- expose via tunnel

### Hosted Preview

- deploy to Vercel or similar
- return deployment URL

---

## Recommendation

Start with:

- simple preview server or lightweight deploy

Avoid complex infra early.

---

# 6. Evaluator Integration

Evaluator receives:

'''json
{
  "build_candidate": {
    "preview_url": "...",
    "artifact_refs": []
  }
}
'''

---

## Evaluator Responsibilities

- access preview_url
- run tests
- inspect DOM / UI
- validate functionality

---

## Key Rule

Evaluator must interact with the **real system**, not abstract data.

---

# 7. Iteration Handling

## On iteration

Generator must:

- reuse existing sandbox if possible
- apply incremental changes
- avoid full rebuild when unnecessary

---

## Strategy

- patch existing files
- rebuild only affected parts
- maintain preview continuity

---

# 8. Failure Modes

## Build Failure

- return partial output
- include logs in artifacts
- do not crash silently

---

## Preview Failure

- return preview_url = null
- include failure reason
- evaluator should return `blocked`

---

## Sandbox Failure

- create new sandbox
- retry build once
- escalate to interrupt if repeated

---

# 9. Cleanup Strategy

## v1

- keep sandboxes temporarily
- clean manually or periodically

---

## Future

- automatic sandbox lifecycle management
- TTL-based cleanup
- snapshot-based preservation

---

# 10. Persistence Integration

KMBL must store:

- sandbox_ref
- preview_url
- artifact_refs

Inside:

- build_candidate
- evaluation_report (if relevant)

---

# 11. Design Rules

## Rule 1

Every build must be executable.

---

## Rule 2

Every build must be evaluatable.

---

## Rule 3

Sandbox must be isolated.

---

## Rule 4

Preview must reflect actual system state.

---

## Rule 5

Generator must not bypass sandbox.

---

# 12. Minimal v1 Scope

Start with:

- git worktree sandbox
- basic file patching
- simple build command execution
- single preview URL

Skip:

- container orchestration
- advanced caching
- multi-environment builds

---

# 13. Future Extensions

- containerized builds
- parallel sandbox execution
- diff-based builds
- persistent preview environments
- snapshot-linked sandbox replay

Not required for v1.