# ArchMind v1.1.0

## What ArchMind Is

ArchMind is a practical:
- spec-driven AI development engine
- runtime orchestration tool
- multi-provider reasoning system
- lightweight web dashboard

It is built for iterative delivery from idea to runnable software:
`idea -> generation -> validation -> run -> inspect -> evolve`

## Core Capabilities

- Idea-to-project generation with deterministic template scaffolds.
- Spec progression loop with `/inspect`, `/next`, `/improve`.
- Primitive evolution operations:
  - `/add_entity <name>`
  - `/add_field <Entity> <field:type>`
  - `/add_api <METHOD> <path>`
  - `/add_page <path>`
- Runtime orchestration for local backend/frontend lifecycle:
  - `/run backend`, `/run all`, `/running`, `/restart`, `/stop`, `/stop all`, `/logs`
- Multi-provider control (`local` / `cloud` / `auto`) with inspect/status visibility.
- Web dashboard for project list/detail, runtime status, provider mode, spec summary, recent evolution.

## What Improved In v1.1.0

Compared to v1.0.0, v1.1.0 focuses on runtime and dashboard stability:

- Project-scoped frontend runtime:
  - frontend servers are isolated per project (no shared single frontend runtime illusion).
- Runtime URL visibility improved:
  - loopback + LAN + Tailscale URL expansion in dashboard/runtime surfaces.
- Generated frontend API resolution stabilized:
  - single shared runtime-aware API base hook used across generated pages.
  - remote-safe host replacement behavior improved.
  - runtime backend port propagation fixed so generated frontend follows actual runtime backend port.
- Hydration mismatch prevention:
  - generated frontend API base resolution moved to client-safe hook/effect flow.
- Generated backend interoperability:
  - generated FastAPI backends now include CORS middleware defaults for development access.
- Dashboard/UI API hardening:
  - resilient handling of malformed or partial project metadata.
- Safe project deletion added to Web UI with separated scopes:
  - Delete Local Project
  - Delete GitHub Repo
  - Delete Project + GitHub Repo (explicit danger action)

## Web UI / Runtime Management

Dashboard stack:
- Frontend: Next.js App Router (`frontend/`)
- Browser-facing API path: `/api/ui/*`
- Server-side proxy target: `ARCHMIND_UI_API_BASE` or `http://127.0.0.1:8010/ui`

UI API endpoints (current):
- `/ui/projects`
- `/ui/projects/{project}`
- `/ui/projects/{project}/provider` (GET/POST)
- `/ui/projects/{project}/run-backend` (POST)
- `/ui/projects/{project}/run-all` (POST)
- `/ui/projects/{project}/restart` (POST)
- `/ui/projects/{project}/stop` (POST)
- `/ui/projects/{project}/delete-local` (POST)
- `/ui/projects/{project}/delete-repo` (POST)
- `/ui/projects/{project}/delete-all` (POST)

Practical access modes:
- Local/LAN dashboard access (example: `http://<host-ip>:3000/dashboard`)
- Optional Tailscale remote access to the same dashboard endpoint

## Generated App Behavior

For generated fullstack projects:
- Frontend API base is resolved through a shared runtime-aware helper.
- Runtime backend URL/port propagation is respected.
- Remote browser access is supported with loopback-safe host rewrite logic.
- Generated FastAPI backend includes CORS middleware for development connectivity.

## Offline Install / Bundle

- ArchMind supports offline dependency installation using packaged bundles such as `wheelhouse.zip`.
- The `wheelhouse.zip` bundle is intended for environments without external network/package index access.
- Build/verify offline install assets with `scripts/make_wheelhouse.sh` and `scripts/offline_install_verify.sh`.
- Use the project offline install scripts/workflow to install from the bundled wheels.

## Current Limitations

- Dashboard is still evolving; it is internal-tool oriented, not a polished enterprise admin suite.
- Generated apps are MVP-level scaffolds and may need domain-specific hardening.
- Auth, realtime streaming, and production deployment workflows are not fully matured.
- Local runtime/dev workflow remains the primary operating mode.

## Development / Test Command

Use the full regression suite:

```bash
python -m pytest -vv -rA --maxfail=1
```

## Release Version Note

This README reflects `v1.1.0` release scope and post-v1.0.0 stabilization work.
