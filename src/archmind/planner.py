from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PlanArtifacts:
    plan_md_path: Path
    plan_json_path: Path


def _build_steps(scope_text: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "S1",
            "title": "현행 코드베이스 파악",
            "description": "핵심 엔트리포인트와 실패 로그를 확인해 수정 대상 범위를 고정한다.",
            "depends_on": [],
            "status": "todo",
            "verification": "재현 커맨드가 일관되게 실패/성공하는지 확인",
        },
        {
            "id": "S2",
            "title": "핵심 수정 구현",
            "description": f"우선순위 결함을 최소 변경으로 수정한다. (범위: {scope_text})",
            "depends_on": ["S1"],
            "status": "todo",
            "verification": "관련 테스트/검증 커맨드 통과",
        },
        {
            "id": "S3",
            "title": "회귀 검증",
            "description": "수정 범위 외 기능에 영향이 없는지 회귀를 점검한다.",
            "depends_on": ["S2"],
            "status": "todo",
            "verification": "python -m pytest -q 또는 프로파일 커맨드 통과",
        },
        {
            "id": "S4",
            "title": "결과 정리",
            "description": "변경 파일/리스크/남은 TODO를 기록하고 인수 기준 충족 여부를 판단한다.",
            "depends_on": ["S3"],
            "status": "todo",
            "verification": "acceptance 항목 모두 충족",
        },
    ]


def _build_plan_payload(project_dir: Path, idea: str) -> dict[str, Any]:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    normalized_idea = (idea or "").strip() or f"{project_dir.name} 안정화 및 개선"
    scope_text = "backend/frontend 및 테스트"
    steps = _build_steps(scope_text)
    risks = [
        {
            "id": "R1",
            "title": "수정 범위 확대",
            "impact": "불필요한 파일 변경으로 회귀 가능성 증가",
            "mitigation": "실패 지점 중심의 최소 수정 원칙 유지",
        },
        {
            "id": "R2",
            "title": "환경 의존 실패",
            "impact": "Node/Python 의존성 미설치로 검증 불가",
            "mitigation": "SKIP 원인 명시 및 재실행 조건 문서화",
        },
    ]
    acceptance = [
        "핵심 재현 커맨드가 통과한다.",
        "python -m pytest -q 또는 지정 프로파일 검증이 통과한다.",
        "변경 파일 수와 변경 라인은 문제 해결에 필요한 최소 범위다.",
        "실패 원인, 수정 내용, 남은 리스크가 .archmind 산출물에 기록된다.",
    ]
    return {
        "schema_version": "1.0",
        "created_at": created_at,
        "project_dir": str(project_dir),
        "idea": normalized_idea,
        "steps": steps,
        "risks": risks,
        "acceptance": acceptance,
    }


def _render_plan_md(payload: dict[str, Any]) -> str:
    steps = payload.get("steps", [])
    risks = payload.get("risks", [])
    acceptance = payload.get("acceptance", [])
    lines = [
        "# ArchMind Plan",
        "",
        "## 목표/범위",
        f"- 아이디어: {payload.get('idea', '')}",
        f"- 프로젝트: {payload.get('project_dir', '')}",
        f"- 생성 시각: {payload.get('created_at', '')}",
        "- 목표: 실패 재현을 안정화하고 최소 변경으로 성공 상태를 만든다.",
        "- 범위: 기능 수정, 테스트/검증, 결과 기록",
        "- 제외: 대규모 리팩터링, 요구사항 외 신규 기능 추가",
        "",
        "## 작업 단계",
    ]
    for step in steps:
        lines.append(f"1. [{step.get('id')}] {step.get('title')}")
        lines.append(f"   - 설명: {step.get('description')}")
        lines.append(f"   - 검증: {step.get('verification')}")
    lines += [
        "",
        "## 테스트 전략",
        "- 1차: 실패 재현 커맨드로 기준선 확인",
        "- 2차: 수정 후 동일 커맨드 재실행으로 개선 여부 확인",
        "- 3차: python -m pytest -q 또는 선택한 profile 검증",
        "- 4차: 실패 원인/스택트레이스가 제거되었는지 로그 확인",
        "",
        "## 리스크",
    ]
    for risk in risks:
        lines.append(f"- [{risk.get('id')}] {risk.get('title')}: {risk.get('impact')}")
        lines.append(f"  - 대응: {risk.get('mitigation')}")
    lines += [
        "",
        "## Done 정의",
    ]
    for item in acceptance:
        lines.append(f"- [ ] {item}")
    lines += [
        "",
        "## 메모",
        "- plan은 pipeline/fix 프롬프트에 요약되어 포함된다.",
        "- plan이 없으면 fix 프롬프트에 'plan missing'이 기록된다.",
    ]
    if len(lines) < 20:
        lines += ["- 추가 메모: 없음"] * (20 - len(lines))
    if len(lines) > 60:
        lines = lines[:60]
    return "\n".join(lines) + "\n"


def write_project_plan(project_dir: Path, idea: str) -> PlanArtifacts:
    project_dir = project_dir.expanduser().resolve()
    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    payload = _build_plan_payload(project_dir, idea)
    plan_json_path = archmind_dir / "plan.json"
    plan_md_path = archmind_dir / "plan.md"
    plan_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    plan_md_path.write_text(_render_plan_md(payload), encoding="utf-8")
    return PlanArtifacts(plan_md_path=plan_md_path, plan_json_path=plan_json_path)


def read_plan_summary(project_dir: Path, max_lines: int = 200) -> list[str]:
    plan_path = project_dir.expanduser().resolve() / ".archmind" / "plan.md"
    if not plan_path.exists():
        return ["plan missing"]
    lines = plan_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return ["plan missing"]
    return lines[:max_lines]
