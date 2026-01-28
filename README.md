# ArchMind

## Quickstart
```bash
python -m pip install -e ".[dev]"
archmind generate --idea "defect tracker" --template fullstack-ddd --out /tmp --name defect_demo
archmind pipeline --path /tmp/defect_demo --backend-only --model none
ls /tmp/defect_demo/.archmind/run_logs
cat /tmp/defect_demo/.archmind/result.txt
```

## What is ArchMind?
ArchMind is a CLI tool that generates runnable project skeletons and then validates/fixes them with a repeatable run -> fix loop.

Core capabilities:
- Deterministic templates (fastapi-ddd, fullstack-ddd) for predictable outputs
- CLI pipeline to generate -> run -> fix -> run
- Structured run logs and failure prompts to speed up debugging
- Backend and frontend checks with per-step summaries
- Safe file writing and patch backups during fixes

## Who is it for?
- QA/validation automation teams who need repeatable runnable scaffolds
- Individual developers bootstrapping APIs or fullstack prototypes
- Teams validating legacy projects with consistent test/log output
- Tooling engineers building CI-friendly generation pipelines

## Features
- generate: Create a project skeleton from an idea, with deterministic templates available.
- run: Execute backend pytest and frontend lint/test/build with summarized logs.
- fix: Rule-based auto-fix loop that writes plans and prompts before applying changes.
- pipeline: One-command generate -> run -> fix -> run workflow with logs.

## Installation
Recommended (dev + test dependencies):
```bash
python -m pip install -e ".[dev]"
```

Dev install + tests:
```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Local LLM (Ollama) prerequisites:
- Needed only for the non-deterministic template (`fastapi`).
- Ensure Ollama is running at `http://127.0.0.1:11434` (default).

Node.js requirement:
- Required when running frontend checks (`archmind run --all` or `--frontend-only`).
- `npm` is used for `npm ci`/`npm install` and `npm run lint/test/build`.

## Quick Start (30 seconds)

A) Generate + pipeline for a fullstack template (deterministic, no Ollama required)
```bash
archmind pipeline --idea "defect tracker ui" \
  --template fullstack-ddd \
  --out /tmp \
  --name defect_demo \
  --backend-only \
  --max-iterations 1 \
  --model none
```

B) Run/fix/pipeline against an existing project
```bash
# run only backend tests
archmind run --path /path/to/project --backend-only

# plan fixes without applying
archmind fix --path /path/to/project --scope backend --dry-run

# full pipeline on an existing project
archmind pipeline --path /path/to/project --backend-only --max-iterations 1 --model none
```

## Commands

### `archmind generate ...`
When to use: Create a new project from an idea.
Representative options:
- `--template {fastapi,fastapi-ddd,fullstack-ddd}`
- `--model` and `--ollama-base-url` (used by `fastapi` template)
- `--out`, `--name`, `--force`
Example:
```bash
archmind generate --idea "defect tracker" --template fullstack-ddd --out /tmp --name defect_demo
```

### `archmind run ...`
When to use: Run backend pytest and/or frontend checks for an existing project.
Representative options:
- `--all` / `--backend-only` / `--frontend-only`
- `--no-install` (skip npm install)
- `--timeout-s`, `--log-dir`, `--json-summary`
Example:
```bash
archmind run --path /tmp/defect_demo --backend-only
```

### `archmind fix ...`
When to use: Generate a fix plan and optionally apply rule-based patches.
Representative options:
- `--scope {backend,frontend,all}`
- `--dry-run` (plan only, no changes)
- `--apply` (required to modify files)
Example:
```bash
archmind fix --path /tmp/defect_demo --scope backend --apply
```

### `archmind pipeline ...`
When to use: End-to-end workflow (generate -> run -> fix -> run).
Representative options:
- `--idea` or `--path`
- `--template`, `--gen-model`, `--gen-ollama-base-url`
- `--backend-only` / `--frontend-only` / `--all`
- `--model {ollama,openai,none}` (fix stage)
- `--apply`, `--dry-run`
Example:
```bash
archmind pipeline --idea "defect tracker" --template fullstack-ddd --backend-only --max-iterations 1 --model none
```

## Output / Logs
ArchMind writes logs under the project directory:

- `.archmind/run_logs/`
  - `run_YYYYMMDD_HHMMSS.log` : full stdout/stderr
  - `run_YYYYMMDD_HHMMSS.summary.txt` : human-readable summary
  - `run_YYYYMMDD_HHMMSS.summary.json` : machine-readable summary (`--json-summary`)
  - `YYYYMMDD_HHMMSS.prompt.md` : failure prompt (only on run failure)

