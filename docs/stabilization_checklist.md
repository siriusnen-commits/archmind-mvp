# Stabilization Checklist

이 문서는 ArchMind의 기존 기능이 서로 일관되게 동작하는지 점검하기 위한 최소 체크리스트다.

## 공통 기준
- state/evaluation/result/Telegram 출력이 같은 상태를 말해야 한다.
- `iterations`, `fix_attempts`, `agent_state`, `last_status`, `next_action`이 상호 모순되지 않아야 한다.
- Telegram finished/state 메시지는 최신 디스크 아티팩트 기준으로 만들어져야 한다.

## 시나리오 1: module-not-found
- 기대 상태:
  - failure class: `backend-pytest:module-not-found`
  - repair targets에 `requirements.txt` 포함
  - relevant files에 `requirements.txt` + 관련 테스트/엔트리 파일 포함
  - 외부 경로(`.pyenv/.venv/site-packages`)는 제외

## 시나리오 2: backend assertion fail
- 기대 상태:
  - failure excerpt에 `AssertionError` + `FAILED ...` 핵심 라인 포함
  - repair targets/relevant files가 구현 파일 중심으로 선택
  - finished 메시지에 내부 메타(command/cwd/duration/timestamp) 노출 없음

## 시나리오 3: frontend lint fail
- 기대 상태:
  - excerpt/logs에 ESLint 핵심 라인 유지
  - interactive prompt noise(`Base/Cancel/Strict (recommended)`) 제거
  - relevant files가 frontend source + config/package 중심

## 시나리오 4: repeated failure -> STUCK
- 기대 상태:
  - evaluation/status가 `STUCK`
  - state `stuck`, `stuck_reason` 반영
  - `/state`와 finished 모두 `Next action: STUCK` 계열 권고 표시

## 시나리오 5: retry after fix
- 기대 상태:
  - `/retry`는 fix -> continue 순서 유지
  - state `fix_attempts`/`iterations`가 누적
  - watcher finished 메시지는 최신 state/evaluation 기준
