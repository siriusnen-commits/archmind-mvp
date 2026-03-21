# ArchMind v1.0.0

ArchMind is a practical:
- spec-driven AI development engine
- runtime orchestration tool
- multi-provider reasoning system
- lightweight web dashboard

It supports a working loop from idea to runnable and evolvable project:
`idea -> generation -> validation -> run -> inspect -> evolve`

## v1.0.0 Highlights

- Multi-provider reasoning with `local` / `cloud` / `auto` modes and fallback-oriented operation.
- Provider control in Telegram flows with visibility in inspection/status surfaces.
- Web dashboard MVP for projects, runtime/spec/provider state, and recent evolution.
- Next.js same-origin proxy UI architecture (`/api/ui/*`) so browsers only access the frontend origin.
- Spec progression and recent evolution tracking retained across iterative changes.

## Major Capabilities

- Project generation and iteration from an idea.
- Progression-aware loop with `/inspect`, `/next`, `/improve`.
- Primitive evolution commands:
  - `/add_entity <name>`
  - `/add_field <Entity> <field:type>`
  - `/add_api <METHOD> <path>`
  - `/add_page <path>`
- Runtime orchestration for local backend/frontend lifecycle:
  - `/run backend`, `/run all`, `/running`, `/restart`, `/stop`, `/stop all`, `/logs`
- Provider control:
  - `/provider` based mode control (`local` / `cloud` / `auto`)
- Dashboard MVP:
  - project list/detail
  - runtime/spec/provider/evolution views
  - provider mode update from UI
  - current project visibility

## Dashboard Architecture (MVP)

- Frontend: Next.js App Router (`frontend/`)
- Browser-facing API path: `/api/ui/*` on the Next.js server
- Proxy target (server-side only): `ARCHMIND_UI_API_BASE` or `http://127.0.0.1:8010/ui`
- Backend UI API routes:
  - `/ui/projects`
  - `/ui/projects/{project}`
  - `/ui/projects/{project}/provider` (GET/POST)

This same-origin proxy layout avoids requiring end-user browsers to connect directly to backend port `8010`.

## Practical Access Modes

- Local/LAN dashboard access:
  - Example: `http://192.168.0.197:3000/dashboard`
- Optional remote access:
  - Tailscale-based access to the same dashboard endpoint on the host network

## Current Limitations (Intentional for v1.0.0)

- Dashboard is MVP and read-mostly plus targeted provider control updates.
- Authentication/authorization is not implemented yet.
- Realtime streaming/live push updates are not implemented yet.

## Core Workflow

- Generate from idea (`/idea` or `/idea_local`)
- Validate and run services
- Inspect status/spec progress (`/inspect`)
- Get next actions (`/next`) and corrections (`/improve`)
- Evolve spec primitives (`/add_entity`, `/add_field`, `/add_api`, `/add_page`)
- Re-run and iterate

## Key Commands

- `/idea <idea>`
- `/idea_local <idea>`
- `/inspect`
- `/next`
- `/improve`
- `/add_entity <name>`
- `/add_field <Entity> <field:type>`
- `/add_api <METHOD> <path>`
- `/add_page <path>`
- `/provider`
- `/run backend`
- `/run all`
- `/running`
- `/restart`
- `/stop`
- `/stop all`
- `/logs`

## Offline Install

For offline environments, ArchMind supports installation using bundled dependencies (for example `wheelhouse.zip` workflows).
You can verify offline installation with `scripts/offline_install_verify.sh`.
