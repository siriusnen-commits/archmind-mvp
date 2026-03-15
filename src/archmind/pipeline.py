from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.fixer import run_fix_loop
from archmind.brain import reason_architecture_from_idea
from archmind.failure_memory import append_failure_memory, get_failure_hints
from archmind.idea_normalizer import normalize_idea
from archmind.environment import ensure_environment_readiness
from archmind.evaluator import write_evaluation
from archmind.github_repo import create_github_repo
from archmind.deploy import deploy_project
from archmind.planner import write_project_plan
from archmind.project_type import detect_project_type, normalize_project_type
from archmind.template_selector import (
    resolve_default_template,
    resolve_effective_template,
    select_template_for_project_type,
)
from archmind.runner import RunConfig, RunResult, compute_run_status, run_pipeline
from archmind.state import (
    ensure_state,
    load_state,
    set_agent_state,
    set_progress_step,
    update_after_deploy,
    update_after_fix,
    update_after_run,
    write_state,
)
from archmind.tasks import current_task, ensure_tasks


@dataclass
class PipelineOptions:
    idea: Optional[str]
    path: Optional[Path]
    out: str
    name: Optional[str]
    template: str
    template_explicit: bool
    prompt: Optional[str]
    gen_model: str
    gen_ollama_base_url: str
    gen_max_retries: int
    gen_timeout_s: int
    run_all: bool
    backend_only: bool
    frontend_only: bool
    no_install: bool
    profile: Optional[str]
    cmds: list[str]
    timeout_s: int
    scope: str
    max_iterations: int
    model: str
    apply: bool
    dry_run: bool
    json_summary: bool
    auto_deploy: bool
    auto_deploy_target: str


