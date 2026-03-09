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

## Install (Quick)

```bash
pip install archmind
# Generate → run → fix → run (one command)
archmind pipeline \
  --idea "defect tracker ui with search filter sort pagination" \
  --template fullstack-ddd \
  --apply
```
Offline? See Offline install (wheelhouse) below.

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

## Profiles

ArchMind can run standardized profiles to act as a general automation runner.

Examples:
```bash
archmind run --path <proj> --profile python-pytest
archmind run --path <proj> --profile node-vite
archmind run --path <proj> --profile generic --cmd "make lint" --cmd "make test"
```

Priority rules (when mixed with legacy flags):
- If `--profile` is set, profile execution wins.
- `--backend-only/--frontend-only/--all` are ignored in profile mode.
- Without `--profile`, legacy flags behave as before.
- `--profile generic-shell` requires at least one `--cmd`.
- `--no-install` still applies to `node-vite`.

Fix (plan only vs apply):
```bash
archmind fix --path /tmp/defect_demo --scope backend --dry-run
archmind fix --path /tmp/defect_demo --scope backend --apply
```

Pipeline:
```bash
archmind pipeline --path /tmp/defect_demo --backend-only --max-iterations 1 --model none
```

Plan:
```bash
archmind plan --idea "stabilize failing tests and define fix steps" --path /tmp/defect_demo
cat /tmp/defect_demo/.archmind/plan.md
cat /tmp/defect_demo/.archmind/plan.json
```
- `plan.md`: 목표/범위, 작업 단계, 테스트 전략, Done 정의 (20~60줄)
- `plan.json`: `steps`, `risks`, `acceptance` 기반 구조화 산출물
- `pipeline` 실행 시 현재 프로젝트의 `.archmind/plan.*`가 자동 생성/갱신됨

Tasks:
```bash
archmind tasks --path myproj
archmind next --path myproj
archmind complete --path myproj --id 1
```
- `.archmind/tasks.json` 에 `todo/doing/done/blocked` 상태의 task queue를 저장
- `archmind tasks` 는 tasks가 없으면 `plan.json` 또는 `plan.md`에서 초기 task를 생성
- `archmind next` 는 첫 `todo`를 출력하고 없으면 `no pending tasks`를 출력
- `archmind complete` 는 기본 `done`, `--doing`, `--blocked` 상태 전환 지원

Evaluate:
```bash
archmind evaluate --path myproj
```
- `.archmind/evaluation.json` 에 `DONE/NOT_DONE/BLOCKED` 판정을 저장
- 입력 소스: `tasks.json`, 최신 `result.json`(또는 run summary), `plan.json/plan.md`
- `DONE`: tasks 완료 + 최근 실행 성공 + acceptance 정의됨
- `NOT_DONE`: pending task 존재 또는 최근 실행 실패/누락
- `BLOCKED`: 모든 task가 `blocked` 상태
- `pipeline` 종료 시 evaluate가 자동 실행되어 result에 요약 포함

State:
```bash
archmind state --path myproj
```
- `.archmind/state.json` 은 반복 실행의 메모리 계층으로 동작한다.
- 저장 항목: `iterations`, `current_task_id`, `last_action`, `last_status`, `recent_failures`, `history`.
- `run/fix/evaluate/complete/pipeline` 실행 시 자동 갱신되어 현재 진행 상황을 복원 가능하게 유지한다.
- `history` 는 최근 20개 이벤트만, `recent_failures` 는 최근 10개만 유지한다.
- fix prompt에는 state 요약(현재 task, 최근 실패, last_status)이 함께 포함된다.

Telegram integration (MVP):
- BotFather에서 Telegram 봇을 만들고 `TELEGRAM_BOT_TOKEN` 발급
- 환경변수 설정:
  `export TELEGRAM_BOT_TOKEN=...`
  `export ARCHMIND_BASE_DIR=~/archmind-telegram-projects` (선택)
  `export ARCHMIND_DEFAULT_TEMPLATE=fullstack-ddd` (선택)