- `.archmind/run_logs/` (fix-related)
  - `fix_YYYYMMDD_HHMMSS.plan.json` / `fix_YYYYMMDD_HHMMSS.plan.md`
  - `fix_YYYYMMDD_HHMMSS.prompt.md`
  - `fix_YYYYMMDD_HHMMSS.summary.txt` / `fix_YYYYMMDD_HHMMSS.summary.json`
  - `fix_YYYYMMDD_HHMMSS.patch.diff`

- `.archmind/pipeline_logs/`
  - `pipeline_YYYYMMDD_HHMMSS.log`
  - `pipeline_YYYYMMDD_HHMMSS.summary.txt`
  - `pipeline_YYYYMMDD_HHMMSS.summary.json` (with `--json-summary`)

Failure prompt (`*.prompt.md`) includes:
- 재현 커맨드
- 실패 요약
- 실패 지점(테스트 이름/파일/스택)
- 수정 지시문
- 완료 조건 체크리스트

Result files quick check (2 examples):
```bash
archmind pipeline --path /path/to/project --backend-only --model none
cat /path/to/project/.archmind/result.txt
archmind pipeline --idea "demo" --template fullstack-ddd --out /tmp --name demo --backend-only --model none
cat /tmp/demo/.archmind/result.json
```

## Troubleshooting
1) CORS/0.0.0.0 vs 127.0.0.1
- Symptom: frontend fetch fails with CORS or network error.
- Fix: Use `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000` or set backend CORS `ALLOW_ORIGINS`.

2) FastAPI/SQLModel 미설치로 테스트 수집 실패
- Symptom: `ModuleNotFoundError: fastapi/sqlmodel` during pytest.
- Fix: `python -m pip install -e ".[dev]"`

3) node/npm 없음으로 frontend 단계 실패 또는 스킵
- Symptom: frontend status SKIPPED or FAIL in run summary.
- Fix: Install Node.js + npm, then rerun: `archmind run --path ... --all`

4) Ollama 모델/베이스 URL 문제
- Symptom: generate 단계에서 연결 실패.
- Fix: start Ollama at `http://127.0.0.1:11434` or pass `--ollama-base-url`.

5) 권한/경로 문제
- Symptom: cannot create `.archmind` or write logs.
- Fix: ensure project directory is writable, or use `--log-dir`.

6) “apply disabled” 의미
- Meaning: `archmind fix` or `pipeline` ran without `--apply`.
- Fix: rerun with `--apply` to allow file changes.

## Frontend auto-fix usage
- Use when `archmind run --all` fails at frontend lint/typecheck.
- Frontend scope only touches files under `frontend/`.
```bash
archmind run --path /path/to/project --all
archmind fix --path /path/to/project --scope frontend --model ollama --apply
archmind pipeline --path /path/to/project --all --scope all --max-iterations 2 --model ollama --apply
```
- Check `.archmind/run_logs/` for fix prompt/patch/summary.
- If no changes are applied, review the prompt and fix manually.

## Roadmap
- Improve rule-based fix coverage
- Add richer frontend checks
- Expand deterministic templates
- Optional OpenAI-based fix strategy
- CI-friendly preset commands

## Release (maintainers)
- Bump version in `pyproject.toml`
- `python -m build --no-isolation` (creates dist/*)
- `python -m twine check dist/*`
- `git tag vX.Y.Z`
- `git push origin vX.Y.Z`
- GitHub Actions builds sdist+wheel and uploads artifacts
- PyPI publish is disabled by default in `.github/workflows/release.yml`
- Enable by configuring Trusted Publisher or a PyPI token and uncommenting publish step

## Offline install (air-gapped)
- Step 1 (online machine): `./scripts/make_wheelhouse.sh`
- Optional dev extras: `./scripts/make_wheelhouse.sh --dev`
- This creates `wheelhouse/` and `dist/archmind-*.whl`
- Step 2: copy `wheelhouse/` and `dist/*.whl` to the offline machine
- Step 3 (offline machine): `./scripts/offline_install_verify.sh`
- The script installs with `--no-index --find-links wheelhouse`
- It verifies `archmind --version` and CLI help commands
- If you run make_wheelhouse.sh offline, failure is expected
- If dependencies change, regenerate the wheelhouse
- Use `--wheelhouse PATH` or `--keep` to customize output
- GitHub Releases/Actions also publish `wheelhouse.zip` (archmind wheel + runtime deps)
- Download and unzip `wheelhouse.zip`, then run:
  `./scripts/offline_install_verify.sh --wheelhouse <unzipped_path>`

## License
TBD
