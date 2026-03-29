from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from archmind.execution_history import append_execution_event

ADD_FIELD_RE = re.compile(r"^/add_field\s+(\S+)\s+([^:\s]+)\s*:\s*(\S+)\s*$")
ADD_API_RE = re.compile(r"^/add_api\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*$", re.IGNORECASE)
ADD_PAGE_RE = re.compile(r"^/add_page\s+(.+)$")
ADD_IMPLEMENT_PAGE_RE = re.compile(r"^/implement_page\s+(.+)$")
ADD_ENTITY_RE = re.compile(r"^/add_entity\s+(\S+)\s*$")
AUTO_RE = re.compile(r"^/auto(?:\s+(\d+))?\s*$")
AUTO_STRATEGIES = {"safe", "balanced", "aggressive"}


def _normalize_auto_strategy(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in AUTO_STRATEGIES else "balanced"


def _strategy_allows_priority(strategy: str, priority: str) -> bool:
    normalized = _normalize_auto_strategy(strategy)
    level = str(priority or "").strip().lower()
    if level == "none":
        return False
    if normalized == "safe":
        return level == "high"
    if normalized == "aggressive":
        return level in {"high", "medium"}
    return level in {"high", "medium"}


def _strategy_adjust_budget(base_budget: int, strategy: str) -> int:
    normalized = _normalize_auto_strategy(strategy)
    if normalized == "safe":
        return max(1, min(4, base_budget - 1))
    if normalized == "aggressive":
        return min(8, base_budget + 1)
    return base_budget


def _strategy_stop_explanation(strategy: str, priority: str) -> str:
    normalized = _normalize_auto_strategy(strategy)
    level = str(priority or "").strip().lower() or "unknown"
    if normalized == "safe":
        return f"Safe strategy allows only high-priority actions; next candidate priority is {level}."
    return f"Strategy guard blocked next candidate priority={level}."


def _resolve_project_dir(project_name: str) -> Path | None:
    key = str(project_name or "").strip()
    if not key:
        return None
    try:
        from archmind.project_query import find_project_by_name

        resolved = find_project_by_name(key)
        if resolved is not None:
            return resolved
    except Exception:
        pass

    # Telegram tests often resolve projects via patched _resolve_target_project without
    # ARCHMIND_PROJECTS_DIR wiring, so keep this fallback.
    try:
        from archmind.telegram_bot import _resolve_target_project

        candidate = _resolve_target_project()
        if candidate is not None and str(candidate.name or "").strip() == key:
            return candidate
    except Exception:
        pass
    return None


def _write_execution_event(
    project_dir: Path | None,
    *,
    project_name: str,
    source: str,
    command: str,
    status: str,
    message: str,
    run_id: str | None = None,
    step_no: int | None = None,
    stop_reason: str | None = None,
) -> None:
    if project_dir is None:
        return
    append_execution_event(
        project_dir,
        project_name=project_name,
        source=source,
        command=command,
        status=status,
        message=message,
        run_id=run_id,
        step_no=step_no,
        stop_reason=stop_reason,
    )


def _execute_auto_command(
    project_dir: Path,
    *,
    project_name: str,
    source: str,
    run_id: str | None = None,
    requested_steps: int | None = None,
    auto_strategy: str | None = None,
) -> dict[str, Any]:
    from archmind.state import load_state, write_state
    from archmind.execution_history import append_execution_event
    from archmind.telegram_bot import (
        AUTO_ALLOWED_COMMANDS,
        _analysis_progress_signature,
        _auto_analysis_brief,
        _auto_command_already_satisfied,
        _auto_is_good_enough_mvp,
        _auto_is_multi_entity,
        _auto_progress_snapshot,
        _auto_runtime_state_lines,
        _auto_stop_explanation,
        _build_project_analysis,
        _compute_auto_iteration_budget,
        _extract_next_action,
        _extract_next_action_explanation,
        _normalize_recommended_command,
        _parse_command_string,
        auto_progress_delta,
        classify_auto_action_priority,
        sync_repo_after_auto_batch,
    )

    summary_lines: list[str] = [
        "Auto evolution run",
        f"Target Project: {project_dir.name}",
        "",
    ]
    strategy = _normalize_auto_strategy(auto_strategy)
    seen_commands: set[str] = set()
    seen_command_states: set[tuple[str, tuple[Any, ...]]] = set()
    executed_commands: list[str] = []
    executed = 0
    stop_reason = "max step count reached"
    progress_made = False
    run_key = run_id or f"auto-{project_dir.name}"
    analysis = _build_project_analysis(project_dir, use_canonical_spec=True)
    initial_snapshot = _auto_progress_snapshot(analysis)
    base_budget, budget_reasons = _compute_auto_iteration_budget(analysis, requested_steps)
    iteration_budget = _strategy_adjust_budget(base_budget, strategy)
    total_progress_score = 0
    dynamic_extensions = 0

    summary_lines.extend(
        [
            f"Strategy: {strategy}",
            f"Budget: {iteration_budget}",
            f"Budget reason: {', '.join(budget_reasons)} + strategy={strategy}",
            "",
        ]
    )

    idx = 1
    while idx <= iteration_budget:
        kind, message, raw_command = _extract_next_action(analysis)
        explanation = _extract_next_action_explanation(analysis)
        reason_summary = str(explanation.get("reason_summary") or "").strip() or message
        expected_effect = str(explanation.get("expected_effect") or "").strip()
        priority_reason = str(explanation.get("priority_reason") or "").strip()
        priority = classify_auto_action_priority({"kind": kind, "message": message, "command": raw_command})
        normalized_command = _normalize_recommended_command(raw_command)
        cmd, _ = _parse_command_string(normalized_command) if normalized_command else ("", [])
        priority_allowed = _strategy_allows_priority(strategy, priority)
        actionable_supported = priority_allowed and bool(normalized_command) and cmd in AUTO_ALLOWED_COMMANDS
        state_signature = _analysis_progress_signature(analysis)
        before_snapshot = _auto_progress_snapshot(analysis)

        summary_lines.append(f"Step {idx}")
        if reason_summary:
            summary_lines.append(f"- Why: {reason_summary}")
        if expected_effect:
            summary_lines.append(f"- Expected effect: {expected_effect}")
        if priority_reason:
            summary_lines.append(f"- Priority reason: {priority_reason}")

        if not actionable_supported:
            if _auto_is_good_enough_mvp(analysis):
                stop_reason = "good enough MVP reached"
                stop_explanation = _auto_stop_explanation(stop_reason, analysis)
                summary_lines.append("- Result: STOP (good enough MVP reached)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command or raw_command or "",
                    status="stop",
                    message=f"Good enough MVP reached. {stop_explanation}",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break
            if priority == "none":
                stop_reason = "no immediate next action"
                stop_explanation = _auto_stop_explanation(stop_reason, analysis)
                summary_lines.append("- No immediate next action.")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command or raw_command or "",
                    status="stop",
                    message=f"No immediate next action. {stop_explanation}",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break
            if not normalized_command:
                stop_reason = "empty or malformed command"
                stop_explanation = _auto_stop_explanation(stop_reason, analysis)
                summary_lines.append("- Result: STOP (empty or malformed command)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=raw_command or "",
                    status="stop",
                    message="Empty or malformed command.",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break
            summary_lines.append(f"- Next: {normalized_command}")
            if cmd not in AUTO_ALLOWED_COMMANDS:
                stop_reason = f"unsupported command: {cmd or normalized_command}"
                stop_explanation = _auto_stop_explanation(stop_reason, analysis)
                summary_lines.append("- Result: STOP (unsupported command)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command,
                    status="stop",
                    message="Unsupported command for auto run.",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break
            if not priority_allowed:
                stop_reason = f"strategy guard: {strategy} blocks {priority or 'unknown'}-priority action"
                stop_explanation = _strategy_stop_explanation(strategy, priority)
                summary_lines.append("- Result: STOP (strategy guard)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command,
                    status="stop",
                    message=stop_explanation,
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break
            if priority == "low":
                stop_reason = "low-priority next action"
                stop_explanation = _auto_stop_explanation(stop_reason, analysis)
                summary_lines.append("- Result: STOP (low-priority next action)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command,
                    status="stop",
                    message="Low-priority next action.",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                break

        summary_lines.append(f"- Next: {normalized_command}")
        if _auto_command_already_satisfied(analysis, normalized_command):
            stop_reason = "already satisfied command"
            stop_explanation = _auto_stop_explanation(stop_reason, analysis)
            summary_lines.append("- Result: STOP (already satisfied in canonical state)")
            summary_lines.append(f"- Why stop: {stop_explanation}")
            append_execution_event(
                project_dir,
                project_name=project_name,
                source=source,
                command=normalized_command,
                status="stop",
                message="Command already satisfied by canonical project state.",
                run_id=run_key,
                step_no=idx,
                stop_reason=stop_reason,
            )
            break

        state_key = (normalized_command, state_signature)
        if state_key in seen_command_states:
            stop_reason = "repeated command without state change"
            stop_explanation = _auto_stop_explanation(stop_reason, analysis)
            summary_lines.append("- Result: STOP (repeated command without state change)")
            summary_lines.append(f"- Why stop: {stop_explanation}")
            append_execution_event(
                project_dir,
                project_name=project_name,
                source=source,
                command=normalized_command,
                status="stop",
                message="Repeated command without material state change.",
                run_id=run_key,
                step_no=idx,
                stop_reason=stop_reason,
            )
            break
        seen_command_states.add(state_key)

        if normalized_command in seen_commands:
            stop_reason = "repeated command detected"
            stop_explanation = _auto_stop_explanation(stop_reason, analysis)
            summary_lines.append("- Result: STOP (repeated-command protection)")
            summary_lines.append(f"- Why stop: {stop_explanation}")
            append_execution_event(
                project_dir,
                project_name=project_name,
                source=source,
                command=normalized_command,
                status="stop",
                message="Repeated command detected.",
                run_id=run_key,
                step_no=idx,
                stop_reason=stop_reason,
            )
            break
        seen_commands.add(normalized_command)

        step_result = execute_command(
            normalized_command,
            project_name,
            source=source,
            run_id=run_key,
            step_no=idx,
            enable_git_sync=False,
        )
        if bool(step_result.get("ok")):
            summary_lines.append("- Result: OK")
            executed += 1
            executed_commands.append(normalized_command)
            next_analysis = _build_project_analysis(project_dir, use_canonical_spec=True)
            if _analysis_progress_signature(next_analysis) != state_signature:
                delta = auto_progress_delta(before_snapshot, _auto_progress_snapshot(next_analysis))
                score = int(delta.get("score") or 0)
                if bool(delta.get("material")):
                    progress_made = True
                    total_progress_score += score
                    summary_lines.append(f"- Progress score: +{score}")
                    extension_limit = 0
                    extension_threshold = 4
                    if strategy == "balanced":
                        extension_limit = 2
                    elif strategy == "aggressive":
                        extension_limit = 3
                        extension_threshold = 3
                    if (
                        extension_limit > 0
                        and score >= extension_threshold
                        and _auto_is_multi_entity(next_analysis)
                        and iteration_budget < 8
                        and dynamic_extensions < extension_limit
                    ):
                        iteration_budget += 1
                        dynamic_extensions += 1
                        summary_lines.append(f"- Budget extended: {iteration_budget}")
                else:
                    stop_reason = "no material progress"
                    stop_explanation = _auto_stop_explanation(stop_reason, next_analysis)
                    summary_lines.append("- Result: STOP (no material progress)")
                    summary_lines.append(f"- Why stop: {stop_explanation}")
                    append_execution_event(
                        project_dir,
                        project_name=project_name,
                        source=source,
                        command=normalized_command,
                        status="stop",
                        message="No material progress after command execution.",
                        run_id=run_key,
                        step_no=idx,
                        stop_reason=stop_reason,
                    )
                    analysis = next_analysis
                    break
            else:
                stop_reason = "no material state change after command"
                stop_explanation = _auto_stop_explanation(stop_reason, next_analysis)
                summary_lines.append("- Result: STOP (no material state change)")
                summary_lines.append(f"- Why stop: {stop_explanation}")
                append_execution_event(
                    project_dir,
                    project_name=project_name,
                    source=source,
                    command=normalized_command,
                    status="stop",
                    message="No material state change after command execution.",
                    run_id=run_key,
                    step_no=idx,
                    stop_reason=stop_reason,
                )
                analysis = next_analysis
                break
            analysis = next_analysis
        else:
            detail = str(step_result.get("error") or step_result.get("detail") or step_result.get("message") or "execution failed").strip()
            stop_reason = f"command failed: {detail}"
            stop_explanation = _auto_stop_explanation(stop_reason, analysis)
            summary_lines.append(f"- Result: FAIL ({detail})")
            summary_lines.append(f"- Why stop: {stop_explanation}")
            append_execution_event(
                project_dir,
                project_name=project_name,
                source=source,
                command=normalized_command,
                status="stop",
                message=detail,
                run_id=run_key,
                step_no=idx,
                stop_reason=stop_reason,
            )
            break

        summary_lines.append("")
        idx += 1
    else:
        stop_reason = "iteration budget reached"

    if summary_lines and summary_lines[-1] == "":
        summary_lines.pop()
    final_snapshot = _auto_progress_snapshot(analysis)
    if str(stop_reason).startswith("strategy guard:"):
        blocked_priority = str(stop_reason).split(" blocks ", 1)[-1].split("-priority", 1)[0].strip()
        stop_explanation = _strategy_stop_explanation(strategy, blocked_priority)
    else:
        stop_explanation = _auto_stop_explanation(stop_reason, analysis)
    repo_sync: dict[str, Any] = {"status": "NOT_ATTEMPTED", "reason": "no executed changes"}
    if executed_commands:
        repo_sync = sync_repo_after_auto_batch(project_dir, executed_commands)

    runtime_lines = _auto_runtime_state_lines(project_dir)
    runtime_backend = ""
    runtime_frontend = ""
    runtime_backend_url = ""
    runtime_frontend_url = ""
    if runtime_lines:
        first = str(runtime_lines[0] or "")
        if "backend=" in first and "frontend=" in first:
            pieces = first.split("backend=", 1)[-1].split(", frontend=")
            if len(pieces) == 2:
                runtime_backend = pieces[0].strip()
                runtime_frontend = pieces[1].strip()
    for row in runtime_lines:
        text = str(row or "").strip()
        if text.startswith("- Backend URL:"):
            runtime_backend_url = text.split(":", 1)[-1].strip()
        if text.startswith("- Frontend URL:"):
            runtime_frontend_url = text.split(":", 1)[-1].strip()

    summary_lines.extend(
        [
            "",
            "Summary",
            f"- Executed: {executed}",
            f"- Commands: {', '.join(executed_commands) if executed_commands else '(none)'}",
            f"- Stopped: {stop_reason}",
            f"- Stop explanation: {stop_explanation}",
            f"- Progress made: {'yes' if progress_made else 'no'}",
            f"- Progress score: {total_progress_score}",
            (
                "- Metrics: "
                f"entities {initial_snapshot['entities']}->{final_snapshot['entities']}, "
                f"apis {initial_snapshot['apis']}->{final_snapshot['apis']}, "
                f"pages {initial_snapshot['pages']}->{final_snapshot['pages']}, "
                f"relation_pages {initial_snapshot['relation_pages']}->{final_snapshot['relation_pages']}, "
                f"relation_apis {initial_snapshot['relation_apis']}->{final_snapshot['relation_apis']}, "
                f"placeholders {initial_snapshot['placeholders']}->{final_snapshot['placeholders']}"
            ),
            f"- Current: {_auto_analysis_brief(analysis)}",
            f"- Repo sync: {str(repo_sync.get('status') or 'NOT_ATTEMPTED').strip().upper()}",
        ]
    )
    summary_lines.extend(runtime_lines)

    auto_result = {
        "run_id": run_key,
        "strategy": strategy,
        "executed": executed,
        "commands": executed_commands,
        "stop_reason": stop_reason,
        "stop_explanation": stop_explanation,
        "progress_made": progress_made,
        "progress_score": total_progress_score,
        "metrics_before": initial_snapshot,
        "metrics_after": final_snapshot,
        "current": _auto_analysis_brief(analysis),
        "repo_sync": repo_sync,
        "runtime": {
            "backend_status": runtime_backend,
            "frontend_status": runtime_frontend,
            "backend_url": runtime_backend_url,
            "frontend_url": runtime_frontend_url,
        },
    }

    try:
        state = load_state(project_dir) or {}
        state["auto_last_result"] = auto_result
        write_state(project_dir, state)
    except Exception:
        pass

    return {
        "ok": True,
        "project_name": project_name,
        "message_text": "\n".join(summary_lines),
        "detail": f"Auto completed: executed={executed}, stopped={stop_reason}",
        "repository_sync": repo_sync,
        "auto_result": auto_result,
    }


def execute_command(
    command: str,
    project_name: str,
    *,
    source: str = "manual-command",
    run_id: str | None = None,
    step_no: int | None = None,
    enable_git_sync: bool = True,
    auto_strategy: str | None = None,
) -> dict:
    normalized_command = str(command or "").strip()
    normalized_auto_strategy = _normalize_auto_strategy(auto_strategy)
    key = str(project_name or "").strip()
    if not normalized_command:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Command is required",
        }
    if not key:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "project_name is required",
        }

    project_dir = _resolve_project_dir(key)
    if project_dir is None:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Project not found",
        }

    field_match = ADD_FIELD_RE.match(normalized_command)
    api_match = ADD_API_RE.match(normalized_command)
    page_match = ADD_PAGE_RE.match(normalized_command)
    implement_page_match = ADD_IMPLEMENT_PAGE_RE.match(normalized_command)
    entity_match = ADD_ENTITY_RE.match(normalized_command)
    auto_match = AUTO_RE.match(normalized_command)

    try:
        from archmind.telegram_bot import (
            add_api_to_project,
            add_entity_to_project,
            add_field_to_project,
            add_page_to_project,
            implement_page_in_project,
            sync_repo_after_evolution_command,
        )

        result: dict[str, Any]
        if auto_match:
            raw_steps = str(auto_match.group(1) or "").strip()
            requested_steps = None
            if raw_steps:
                try:
                    requested_steps = int(raw_steps)
                except Exception:
                    requested_steps = None
            result = _execute_auto_command(
                project_dir,
                project_name=key,
                source=source,
                run_id=run_id,
                requested_steps=requested_steps,
                auto_strategy=normalized_auto_strategy,
            )
        elif entity_match:
            entity_name = str(entity_match.group(1) or "").strip()
            result = add_entity_to_project(project_dir, entity_name, auto_restart_backend=True)
        elif field_match:
            entity_name = str(field_match.group(1) or "").strip()
            field_name = str(field_match.group(2) or "").strip()
            field_type = str(field_match.group(3) or "").strip().lower()
            result = add_field_to_project(project_dir, entity_name, field_name, field_type, auto_restart_backend=True)
        elif api_match:
            method = str(api_match.group(1) or "").strip().upper()
            path = str(api_match.group(2) or "").strip()
            result = add_api_to_project(project_dir, method, path, auto_restart_backend=True)
        elif page_match:
            page_path = str(page_match.group(1) or "").strip()
            if not page_path:
                payload = {
                    "ok": False,
                    "command": normalized_command,
                    "project_name": key,
                    "message": "",
                    "error": "Usage: /add_page <path>",
                }
                _write_execution_event(
                    project_dir,
                    project_name=key,
                    source=source,
                    command=normalized_command,
                    status="fail",
                    message=str(payload.get("error") or ""),
                    run_id=run_id,
                    step_no=step_no,
                )
                return payload
            result = add_page_to_project(project_dir, page_path, auto_restart_backend=True)
        elif implement_page_match:
            page_path = str(implement_page_match.group(1) or "").strip()
            if not page_path:
                payload = {
                    "ok": False,
                    "command": normalized_command,
                    "project_name": key,
                    "message": "",
                    "error": "Usage: /implement_page <path>",
                }
                _write_execution_event(
                    project_dir,
                    project_name=key,
                    source=source,
                    command=normalized_command,
                    status="fail",
                    message=str(payload.get("error") or ""),
                    run_id=run_id,
                    step_no=step_no,
                )
                return payload
            result = implement_page_in_project(project_dir, page_path, auto_restart_backend=True)
        else:
            payload = {
                "ok": False,
                "command": normalized_command,
                "project_name": key,
                "message": "",
                "error": "Unsupported command. Supported: /add_entity, /add_field, /add_api, /add_page, /implement_page, /auto",
            }
            _write_execution_event(
                project_dir,
                project_name=key,
                source=source,
                command=normalized_command,
                status="fail",
                message=str(payload.get("error") or ""),
                run_id=run_id,
                step_no=step_no,
            )
            return payload
    except Exception as exc:
        payload = {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": str(exc),
        }
        _write_execution_event(
            project_dir,
            project_name=key,
            source=source,
            command=normalized_command,
            status="fail",
            message=str(payload.get("error") or ""),
            run_id=run_id,
            step_no=step_no,
        )
        return payload

    if not isinstance(result, dict):
        payload = {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Command execution failed",
        }
        _write_execution_event(
            project_dir,
            project_name=key,
            source=source,
            command=normalized_command,
            status="fail",
            message=str(payload.get("error") or ""),
            run_id=run_id,
            step_no=step_no,
        )
        return payload

    message = str(result.get("message_text") or result.get("detail") or "").strip()
    error = str(result.get("error") or "").strip() or None
    payload = dict(result)
    payload.update(
        {
            "ok": bool(result.get("ok")),
            "command": normalized_command,
            "project_name": str(result.get("project_name") or key),
            "message": message,
            "error": error,
        }
    )
    if bool(payload.get("ok")) and enable_git_sync and not auto_match:
        sync = sync_repo_after_evolution_command(project_dir, normalized_command)
        payload["repository_sync"] = sync
        sync_status = str(sync.get("status") or "").strip().upper()
        sync_reason = str(sync.get("reason") or "").strip()
        if sync_status in {"PUSH_FAILED", "COMMIT_ONLY"}:
            base_message = str(payload.get("message_text") or payload.get("message") or "").strip()
            extra = f"Repository sync: {sync_status}"
            if sync_reason:
                extra += f" ({sync_reason})"
            sync_hint = str(sync.get("hint") or "").strip()
            if sync_hint:
                extra += f"\nHint: {sync_hint}"
            if base_message:
                payload["message_text"] = f"{base_message}\n\n{extra}"
            else:
                payload["message_text"] = extra
            payload["message"] = str(payload.get("message_text") or payload.get("message") or "").strip()
    _write_execution_event(
        project_dir,
        project_name=str(payload.get("project_name") or key),
        source=source,
        command=normalized_command,
        status="ok" if bool(payload.get("ok")) else "fail",
        message=str(payload.get("message") or payload.get("error") or ""),
        run_id=run_id,
        step_no=step_no,
    )
    return payload
