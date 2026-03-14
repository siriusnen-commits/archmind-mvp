# ArchMind v0.4.0

ArchMind v0.4 introduces the Brain v1 architecture reasoning layer, target-based runtime/deploy abstraction, and a local runtime management workflow that enables idea-to-running-app development.

Idea → Architecture → Working Project

Current capabilities:
- idea → architecture reasoning
- idea → runnable project
- automatic GitHub repository creation
- local runtime management
- deploy target abstraction (`local` / `railway`)
- backend/frontend smoke verification

ArchMind is a CLI that generates runnable project scaffolds, then runs and fixes them with a repeatable pipeline. Use it to validate templates or existing codebases fast, with structured logs and minimal setup.

## What it does / What it doesn’t

What it does:
- Generates deterministic project skeletons from an idea
- Detects a baseline `project_type` from idea text before generation
- Runs backend and/or frontend checks with clear summaries
- Creates fix plans and applies patches when explicitly allowed
- Produces repeatable logs and artifacts under `.archmind/`

Idea routing notes:
- ArchMind now performs a lightweight heuristic classification on idea text.
- Supported baseline types: `backend-api`, `frontend-web`, `fullstack-web`, `cli-tool`, `automation-script`, `unknown`.
- Baseline routing now follows `idea -> project_type -> selected_template`.
- Routing traces `selected_template` and `effective_template` separately for transparency.
- `selected_template` is the baseline choice from `project_type`.
- `effective_template` is the template actually used for generation.
- `frontend-web` baseline now uses the supported `nextjs` template (no fallback to `fastapi`).
- Example routing: `frontend-web -> selected_template=nextjs -> effective_template=nextjs`.
- Unknown type falls back to `ARCHMIND_DEFAULT_TEMPLATE` (or built-in default).
- If `selected_template` is unsupported, fallback is applied and `template_fallback_reason` is recorded.
- Routing metadata is persisted in pipeline summaries, `result.json`, and `state.json`.
- Current scope is initial routing only; richer template matching is a follow-up layer.
- Next stage is template selection combined with LLM-assisted generation refinement.

FastAPI baseline scaffold:
- `fastapi` template now generates a pytest-ready backend baseline by default.
- Included out of the box: `app/main.py`, root `main.py`, `tests/test_health.py`, and `pytest.ini`.
- Baseline endpoint: `GET /health` returns `{"status": "ok"}`.
- `requirements.txt` includes runtime + minimal test deps for immediate validation.
- Result: backend-only projects can enter run/evaluate right after generation without "no tests" skip.

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

