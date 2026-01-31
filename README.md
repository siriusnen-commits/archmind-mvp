# ArchMind v0.2.0

ArchMind is a CLI that generates runnable project scaffolds, then runs and fixes them with a repeatable pipeline. Use it to validate templates or existing codebases fast, with structured logs and minimal setup.

## What it does / What it doesn’t

What it does:
- Generates deterministic project skeletons from an idea
- Runs backend and/or frontend checks with clear summaries
- Creates fix plans and applies patches when explicitly allowed
- Produces repeatable logs and artifacts under `.archmind/`

What it doesn’t:
- Replace code review or product design decisions
- Modify files unless `--apply` is provided
- Run frontend checks without Node.js/npm installed
- Guarantee OpenAI API availability or quota

## Quick Start

One command pipeline (fullstack-ddd + Ollama for fixes + apply changes):
```bash
python -m pip install -e ".[dev]"
archmind pipeline --idea "issue tracker" --template fullstack-ddd --out /tmp --name issue_tracker --backend-only --model ollama --apply
cat /tmp/issue_tracker/.archmind/result.txt
```

Notes:
- OpenAI API usage (when `--model openai`) may require active billing/quota.
- If you use Ollama, ensure it is running and reachable before invoking `--model ollama`.

## CLI overview

Generate:
```bash
archmind generate --idea "defect tracker" --template fullstack-ddd --out /tmp --name defect_demo
```

Run:
```bash
archmind run --path /tmp/defect_demo --backend-only
```

Fix (plan only vs apply):
```bash
archmind fix --path /tmp/defect_demo --scope backend --dry-run
archmind fix --path /tmp/defect_demo --scope backend --apply
```

Pipeline:
```bash
archmind pipeline --path /tmp/defect_demo --backend-only --max-iterations 1 --model none
```

## Output Artifacts (.archmind/ structure)

Typical outputs created inside the project directory:
- `.archmind/run_logs/`
  - `run_YYYYMMDD_HHMMSS.log` and `run_YYYYMMDD_HHMMSS.summary.txt`
  - `run_YYYYMMDD_HHMMSS.summary.json` (when `--json-summary`)
  - `YYYYMMDD_HHMMSS.prompt.md` (only on run failure)
  - `fix_YYYYMMDD_HHMMSS.plan.md` / `fix_YYYYMMDD_HHMMSS.plan.json`
  - `fix_YYYYMMDD_HHMMSS.patch.diff`
  - `fix_YYYYMMDD_HHMMSS.summary.txt` / `fix_YYYYMMDD_HHMMSS.summary.json`
- `.archmind/pipeline_logs/`
  - `pipeline_YYYYMMDD_HHMMSS.log`
  - `pipeline_YYYYMMDD_HHMMSS.summary.txt`
  - `pipeline_YYYYMMDD_HHMMSS.summary.json` (when `--json-summary`)
- `.archmind/result.txt` and `.archmind/result.json` (pipeline results)
- `.archmind/patch_backups/` (timestamped backups for applied patches)

## Offline install / wheelhouse verification

Wheelhouse must be built on an online machine, then copied to the offline machine.
If you distribute a single archive, name it `wheelhouse.zip` and include `wheelhouse/` plus `dist/archmind-*.whl`.

Build wheelhouse (online machine):
```bash
./scripts/make_wheelhouse.sh --clean
```

Offline install (offline machine):
```bash
./scripts/offline_install.sh
```

Verify offline wheelhouse (offline machine):
```bash
./scripts/offline_install_verify.sh --wheelhouse wheelhouse
```

## Troubleshooting (top 5)

1) CORS/origin mismatch (frontend fetch fails)
- Symptom: CORS error or network error when UI calls the API
- Fix: Use the backend host as `127.0.0.1` and align CORS `ALLOW_ORIGINS`

2) Missing FastAPI dependencies in project venv
- Symptom: `ModuleNotFoundError: fastapi` (or `sqlmodel`) during pytest
- Fix: `python -m pip install -e ".[dev]"`

3) Node.js/npm missing (frontend checks skipped or fail)
- Symptom: frontend status SKIPPED/FAIL in run summary
- Fix: Install Node.js + npm, then rerun `archmind run --path ... --all`

4) printf dash issue in release notes
- Symptom: `printf: illegal option --` when printing lines that start with `-`
- Fix: Use `printf -- "%s\n" "- item"` or add `--` to stop option parsing

5) OpenAI insufficient_quota
- Symptom: OpenAI errors indicating `insufficient_quota`
- Fix: Confirm billing/quota, or use `--model ollama` or `--model none`

## Release (maintainers)

Checklist:
- `python -m pytest -q`
- `python -m build`
- `python -m twine check dist/*`
- `git tag v0.2.0 && git push --tags`
- artifacts 확인