- 실행:
  `python scripts/telegram_bot.py`
- 지원 명령:
  `/idea <text>`, `/pipeline <text>`, `/continue`, `/fix`, `/retry`, `/logs [backend|frontend|last]`, `/state`, `/help`
- `/idea` 와 `/pipeline` 은 백그라운드로 `archmind pipeline ... --apply` 실행
- `/continue` 는 마지막 프로젝트에 대해 `archmind pipeline --path <last_project>` 재실행
- `/fix` 는 마지막 프로젝트에 대해 `archmind fix --path <last_project> --apply` 실행
- `/retry` 는 실패 복구 루프를 한 번에 실행:
  `archmind fix --path <last_project> --apply` 후 `archmind pipeline --path <last_project>`
- `/retry` 시작 시 프로젝트가 이미 `DONE/SUCCESS` 상태면 실행하지 않고 완료 안내 메시지를 반환
- `STUCK` 상태에서는 경고를 보여주되 `/retry` 실행은 허용
- `/logs backend` 는 최근 backend 실패 로그(pytest/traceback 요약)를 보여줌
- `/logs frontend` 는 최근 frontend 실패 로그(lint/build 요약)를 보여줌
- `/logs last` 는 최신 run summary/log 기반 최근 실패 로그를 보여줌
- 실패 후 Telegram에서 바로 `/continue` 또는 `/fix`로 복구 루프를 이어갈 수 있음
- pipeline 종료 후 완료/실패 요약 메시지를 Telegram으로 자동 전송
- 자동 요약에는 status, iterations, current task, result/state 요약이 포함
- current task는 `failure_signature`를 기반으로 사람이 읽기 쉬운 라벨로 보정될 수 있음
  (예: `backend pytest failure 분석`, `frontend lint failure 수정`)
- 특히 `STUCK` 상태에서는 failure 기반 current task 라벨을 우선 표시
- 완료 메시지에는 `Next:` 추천 액션(예: `/fix`, `/continue`)이 함께 포함됨
- 기본 finished 메시지는 핵심 상태/요약/다음 액션 중심이며 raw command 문자열은 숨김
- finished 메시지는 내부 state dump/project 절대경로 대신 프로젝트 이름과 핵심 상태만 표시
- finished 메시지는 짧게 유지하고, 자세한 실패 근거는 `/logs`로 확인하는 흐름을 권장
- 상세 로그와 내부 결과는 `<project>/.archmind/result.json`, `state.json`, `evaluation.json`에서 확인
- Telegram 알림은 빠른 의사결정용 요약이며, 디버깅은 `.archmind` 아티팩트 기준으로 진행
- 반복 실패가 누적되면 상태를 `STUCK`으로 승격해 사람이 개입할 시점을 명확히 표시
- `STUCK`은 자동 반복만으로 돌파가 어려운 상태를 의미하며 failure details 검토가 필요
- `STUCK`일 때는 `/state`로 원인 확인 후 task/plan을 조정한 뒤 `/fix` 또는 `/continue` 권장
- fix 단계는 failure class 기반으로 수리 전략을 다르게 선택함
  (예: `backend-pytest:assertion`, `backend-pytest:module-not-found`, `frontend-lint`, `frontend-typescript`)
- backend assertion 실패는 구현 수정 중심, import/module 실패는 의존성/경로 해결 중심으로 유도
- frontend lint/typescript/build 실패는 각 목적(린트 통과/타입 안정성/build 복구)에 맞춰 prompt를 분기
- state에는 `last_failure_class`, `last_fix_strategy`, fix 전/후 failure signature가 기록됨
- 생성 로그는 우선 `<base_dir>/<project_name>.telegram.log` 임시 로그로 기록
- 마지막 프로젝트 경로는 `~/.archmind_telegram_last_project` 로 관리
- `/state` 는 마지막 프로젝트를 수동 확인할 때 사용하는 명령

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
- `.archmind/result.txt` and `.archmind/result.json` (latest run/pipeline results)
- `.archmind/state.json` (iterative execution memory snapshot)
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
