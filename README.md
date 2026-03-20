# ArchMind v0.7.0

ArchMind is an AI-driven architecture and development workflow engine.

It now supports an end-to-end loop:
`idea -> generation -> validation -> run -> health -> auto-fix`

## Major Milestone in v0.7.0

ArchMind now supports a much more complete execution loop:

- Idea -> Project Generation
- Structure Validation
- Backend Runtime Detection
- Local Backend Run with Health Check
- Auto-Run after `/idea_local`
- Deploy vs Runtime State Separation
- Auto-Fix (self-healing runtime retry)
- Preflight Check before execution

## v0.7.0 Key Changes

### Preflight Check
- Detects and fixes issues before execution:
  - Missing dependencies
  - Import errors
  - Database initialization
  - Environment setup
  - Port conflicts

### Auto-Fix (Self-Healing)
- Analyzes runtime failures from logs
- Applies fixes automatically
- Retries backend execution with bounded attempts

### Local Runtime Execution
- `/run backend` executes local backend with health check
- `/idea_local` can auto-run backend right after generation
- Runtime diagnostics are available from `/logs backend`

### State Architecture
- Clear separation of state domains:
  - `deploy`: cloud/deployment status
  - `runtime`: local execution/runtime status

## Core Workflow

- design from idea
- suggest project structure
- build development plan
- generate project
- auto-run backend
- inspect current project
- improve or continue with next suggestions

## Key Commands

- `/design <idea>`
- `/plan <idea>`
- `/idea_local <idea>`
- `/run backend`
- `/inspect`
- `/improve`
- `/next`

## Offline Install

For offline environments, ArchMind supports installation using a bundled dependency archive such as `wheelhouse.zip`.
You can verify offline installation with `scripts/offline_install_verify.sh`.

## What v0.7.0 Means

ArchMind can now:

> generate, run, validate, and stabilize projects with minimal manual intervention.

## Next

- multi-service orchestration
- persistent process manager
- UI layer