def _filter_kwargs_for_callable(fn, kwargs: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    accepted = set(sig.parameters.keys())
    return {k: v for k, v in kwargs.items() if k in accepted}


def _resolve_generator_entry():
    import archmind.generator as gen  # type: ignore

    candidates = [
        "generate_project",
        "generate",
        "generate_from_idea",
        "generate_project_from_idea",
        "run_generate",
    ]
    for name in candidates:
        fn = getattr(gen, name, None)
        if callable(fn):
            return fn
    for name, obj in vars(gen).items():
        if callable(obj) and name.startswith("generate"):
            return obj
    raise RuntimeError(
        "No generator entrypoint found in archmind.generator. "
        "Expected one of: generate_project / generate / generate_from_idea / generate_project_from_idea."
    )


def _make_generate_options(opt_kwargs: dict[str, Any]):
    from archmind.generator import GenerateOptions  # type: ignore

    init = GenerateOptions.__init__  # type: ignore[attr-defined]
    filtered = _filter_kwargs_for_callable(init, opt_kwargs)
    return GenerateOptions(**filtered)


def _resolve_project_dir(opts: PipelineOptions, modules: Optional[list[str]] = None) -> Optional[Path]:
    if opts.idea:
        opt_kwargs = _build_generate_options_kwargs(opts)
        opt = _make_generate_options(opt_kwargs)
        setattr(opt, "modules", list(modules or []))
        gen_entry = _resolve_generator_entry()

        # positional-first call attempt
        try_orders = [
            (opts.idea, opt),
            (opts.idea,),
            (),
        ]
        for tup in try_orders:
            try:
                generated = gen_entry(*tup)
                return Path(generated).resolve() if generated else None
            except TypeError:
                pass

        call_kwargs = {"idea": opts.idea, "opt": opt, "options": opt}
        filtered = _filter_kwargs_for_callable(gen_entry, call_kwargs)
        generated = gen_entry(**filtered)
        return Path(generated).resolve() if generated else None

    if opts.path:
        return opts.path.resolve()

    return None


def _generate_options_supported_fields(cls: type) -> Optional[set[str]]:
    if hasattr(cls, "__dataclass_fields__"):
        return set(getattr(cls, "__dataclass_fields__", {}).keys())

    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        sig = inspect.signature(cls)

    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return None

    return {k for k in sig.parameters.keys() if k != "self"}


def _add_first_supported(
    target: dict[str, Any], supported: Optional[set[str]], names: tuple[str, ...], value: Any
) -> None:
    if value is None:
        return
    if supported is None:
        target.setdefault(names[0], value)
        return
    for name in names:
        if name in supported:
            target[name] = value
            return


def _build_generate_options_kwargs(opts: PipelineOptions) -> dict[str, Any]:
    from archmind.generator import GenerateOptions  # type: ignore

    supported = _generate_options_supported_fields(GenerateOptions)
    result: dict[str, Any] = {}
    out_value = opts.out or "generated"
    _add_first_supported(result, supported, ("out", "out_dir"), Path(out_value))
    _add_first_supported(result, supported, ("force",), False)
    _add_first_supported(result, supported, ("name",), opts.name)
    _add_first_supported(result, supported, ("template",), opts.template)
    _add_first_supported(result, supported, ("prompt",), opts.prompt)
    _add_first_supported(result, supported, ("model", "gen_model"), opts.gen_model)
    _add_first_supported(
        result,
        supported,
        ("ollama_base_url", "base_url", "gen_ollama_base_url"),
        opts.gen_ollama_base_url,
    )
    _add_first_supported(result, supported, ("max_retries", "gen_max_retries"), opts.gen_max_retries)
    _add_first_supported(result, supported, ("timeout_s", "gen_timeout_s"), opts.gen_timeout_s)
    return result


def _latest_run_summary(project_dir: Path) -> Optional[str]:
    log_dir = project_dir / ".archmind" / "run_logs"
    if not log_dir.exists():
        return None
    summaries = sorted(log_dir.glob("run_*.summary.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not summaries:
        return None
    return summaries[0].read_text(encoding="utf-8", errors="replace")


def _latest_path(project_dir: Path, pattern: str) -> Optional[Path]:
    base = project_dir / ".archmind" / "run_logs"
    if not base.exists():
        return None
    matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _latest_run_prompt(project_dir: Path) -> Optional[Path]:
    base = project_dir / ".archmind" / "run_logs"
    if not base.exists():
        return None
    matches = sorted(base.glob("*.prompt.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in matches:
        if not path.name.startswith("fix_"):
            return path
    return None


def _build_command(opts: PipelineOptions) -> str:
    parts = ["archmind", "pipeline"]
    if opts.path:
        parts += ["--path", str(opts.path)]
    if opts.idea:
        parts += ["--idea", opts.idea]
    if opts.out:
        parts += ["--out", opts.out]
    if opts.name:
        parts += ["--name", opts.name]
    if opts.template:
        parts += ["--template", opts.template]
    if opts.prompt:
        parts += ["--prompt", opts.prompt]
    if opts.gen_model:
        parts += ["--gen-model", opts.gen_model]
    if opts.gen_ollama_base_url:
        parts += ["--gen-ollama-base-url", opts.gen_ollama_base_url]
    parts += ["--gen-max-retries", str(opts.gen_max_retries)]
    parts += ["--gen-timeout-s", str(opts.gen_timeout_s)]
    if opts.run_all:
        parts.append("--all")
    if opts.backend_only:
        parts.append("--backend-only")
    if opts.frontend_only:
        parts.append("--frontend-only")
    if opts.profile:
        parts += ["--profile", opts.profile]
        for cmd in opts.cmds:
            parts += ["--cmd", cmd]
    if opts.no_install:
        parts.append("--no-install")
    parts += ["--timeout-s", str(opts.timeout_s)]
    parts += ["--scope", opts.scope]
    parts += ["--max-iterations", str(opts.max_iterations)]
    parts += ["--model", opts.model]
    if opts.apply:
        parts.append("--apply")
    if opts.dry_run:
        parts.append("--dry-run")
    if opts.json_summary:
        parts.append("--json-summary")
    if opts.auto_deploy:
        parts.append("--auto-deploy")
    if opts.auto_deploy_target:
        parts += ["--deploy-target", opts.auto_deploy_target]
    return " ".join(parts)


def compute_status(
    run_before_ok: bool,
    fix_exit: Optional[int],
    run_after_ok: Optional[bool],
    apply: bool,
) -> str:
    if run_before_ok:
        return "SUCCESS"
    if fix_exit is None:
        return "FAIL"
    if fix_exit != 0:
        return "PARTIAL" if not apply else "FAIL"
    if run_after_ok:
        return "SUCCESS"
    return "FAIL"


def _build_result_text(payload: dict[str, Any]) -> str:
    current = payload.get("current_task") or {}
    current_text = "N/A"
    if isinstance(current, dict) and current.get("id") is not None:
        current_text = f"[{current.get('id')}] {current.get('status')} {current.get('title')}"
    evaluation = payload.get("evaluation") or {}
    evaluation_text = "N/A"
    if isinstance(evaluation, dict) and evaluation.get("status"):
        evaluation_text = str(evaluation.get("status"))
    state_info = payload.get("state") or {}
    state_text = "N/A"
    if isinstance(state_info, dict) and state_info.get("last_status"):
        state_text = f"{state_info.get('last_status')} iter={state_info.get('iterations', 'N/A')}"
    lines = [
        "ArchMind Pipeline Result",
        f"- status: {payload.get('status')}",
        f"- project_type: {payload.get('project_type') or 'unknown'}",
        f"- selected_template: {payload.get('selected_template') or 'unknown'}",
        f"- effective_template: {payload.get('effective_template') or 'unknown'}",
        f"- template_fallback_reason: {payload.get('template_fallback_reason') or 'N/A'}",
        f"- evaluation: {evaluation_text}",
        f"- state: {state_text}",
        f"- project_dir: {payload.get('project_dir')}",
        f"- timestamp: {payload.get('timestamp')}",
        f"- command: {payload.get('command')}",
        f"- current_task: {current_text}",
        "",
        "Steps:",
        f"- generate: {payload['steps']['generate']}",
        f"- run_before_fix: {payload['steps']['run_before_fix']}",
        f"- fix: {payload['steps']['fix']}",
        f"- run_after_fix: {payload['steps']['run_after_fix']}",
    ]
    auto_deploy_step = payload.get("steps", {}).get("auto_deploy")
    if isinstance(auto_deploy_step, dict):
        lines.append(f"- auto_deploy: {auto_deploy_step}")
    lines += [
        "",
        "Artifacts:",
    ]
    for key, value in payload.get("artifacts", {}).items():
        lines.append(f"- {key}: {value or 'N/A'}")
    return "\n".join(lines) + "\n"


def write_result(project_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    result_dir = project_dir / ".archmind"
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / "result.json"
    txt_path = result_dir / "result.txt"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    txt_path.write_text(_build_result_text(payload), encoding="utf-8")
    return json_path, txt_path


def _build_run_config(opts: PipelineOptions, project_dir: Path) -> RunConfig:
    if opts.backend_only:
        run_all = False
        backend_only = True
        frontend_only = False
    elif opts.frontend_only:
        run_all = False
        backend_only = False
        frontend_only = True
    elif opts.run_all:
        run_all = True
        backend_only = False
        frontend_only = False
    else:
        # default: run both when no explicit flags are given
        run_all = True
        backend_only = False
        frontend_only = False

    return RunConfig(
        project_dir=project_dir,
        run_all=run_all,
        backend_only=backend_only,
        frontend_only=frontend_only,
        no_install=opts.no_install,
        timeout_s=opts.timeout_s,
        log_dir=project_dir / ".archmind" / "run_logs",
        json_summary=True,
        command="archmind pipeline run",
        profile=opts.profile,
        cmds=opts.cmds,
    )


def _effective_fix_scope(opts: PipelineOptions) -> str:
    if opts.backend_only:
        return "backend"
    if opts.frontend_only:
        return "frontend"
    if opts.run_all:
        return "all"
    return opts.scope


def _write_pipeline_logs(
    project_dir: Path,
    timestamp: str,
    project_type: str,
    selected_template: str,
    effective_template: str,
    template_fallback_reason: str,
    run_result: RunResult,
    fix_exit: Optional[int],
    rerun_exit: Optional[int],
    final_exit: int,
    json_summary: bool,
) -> None:
    log_dir = project_dir / ".archmind" / "pipeline_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / f"pipeline_{timestamp}.log"
    summary_path = log_dir / f"pipeline_{timestamp}.summary.txt"
    summary_json_path = log_dir / f"pipeline_{timestamp}.summary.json"

    log_lines = [
        f"timestamp: {timestamp}",
        f"project_dir: {project_dir}",
        f"project_type: {project_type}",
        f"selected_template: {selected_template}",
        f"effective_template: {effective_template}",
        f"template_fallback_reason: {template_fallback_reason or 'N/A'}",
        f"run_exit: {run_result.overall_exit_code}",
        f"fix_exit: {fix_exit if fix_exit is not None else 'N/A'}",
        f"rerun_exit: {rerun_exit if rerun_exit is not None else 'N/A'}",
        f"final_exit: {final_exit}",
    ]
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    summary_lines = [
        "1) Pipeline meta:",
        f"- project_dir: {project_dir}",
        f"- timestamp: {timestamp}",
        f"- project_type: {project_type}",
        f"- selected_template: {selected_template}",
        f"- effective_template: {effective_template}",
        f"- template_fallback_reason: {template_fallback_reason or 'N/A'}",
        "2) Run:",
        f"- exit_code: {run_result.overall_exit_code}",
        "3) Fix:",
        f"- exit_code: {fix_exit if fix_exit is not None else 'N/A'}",
        "4) Rerun:",
        f"- exit_code: {rerun_exit if rerun_exit is not None else 'N/A'}",
        "5) Final:",
        f"- exit_code: {final_exit}",
    ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    if json_summary:
        payload = {
            "meta": {"project_dir": str(project_dir), "timestamp": timestamp, "project_type": project_type},
            "template": {
                "selected_template": selected_template,
                "effective_template": effective_template,
                "template_fallback_reason": template_fallback_reason or None,
            },
            "run": {"exit_code": run_result.overall_exit_code},
            "fix": {"exit_code": fix_exit},
            "rerun": {"exit_code": rerun_exit},
            "final_exit_code": final_exit,
        }
        summary_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_component_statuses(run_result: RunResult) -> dict[str, Any]:
    if run_result.profile and run_result.profile != "legacy" and run_result.profile_steps is not None:
        status, reason = compute_run_status(run_result)
        return {"profile": run_result.profile, "status": status, "reason": reason}
    return {
        "backend_status": run_result.backend.status,
        "frontend_status": run_result.frontend.status,
        "frontend_reason": run_result.frontend.reason,
        "backend_reason": run_result.backend.reason,
    }


def _project_type_from_app_shape(app_shape: str) -> str:
    shape = str(app_shape or "").strip().lower()
    if shape == "fullstack":
        return "fullstack-web"
    if shape == "backend":
        return "backend-api"
    if shape == "frontend":
        return "frontend-web"
    return "unknown"


def _write_architecture_reasoning(project_dir: Path, payload: dict[str, Any]) -> Optional[Path]:
    try:
        out = project_dir / ".archmind" / "architecture_reasoning.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out
    except Exception:
        return None


def _failure_memory_path(opts: PipelineOptions, project_dir: Optional[Path] = None) -> Path:
    if project_dir is not None:
        base = project_dir
    elif opts.path is not None:
        base = opts.path.resolve()
    else:
        base = Path(opts.out or "generated").resolve()
    return base / ".archmind" / "failure_memory.json"


def _build_failure_hint(modules: list[str]) -> str:
    if "worker" in modules:
        return "similar idea may require worker module"
    if modules:
        return f"previous similar case suggested module {modules[0]}"
    return "review template/modules for similar failing ideas"


def _write_project_spec(
    project_dir: Path,
    architecture_reasoning: dict[str, Any],
    selected_template: str,
    effective_template: str,
) -> Optional[Path]:
    try:
        out = project_dir / ".archmind" / "project_spec.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        preferred_template = (
            selected_template
            or str(architecture_reasoning.get("recommended_template") or "").strip()
            or effective_template
            or "fastapi"
        )
        payload = {
            "shape": str(architecture_reasoning.get("app_shape") or "unknown"),
            "domains": [str(item) for item in (architecture_reasoning.get("domains") or []) if str(item).strip()],
            "template": preferred_template,
            "modules": [str(item) for item in (architecture_reasoning.get("modules") or []) if str(item).strip()],
            "reason_summary": str(architecture_reasoning.get("reason_summary") or ""),
            "entities": [],
            "api_endpoints": [],
            "frontend_pages": [],
            "evolution": {
                "version": 1,
                "added_modules": [],
                "history": [],
            },
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out
    except Exception:
        return None


def run_pipeline_command(opts: PipelineOptions) -> int:
    if opts.dry_run:
        steps = []
        if opts.idea:
            steps.append("generate")
        steps.append("run")
        steps.append("fix (on failure)")
        steps.append("run (after fix)")
        if opts.auto_deploy:
            steps.append(f"auto deploy ({opts.auto_deploy_target or 'local'})")
        print("[DRY-RUN] pipeline plan:")
        for step in steps:
            print(f"- {step}")
        return 0

    if opts.profile in ("generic", "generic-shell") and not opts.cmds:
        print("[ERROR] --profile generic-shell requires at least one --cmd.", file=sys.stderr)
        return 64

    initial_idea = (opts.idea or "").strip()
    normalized_idea = initial_idea
    idea_language = "en"
    architecture_reasoning: dict[str, Any] = {}
    selected_template = ""
    effective_template = opts.template
    template_fallback_reason = ""
    if initial_idea:
        normalized_payload = normalize_idea(initial_idea)
        normalized_idea = str(normalized_payload.get("normalized") or initial_idea)
        idea_language = str(normalized_payload.get("language") or "en")

        memory_path = _failure_memory_path(opts)
        for hint in get_failure_hints(normalized_idea, memory_path):
            print("Failure memory hint:")
            print(f"- {hint}")

        architecture_reasoning = reason_architecture_from_idea(normalized_idea)
        architecture_reasoning["idea_original"] = initial_idea
        architecture_reasoning["idea_normalized"] = normalized_idea
        architecture_reasoning["idea_language"] = idea_language

        routed_type = normalize_project_type(detect_project_type(normalized_idea))
        app_shape_type = _project_type_from_app_shape(str(architecture_reasoning.get("app_shape") or ""))
        if app_shape_type != "unknown":
            routed_type = app_shape_type
        if opts.template_explicit:
            selected_template = (opts.template or "").strip().lower() or "fastapi"
        else:
            brain_template = str(architecture_reasoning.get("recommended_template") or "").strip().lower()
            if brain_template and app_shape_type != "unknown":
                selected_template = brain_template
            else:
                selected_template = select_template_for_project_type(routed_type, normalized_idea)
        default_template = resolve_default_template()
        effective_template, fallback_reason = resolve_effective_template(selected_template, default_template)
        template_fallback_reason = fallback_reason or ""
        opts.template = effective_template
    else:
        fallback_template = resolve_default_template()
        effective_template = opts.template or fallback_template or "fastapi"

    try:
        project_dir = _resolve_project_dir(opts, modules=list(architecture_reasoning.get("modules") or []))
    except Exception as exc:
        append_failure_memory(
            _failure_memory_path(opts),
            idea=initial_idea or normalized_idea,
            template=effective_template or opts.template,
            modules=[str(item) for item in (architecture_reasoning.get("modules") or [])],
            error=str(exc),
            hint=_build_failure_hint([str(item) for item in (architecture_reasoning.get("modules") or [])]),
        )
        print(f"[ERROR] generation failed: {exc}", file=sys.stderr)
        return 1
    if project_dir is None:
        if initial_idea:
            append_failure_memory(
                _failure_memory_path(opts),
                idea=initial_idea or normalized_idea,
                template=effective_template or opts.template,
                modules=[str(item) for item in (architecture_reasoning.get("modules") or [])],
                error="generation returned no project directory",
                hint=_build_failure_hint([str(item) for item in (architecture_reasoning.get("modules") or [])]),
            )
        print("[ERROR] Provide --path or --idea for pipeline.", file=sys.stderr)
        return 2

    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 2

    reasoning_path: Optional[Path] = None
    project_spec_path: Optional[Path] = None
    if architecture_reasoning:
        architecture_reasoning["selected_template"] = selected_template
        architecture_reasoning["effective_template"] = effective_template
        reasoning_path = _write_architecture_reasoning(project_dir, architecture_reasoning)
        project_spec_path = _write_project_spec(project_dir, architecture_reasoning, selected_template, effective_template)

    plan_md_path: Optional[Path] = None
    plan_json_path: Optional[Path] = None
    plan_idea = initial_idea or f"{project_dir.name} 안정화 및 개선"
    try:
        plan_artifacts = write_project_plan(project_dir, plan_idea)
        plan_md_path = plan_artifacts.plan_md_path
        plan_json_path = plan_artifacts.plan_json_path
    except Exception as exc:
        print(f"[WARN] plan generation failed: {exc}", file=sys.stderr)
    try:
        ensure_tasks(project_dir)
    except Exception as exc:
        print(f"[WARN] tasks initialization failed: {exc}", file=sys.stderr)
    try:
        ensure_state(project_dir)
        ensure_environment_readiness(project_dir)
        if opts.idea:
            set_agent_state(project_dir, "PLANNING", action="pipeline planning", summary="idea to project planning")
            set_progress_step(
                project_dir,
                "planning",
                "Planning architecture",
                status="RUNNING",
                detail="analyzing idea",
            )
            set_progress_step(
                project_dir,
                "generating",
                "Generating project scaffold",
                status="RUNNING",
                detail=f"template={effective_template}",
            )
        set_agent_state(project_dir, "RUNNING", action="pipeline run", summary="pipeline execution started")
        set_progress_step(
            project_dir,
            "running_checks",
            "Running checks",
            status="RUNNING",
            detail="backend/frontend checks",
        )
    except Exception as exc:
        print(f"[WARN] state initialization failed: {exc}", file=sys.stderr)

    run_config = _build_run_config(opts, project_dir)
    command = _build_command(opts)
    archmind_dir = project_dir / ".archmind"
    existing_result = {}
    existing_state = {}
    try:
        existing_result = json.loads((archmind_dir / "result.json").read_text(encoding="utf-8"))
    except Exception:
        existing_result = {}
    try:
        existing_state = json.loads((archmind_dir / "state.json").read_text(encoding="utf-8"))
    except Exception:
        existing_state = {}
    inferred_type = detect_project_type(initial_idea) if initial_idea else ""
    project_type = normalize_project_type(
        inferred_type
        or str(existing_result.get("project_type") or "")
        or str(existing_state.get("project_type") or "")
    )
    if not selected_template:
        selected_template = str(existing_result.get("selected_template") or existing_state.get("selected_template") or "").strip()
    if not selected_template:
        selected_template = select_template_for_project_type(project_type, initial_idea or None)
    if not effective_template:
        effective_template = str(existing_result.get("effective_template") or existing_state.get("selected_template") or "").strip()
    if not effective_template:
        effective_template = opts.template or "fastapi"
    if not template_fallback_reason:
        template_fallback_reason = str(
            existing_result.get("template_fallback_reason") or existing_state.get("template_fallback_reason") or ""
        ).strip()

    final_exit = 1
    fix_exit: Optional[int] = None
    rerun_exit: Optional[int] = None
    rerun_result: Optional[RunResult] = None
    run_result: Optional[RunResult] = None
    github_repo_url: Optional[str] = None

    for iteration in range(1, opts.max_iterations + 1):
        try:
            set_progress_step(
                project_dir,
                "running_checks",
                "Running checks",
                status="RUNNING",
                detail=f"iteration={iteration}",
            )
        except Exception:
            pass
        run_result = run_pipeline(run_config)
        run_status, _ = compute_run_status(run_result)
        try:
            update_after_run(
                project_dir,
                action=f"pipeline run iteration {iteration}",
                run_status=run_status,
                summary=f"pipeline run iteration {iteration} -> {run_status}",
            )
        except Exception as exc:
            print(f"[WARN] state update(run) failed: {exc}", file=sys.stderr)
        if run_status in ("SUCCESS", "SKIP"):
            final_exit = 0
            break

        try:
            set_agent_state(
                project_dir,
                "FIXING",
                action=f"pipeline fix iteration {iteration}",
                summary=f"pipeline fix iteration {iteration} started",
            )
            set_progress_step(
                project_dir,
                "fixing",
                "Applying fixes",
                status="RUNNING",
                detail=f"iteration={iteration}",
            )
        except Exception as exc:
            print(f"[WARN] state phase(FIXING) failed: {exc}", file=sys.stderr)
        fix_exit = run_fix_loop(
            project_dir=project_dir,
            max_iterations=opts.max_iterations,
            model=opts.model,
            dry_run=opts.dry_run,
            timeout_s=opts.timeout_s,
            scope=_effective_fix_scope(opts),
            apply_changes=opts.apply,
            profile=opts.profile,
            cmds=opts.cmds,
        )
        try:
            update_after_fix(
                project_dir,
                action=f"pipeline fix iteration {iteration}",
                exit_code=fix_exit,
            )
        except Exception as exc:
            print(f"[WARN] state update(fix) failed: {exc}", file=sys.stderr)
        if fix_exit != 0:
            final_exit = 1
            break

        try:
            set_agent_state(
                project_dir,
                "RUNNING",
                action=f"pipeline rerun iteration {iteration}",
                summary=f"pipeline rerun iteration {iteration} started",
            )
            set_progress_step(
                project_dir,
                "running_checks",
                "Running checks",
                status="RUNNING",
                detail=f"rerun iteration={iteration}",
            )
        except Exception as exc:
            print(f"[WARN] state phase(RUNNING) failed: {exc}", file=sys.stderr)
        rerun_result = run_pipeline(run_config)
        rerun_status, _ = compute_run_status(rerun_result)
        try:
            update_after_run(
                project_dir,
                action=f"pipeline rerun iteration {iteration}",
                run_status=rerun_status,
                summary=f"pipeline rerun iteration {iteration} -> {rerun_status}",
            )
        except Exception as exc:
            print(f"[WARN] state update(rerun) failed: {exc}", file=sys.stderr)
        rerun_exit = 0 if rerun_status in ("SUCCESS", "SKIP") else 1
        if rerun_exit == 0:
            final_exit = 0
            break

    if run_result is None:
        print("[ERROR] Pipeline did not execute any run steps.", file=sys.stderr)
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_pipeline_logs(
        project_dir,
        timestamp,
        project_type,
        selected_template,
        effective_template,
        template_fallback_reason,
        run_result,
        fix_exit,
        rerun_exit,
        final_exit,
        opts.json_summary,
    )

    run_status, run_reason = compute_run_status(run_result)
    run_before_ok = run_status in ("SUCCESS", "SKIP")
    run_after_ok = None
    if rerun_result is not None:
        rerun_status, _ = compute_run_status(rerun_result)
        run_after_ok = rerun_status in ("SUCCESS", "SKIP")
    status = compute_status(run_before_ok, fix_exit, run_after_ok, opts.apply)

    run_prompt = _latest_run_prompt(project_dir)
    fix_prompt = _latest_path(project_dir, "fix_*.prompt.md")
    last_run = rerun_result or run_result
    artifacts = {
        "run_log": str(last_run.log_path) if last_run else None,
        "run_summary": str(last_run.summary_path) if last_run else None,
        "run_prompt": str(run_prompt) if run_prompt else None,
        "fix_prompt": str(fix_prompt) if fix_prompt else None,
        "json_summary": str(last_run.json_summary_path) if last_run and last_run.json_summary_path else None,
        "plan_md": str(plan_md_path) if plan_md_path else None,
        "plan_json": str(plan_json_path) if plan_json_path else None,
        "architecture_reasoning": str(reasoning_path) if reasoning_path else None,
        "project_spec": str(project_spec_path) if project_spec_path else None,
    }

    payload = {
        "status": status,
        "github_repo_url": None,
        "project_type": project_type,
        "selected_template": selected_template,
        "effective_template": effective_template,
        "template_fallback_reason": template_fallback_reason or None,
        "project_dir": str(project_dir),
        "timestamp": timestamp,
        "command": command,
        "current_task": (
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
            }
            if (task := current_task(project_dir)) is not None
            else None
        ),
        "steps": {
            "generate": {
                "skipped": opts.idea is None,
                "ok": opts.idea is None or project_dir.exists(),
                "detail": "used --path" if opts.idea is None else "generated from idea",
                "project_type": project_type,
                "selected_template": selected_template,
                "effective_template": effective_template,
                "template_fallback_reason": template_fallback_reason or None,
            },
            "run_before_fix": {
                "ok": run_before_ok,
                "status": run_status,
                "reason": run_reason,
                "log": str(run_result.log_path),
                "summary": str(run_result.summary_path),
                "detail": _run_component_statuses(run_result),
            },
            "fix": {
                "attempted": fix_exit is not None,
                "applied": bool(opts.apply),
                "iterations": opts.max_iterations if fix_exit is not None else 0,
                "model": opts.model,
                "scope": _effective_fix_scope(opts),
                "prompt": str(fix_prompt) if fix_prompt else None,
            },
            "run_after_fix": {
                "ok": bool(run_after_ok) if run_after_ok is not None else False,
                "log": str(rerun_result.log_path) if rerun_result else None,
                "summary": str(rerun_result.summary_path) if rerun_result else None,
                "detail": _run_component_statuses(rerun_result) if rerun_result else None,
            },
        },
        "artifacts": artifacts,
        "architecture_reasoning": architecture_reasoning or None,
    }
    evaluation_payload = None
    evaluation_path: Optional[Path] = None
    try:
        set_progress_step(
            project_dir,
            "evaluating",
            "Evaluating results",
            status="RUNNING",
            detail="final evaluation",
        )
    except Exception:
        pass
    try:
        evaluation_payload, evaluation_path = write_evaluation(project_dir)
    except Exception as exc:
        print(f"[WARN] evaluation failed: {exc}", file=sys.stderr)
    payload["evaluation"] = (
        {
            "status": evaluation_payload.get("status"),
            "path": str(evaluation_path) if evaluation_path else None,
            "checks": evaluation_payload.get("checks"),
        }
        if evaluation_payload
        else None
    )
    if evaluation_path:
        artifacts["evaluation"] = str(evaluation_path)

    auto_deploy_target = (opts.auto_deploy_target or "local").strip().lower() or "local"
    auto_deploy_status = "SKIPPED"
    auto_deploy_detail = ""
    auto_deploy_result: dict[str, Any] | None = None
    evaluation_status = ""
    if isinstance(evaluation_payload, dict):
        evaluation_status = str(evaluation_payload.get("status") or "").strip().upper()
    if opts.auto_deploy:
        if status != "SUCCESS":
            auto_deploy_status = "SKIPPED"
            auto_deploy_detail = "pipeline not successful"
        elif evaluation_status and evaluation_status != "DONE":
            auto_deploy_status = "SKIPPED"
            auto_deploy_detail = f"evaluation status {evaluation_status}"
        elif auto_deploy_target != "local":
            auto_deploy_status = "SKIPPED"
            auto_deploy_detail = "auto deploy currently supports local target only"
        else:
            try:
                auto_deploy_result = deploy_project(project_dir=project_dir, target="local", allow_real_deploy=True)
                update_after_deploy(
                    project_dir,
                    auto_deploy_result,
                    action=f"archmind pipeline auto-deploy {auto_deploy_target}",
                )
                auto_deploy_status = (
                    "SUCCESS" if str(auto_deploy_result.get("status") or "").strip().upper() == "SUCCESS" else "FAIL"
                )
                auto_deploy_detail = str(auto_deploy_result.get("detail") or "").strip()
            except Exception as exc:
                auto_deploy_status = "FAIL"
                auto_deploy_detail = f"auto deploy failed: {exc}"

    payload["auto_deploy_enabled"] = bool(opts.auto_deploy)
    payload["auto_deploy_target"] = auto_deploy_target if opts.auto_deploy else ""
    payload["auto_deploy_status"] = auto_deploy_status if opts.auto_deploy else "SKIPPED"
    payload["steps"]["auto_deploy"] = {
        "enabled": bool(opts.auto_deploy),
        "target": auto_deploy_target if opts.auto_deploy else "",
        "status": auto_deploy_status if opts.auto_deploy else "SKIPPED",
        "detail": auto_deploy_detail,
    }
    if isinstance(auto_deploy_result, dict):
        payload["auto_deploy_result"] = auto_deploy_result

    state_payload = load_state(project_dir)
    if state_payload:
        payload["state"] = {
            "last_status": state_payload.get("last_status"),
            "iterations": state_payload.get("iterations"),
            "current_task_id": state_payload.get("current_task_id"),
        }
        artifacts["state"] = str(project_dir / ".archmind" / "state.json")

    result_json, _ = write_result(project_dir, payload)
    try:
        synced_state = load_state(project_dir) or {}
        synced_state["project_type"] = project_type
        synced_state["selected_template"] = selected_template
        synced_state["effective_template"] = effective_template
        synced_state["template_fallback_reason"] = template_fallback_reason
        synced_state["architecture_app_shape"] = str(architecture_reasoning.get("app_shape") or "")
        synced_state["architecture_reason_summary"] = str(architecture_reasoning.get("reason_summary") or "")
        synced_state["architecture_recommended_template"] = str(architecture_reasoning.get("recommended_template") or "")
        synced_state["auto_deploy_enabled"] = bool(opts.auto_deploy)
        synced_state["auto_deploy_target"] = auto_deploy_target if opts.auto_deploy else ""
        synced_state["auto_deploy_status"] = auto_deploy_status if opts.auto_deploy else "SKIPPED"
        write_state(project_dir, synced_state)
    except Exception as exc:
        print(f"[WARN] state template metadata sync failed: {exc}", file=sys.stderr)

    if status == "SUCCESS" and opts.idea:
        try:
            github_repo_url = create_github_repo(project_dir)
        except Exception as exc:
            github_repo_url = None
            print(f"[WARN] github repo creation failed: {exc}", file=sys.stderr)
        if github_repo_url:
            payload["github_repo_url"] = github_repo_url
            try:
                write_result(project_dir, payload)
            except Exception as exc:
                print(f"[WARN] result github_repo_url sync failed: {exc}", file=sys.stderr)
            try:
                synced_state = load_state(project_dir) or {}
                synced_state["github_repo_url"] = github_repo_url
                write_state(project_dir, synced_state)
            except Exception as exc:
                print(f"[WARN] state github_repo_url sync failed: {exc}", file=sys.stderr)
        elif opts.idea:
            print("[WARN] github repo creation skipped/failed.", file=sys.stderr)

    try:
        finished_detail = (
            str(evaluation_payload.get("status"))
            if isinstance(evaluation_payload, dict) and evaluation_payload.get("status")
            else status
        )
        set_progress_step(
            project_dir,
            "finished",
            "Finished",
            status="DONE" if status == "SUCCESS" else "NOT_DONE",
            detail=str(finished_detail),
        )
    except Exception:
        pass

    if status != "SUCCESS":
        summary = _latest_run_summary(project_dir)
        if summary:
            print("[FAIL] 마지막 run 요약:")
            print(summary)

    if status == "SUCCESS":
        print(f"[DONE] SUCCESS. result: {result_json}")
        if opts.auto_deploy:
            print(f"[AUTO-DEPLOY] target={auto_deploy_target}")
            print(f"[AUTO-DEPLOY] status={auto_deploy_status}")
            if auto_deploy_detail:
                print(f"[AUTO-DEPLOY] detail={auto_deploy_detail}")
            if isinstance(auto_deploy_result, dict):
                kind = str(auto_deploy_result.get("kind") or "").strip().lower()
                if kind == "fullstack":
                    backend = auto_deploy_result.get("backend") if isinstance(auto_deploy_result.get("backend"), dict) else {}
                    frontend = auto_deploy_result.get("frontend") if isinstance(auto_deploy_result.get("frontend"), dict) else {}
                    backend_url = str(backend.get("url") or "").strip()
                    frontend_url = str(frontend.get("url") or "").strip()
                    if backend_url:
                        print(f"[AUTO-DEPLOY] backend_url={backend_url}")
                    if frontend_url:
                        print(f"[AUTO-DEPLOY] frontend_url={frontend_url}")
                else:
                    deploy_url = str(auto_deploy_result.get("url") or "").strip()
                    if deploy_url:
                        print(f"[AUTO-DEPLOY] url={deploy_url}")
                backend_smoke = str(auto_deploy_result.get("backend_smoke_status") or "").strip().upper()
                frontend_smoke = str(auto_deploy_result.get("frontend_smoke_status") or "").strip().upper()
                if backend_smoke:
                    print(f"[AUTO-DEPLOY] backend_smoke={backend_smoke}")
                if frontend_smoke:
                    print(f"[AUTO-DEPLOY] frontend_smoke={frontend_smoke}")
        if github_repo_url:
            print("GitHub repo:")
            print(github_repo_url)
        if state_payload:
            print(f"[STATE] {state_payload.get('last_status')} iterations={state_payload.get('iterations')}")
        if evaluation_payload:
            if evaluation_payload.get("status") == "DONE":
                print("[DONE] project complete")
            elif evaluation_payload.get("status") == "BLOCKED":
                print("[BLOCKED] manual intervention required")
            else:
                print("[INFO] further work remains")
        return 0

    print(f"[FAIL] {status}. result: {result_json}")
    if state_payload:
        print(f"[STATE] {state_payload.get('last_status')} iterations={state_payload.get('iterations')}")
    if evaluation_payload:
        if evaluation_payload.get("status") == "DONE":
            print("[DONE] project complete")
        elif evaluation_payload.get("status") == "BLOCKED":
            print("[BLOCKED] manual intervention required")
        else:
            print("[INFO] further work remains")
    return 1
