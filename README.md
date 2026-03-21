# ArchMind v0.9.0

ArchMind is a spec-driven AI development workflow engine with multi-service local runtime orchestration and primitive-based project evolution.

It now supports a practical loop from idea to runnable and evolvable fullstack project:
`idea -> generation -> validation -> run -> inspect -> evolve`

## Major Milestone in v0.9.0

ArchMind now supports:

- primitive-based project evolution with `/add_entity`, `/add_field`, `/add_api`, `/add_page`
- progression-aware `/inspect`, `/next`, and `/improve`
- Recent evolution visibility in `/inspect`
- multi-service local runtime orchestration retained and stabilized
- backend + frontend local execution
- `/run all`, `/restart`, `/stop`, `/stop all`
- `/running`, `/logs backend`, `/logs frontend`
- cleaned project operations and deletion handling

## v0.9.0 Key Changes

### Spec-driven evolution
- `/add_entity <name>`
- `/add_field <Entity> <field:type>`
- `/add_api <METHOD> <path>`
- `/add_page <path>`
- spec progression model (entity -> field -> api -> page)
- `/inspect`, `/next`, `/improve` aligned around progression stages

### Inspection and guidance
- Spec Summary in `/inspect`
- stage-based recommendations in `/next`
- actionable improvements in `/improve`
- Recent evolution section in `/inspect`

### Runtime orchestration retained
- backend + frontend service lifecycle management
- `/run all`, `/restart`, `/stop`, `/stop all`
- `/running`, `/logs backend`, `/logs frontend`
- `runtime.services`-based runtime state model
- consistent `RUNNING` / `STOPPED` / `FAIL` reporting

### Project operations
- GitHub repo creation/deletion state handling
- idempotent repo delete behavior for already-removed repositories
- cleaner `/projects` output and stale runtime/url suppression
- current selection cleanup after local project deletion

## Core Workflow

- idea -> project generation
- structure validation
- runtime detection
- backend/frontend execution
- inspect project state (runtime + spec)
- evolve spec with entities / fields / APIs / pages
- review next steps and improvements

## Key Commands

- `/idea_local <idea>`
- `/inspect`
- `/next`
- `/improve`
- `/add_entity <name>`
- `/add_field <Entity> <field:type>`
- `/add_api <METHOD> <path>`
- `/add_page <path>`
- `/run backend`
- `/run all`
- `/running`
- `/restart`
- `/stop`
- `/stop all`
- `/logs backend`
- `/logs frontend`

## What v0.9.0 Means

ArchMind can now evolve a project through spec primitives while keeping runtime orchestration and inspection consistent.

## Offline Install

For offline environments, ArchMind supports installation using a bundled dependency archive such as `wheelhouse.zip`.
You can verify offline installation with `scripts/offline_install_verify.sh`.

## Next

- local/cloud/hybrid provider layer
- basic web UI dashboard
- stronger provider-agnostic workflow