Deploy (phase 1, mock by default):
```bash
archmind deploy --path /tmp/defect_demo --target railway
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

Task completion rules:
- ArchMind는 evaluate 시점에 tasks를 자동 재평가해 `todo -> done`을 동기화한다.
- 기본 4단계(코드 파악/핵심 수정/회귀 검증/결과 정리)를 실행 결과 기반으로 자동 완료 처리한다.
- 코드 파악(task1): run/fix 실행 또는 failure classification/repair target 신호가 있으면 완료.
- 핵심 수정(task2): fix 시도 또는 `last_fix_strategy`/`last_repair_targets` 기록이 있으면 완료.
- 회귀 검증(task3): 최신 `result.status == SUCCESS` 또는 run/build checks가 SUCCESS면 완료.
- 결과 정리(task4): state/result/evaluation 아티팩트가 최신으로 갱신되면 완료.
- 자동 완료 결과는 `tasks.json`에 반영되고, `plan.json.steps[*].status`도 함께 동기화된다.
- evaluation은 동기화된 tasks 기준으로 `tasks_complete`를 계산한다.
- 따라서 run/build 성공 + acceptance 충족 + tasks_complete가 true면 `DONE`으로 닫힌다.

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

ArchMind Agent State Machine:
- 공식 상태: `IDLE`, `PLANNING`, `RUNNING`, `FIXING`, `RETRYING`, `NOT_DONE`, `STUCK`, `DONE`, `FAILED`
- `agent_state`는 현재 에이전트 phase/state를 나타내고, `last_status`는 최근 액션 결과를 나타낸다.
- `evaluation.status`는 완료 판정(`DONE/NOT_DONE/STUCK/BLOCKED`)에 집중하고, finished 메시지는 이를 우선 표시한다.
- `/state` 출력은 `agent_state + last_status + iterations + fix_attempts`를 함께 보여준다.
- 주요 전이:
  `/idea`: `IDLE -> PLANNING -> RUNNING`
- run/pipeline 성공 후 evaluate가 완료 조건을 만족하면:
  `RUNNING -> DONE`
- run/pipeline 실패 또는 추가 작업 필요:
  `RUNNING -> NOT_DONE`
- `/fix`:
  `NOT_DONE/STUCK -> FIXING -> NOT_DONE` (반복 실패 시 evaluate에서 `STUCK`)
- `/continue`:
  `NOT_DONE/STUCK -> RUNNING -> DONE/NOT_DONE/STUCK`
- `/retry`:
  `NOT_DONE/STUCK -> RETRYING -> FIXING -> RUNNING -> DONE/NOT_DONE/STUCK`
- 반복 동일 실패(서명 반복 + 동일 task + iteration 임계치) 감지 시:
  `NOT_DONE -> STUCK`
- 치명적 예외가 발생하면:
  `* -> FAILED` (복구 전까지 수동 개입 필요)

Action Decision Layer:
- ArchMind는 state/evaluation/result를 함께 읽어 다음 행동을 추론한다.
- 공식 next action: `DONE`, `FIX`, `RUN`, `RETRY`, `STUCK`, `STOP`
- `DONE`: 완료 판정이 확정되어 추가 자동 작업이 불필요한 상태
- `STUCK`: 반복 실패로 자동 루프보다 사람 개입이 우선인 상태
- `FIX`: 최신 run 실패가 있고 아직 fix 시도가 충분하지 않은 상태
- `RUN`: fix 이후 재검증(run/pipeline)이 필요한 상태
- `RETRY`: fix+run 루프를 한 번 더 돌릴 가치가 있는 상태
- `STOP`: 신호가 부족하거나 자동 진행 의미가 낮은 상태
- 기본 규칙:
  - `evaluation.status == DONE` -> `DONE`
  - `state.stuck` 또는 `evaluation.status == STUCK` -> `STUCK`
  - run 실패 + not stuck -> `FIX`
  - fix 전/후 failure signature 변경 -> `RUN`
  - fix 전/후 failure signature 동일 -> `RETRY` (임계 반복 시 `STUCK`)
  - 판단 신호 부족 -> `STOP`
- state.json에는 `next_action`, `next_action_reason`이 기록된다.
- `/state` 출력과 Telegram finished `Next:` 추천은 같은 decision 로직을 공유한다.

Stabilization:
- 신규 기능 추가 전, `docs/stabilization_checklist.md`의 시나리오를 우선 점검한다.
- 핵심 회귀 포인트: state/evaluation/result/Telegram 일관성, fix prompt 품질, relevant file safety.
- 특히 module-not-found, backend assertion, frontend lint, repeated failure(STUCK), retry 루프를 반복 검증한다.

Environment Readiness / Bootstrap:
- ArchMind는 코드 수정 전에 환경/설정 이슈를 감지하는 readiness check를 수행한다.
- 감지되는 이슈 예:
  - `backend-dependency-missing`
  - `frontend-eslint-bootstrap-needed`
  - `frontend-config-missing`
  - `env-readiness-ok`
- `frontend-eslint-bootstrap-needed`일 때는 안전한 bootstrap으로 `frontend/.eslintrc.json`을 자동 생성할 수 있다.
- 생성 기본값:
  `{ "extends": ["next/core-web-vitals", "next/typescript"] }`
- 기존 config 파일이 있으면 덮어쓰지 않는다.
- `backend-dependency-missing`은 기본적으로 자동 설치를 하지 않고 guidance/상태 기록 중심으로 처리한다.
- 위험한 자동화(`pip install`, `npm install`)는 기본 경로에서 수행하지 않는다.
- readiness 결과는 state에 기록된다:
  - `environment_issue`
  - `environment_issue_reason`
  - `last_bootstrap_actions`
- `/state` 출력에서 환경 이슈와 bootstrap actions를 함께 확인할 수 있다.

Telegram integration (MVP):
- BotFather에서 Telegram 봇을 만들고 `TELEGRAM_BOT_TOKEN` 발급
- 환경변수 설정:
  `export TELEGRAM_BOT_TOKEN=...`
  `export ARCHMIND_BASE_DIR=~/archmind-telegram-projects` (선택)
  `export ARCHMIND_DEFAULT_TEMPLATE=fullstack-ddd` (선택)
- 실행:
  `python scripts/telegram_bot.py`
- 지원 명령:
  `/idea <text>`, `/pipeline <text>`, `/continue`, `/fix`, `/retry`, `/deploy [target]`, `/logs [backend|frontend|last]`, `/state`, `/help`
- `/idea` 와 `/pipeline` 은 백그라운드로 `archmind pipeline ... --apply` 실행
- `/continue` 는 마지막 프로젝트에 대해 `archmind pipeline --path <last_project>` 재실행
- `/fix` 는 마지막 프로젝트에 대해 `archmind fix --path <last_project> --apply` 실행
- `/retry` 는 실패 복구 루프를 한 번에 실행:
  `archmind fix --path <last_project> --apply` 후 `archmind pipeline --path <last_project>`
- `/deploy` 는 현재 선택된 프로젝트를 deploy target(phase 1: `railway`)에 대해 실행
  - 기본은 mock 모드(실제 배포 없음)
  - 결과는 `state.json`의 deploy 필드에 기록
- 상태 카운팅 규칙:
  `iterations` 는 run/pipeline 사이클 횟수, `fix_attempts` 는 fix 실행 횟수로 분리 추적
- `/fix` 는 `fix_attempts`만 증가시키고, `/continue` 는 `iterations`를 증가시킴
- `/retry` 는 내부적으로 `fix_attempts` +1 과 `iterations` +1 이 함께 반영됨
- state 로드/저장 시 `history`의 fix action 횟수와 top-level `fix_attempts`를 자동 보정해 불일치를 줄임
- finished 메시지와 `/state` 출력은 보정된 최신 state 기준 `Fix attempts`를 표시
- `/retry` 시작 시 프로젝트가 이미 `DONE/SUCCESS` 상태면 실행하지 않고 완료 안내 메시지를 반환
- `STUCK` 상태에서는 경고를 보여주되 `/retry` 실행은 허용
- `/logs backend` 는 최근 backend 실패 로그(pytest/traceback 요약)를 보여줌
- `/logs frontend` 는 최근 frontend 실패 로그(lint/build 요약)를 보여줌
- `/logs last` 는 최신 run summary/log 기반 최근 실패 로그를 보여줌
- `/logs` 출력은 메타 정보 나열보다 핵심 에러 라인과 디버깅 포커스를 우선 표시
- 출력 구조: `Failure`, `Key lines`, `Focus` (짧고 바로 행동 가능한 형태)
- `project_dir/timestamp/command/cwd/duration` 같은 내부 메타는 기본 `/logs` 출력에서 숨김
- 전체 raw 로그가 필요하면 `<project>/.archmind/run_logs/*` 파일에서 직접 확인
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
- `Status: DONE`일 때 Summary는 사용자용 성공 요약(예: Backend/Frontend 상태, tasks 완료, evaluation 완료) 위주로 표시
- DONE 메시지에서는 `run_summary`, `run_prompt`, `fix_prompt`, `.archmind/...` 같은 내부 경로를 기본 출력에서 숨김
- 상세 artifact 경로는 내부 result/state 파일에 유지되며 디버깅 시 `.archmind` 아티팩트에서 확인 가능
- 상세 로그와 내부 결과는 `<project>/.archmind/result.json`, `state.json`, `evaluation.json`에서 확인
- Telegram 알림은 빠른 의사결정용 요약이며, 디버깅은 `.archmind` 아티팩트 기준으로 진행
- 반복 실패가 누적되면 상태를 `STUCK`으로 승격해 사람이 개입할 시점을 명확히 표시
- `STUCK`은 자동 반복만으로 돌파가 어려운 상태를 의미하며 failure details 검토가 필요
- `STUCK`일 때는 `/state`로 원인 확인 후 task/plan을 조정한 뒤 `/fix` 또는 `/continue` 권장
- fix 단계는 failure class 기반으로 수리 전략을 다르게 선택함
  (예: `backend-pytest:assertion`, `backend-pytest:module-not-found`, `frontend-lint`, `frontend-typescript`)
- backend assertion 실패는 구현 수정 중심, import/module 실패는 의존성/경로 해결 중심으로 유도
- frontend lint/typescript/build 실패는 각 목적(린트 통과/타입 안정성/build 복구)에 맞춰 prompt를 분기
- fix prompt는 failure class와 함께 `Repair targets`를 계산해 우선 수정 대상을 명시함
- dependency/import 계열(`module-not-found`, `env-dependency`)은 코드보다 `requirements.txt`/`package.json`/config를 먼저 점검
- backend assertion 계열은 테스트 파일보다 구현 파일(endpoint/service/serializer)을 우선 대상으로 선택
- repair target 선택은 project-local 파일을 기본 원칙으로 하며, 시스템/외부 경로는 제외함
- fix prompt는 `Relevant Files` 섹션으로 실패와 직접 관련된 파일(기본 2~4개)만 선별해 전달함
- 우선순위는 repair targets -> 실패 excerpt에서 언급된 파일 -> failure class별 엔트리포인트/설정 파일 순서
- local model(예: LLaMA)에서도 전체 코드보다 관련 파일만 좁혀 주는 것이 fix 성공률에 유리함
- `.venv/.pyenv/site-packages/usr/lib/opt/homebrew` 등 외부 런타임 파일은 수정 대상으로 잡지 않음
- failure excerpt는 Traceback 메타보다 핵심 에러 본문(`ModuleNotFoundError`, `AssertionError` 등)을 우선 압축해 제공
- Failure Excerpt는 핵심 에러 본문 1~3줄 + 실패 파일/테스트 라인 중심으로 압축됨
- backend primary failure에서는 frontend lint/interactive prompt 노이즈를 제거하고, frontend primary failure에서는 backend traceback 노이즈를 제거함
- fix prompt의 `실패 지점` 섹션도 primary failure 기준으로 정리됨
- backend 실패 시 backend traceback/context만, frontend 실패 시 frontend lint/TS/build context만 남김
- irrelevant backend/frontend noise(ESLint interactive prompt, short test summary info 등)는 제거됨
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
