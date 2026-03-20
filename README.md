# ArchMind v0.8.0

ArchMind is a spec-driven AI development workflow engine with multi-service local runtime orchestration.

It now supports a practical loop from idea to runnable fullstack project:
`idea -> generation -> validation -> run -> inspect -> evolve`

## Major Milestone in v0.8.0

ArchMind now supports:

- fullstack runtime orchestration
- backend + frontend local execution
- `/run all` for multi-service startup
- `/restart`, `/stop`, `/stop all`
- `/running` unified runtime view
- `/logs backend` and `/logs frontend`
- `runtime.services`-based runtime state model
- consistent `RUNNING` / `STOPPED` / `FAIL` reporting
- GitHub repository creation tracked separately from runtime completion

## v0.8.0 Key Changes

### Runtime orchestration
- backend + frontend service lifecycle management
- `/run all`, `/restart`, `/stop`, `/stop all`
- `/running`, `/logs backend`, `/logs frontend`

### Runtime state model
- `runtime.services.backend` and `runtime.services.frontend`
- clear separation of `RUNNING`, `STOPPED`, and `FAIL`
- improved `/inspect`, `/running`, and `/logs` consistency

### GitHub repository flow
- scaffold generation and GitHub repo creation are decoupled from final runtime status
- repository state is tracked separately from deploy/runtime state

### v0.7 strengths retained
- preflight checks before execution
- auto-fix (self-healing runtime retry)
- local backend execution with health check
- auto-run after `/idea_local`

## Core Workflow

- idea to project generation
- structure validation
- runtime detection
- backend/frontend execution
- health and logs inspection
- restart and stop operations
- inspect, improve, and next-step evolution

## Key Commands

- `/idea_local <idea>`
- `/inspect`
- `/next`
- `/improve`
- `/run backend`
- `/run all`
- `/running`
- `/restart`
- `/stop`
- `/stop all`
- `/logs backend`
- `/logs frontend`

## What v0.8.0 Means

ArchMind can now generate and orchestrate fullstack projects locally with unified multi-service runtime control.

## Offline Install

For offline environments, ArchMind supports installation using a bundled dependency archive such as `wheelhouse.zip`.
You can verify offline installation with `scripts/offline_install_verify.sh`.

## Next

- stronger spec/primitive evolution
- local/cloud/hybrid provider layer
- basic web UI dashboard
