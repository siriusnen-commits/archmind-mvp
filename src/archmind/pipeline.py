from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.fixer import run_fix_loop
from archmind.runner import RunConfig, RunResult, compute_run_status, run_pipeline


@dataclass
class PipelineOptions:
    idea: Optional[str]
    path: Optional[Path]
    out: str
    name: Optional[str]
    template: str
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


def _resolve_project_dir(opts: PipelineOptions) -> Optional[Path]:
    if opts.idea:
        opt_kwargs = _build_generate_options_kwargs(opts)
        opt = _make_generate_options(opt_kwargs)
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
    lines = [
        "ArchMind Pipeline Result",
        f"- status: {payload.get('status')}",
        f"- project_dir: {payload.get('project_dir')}",
        f"- timestamp: {payload.get('timestamp')}",
        f"- command: {payload.get('command')}",
        "",
        "Steps:",
        f"- generate: {payload['steps']['generate']}",
        f"- run_before_fix: {payload['steps']['run_before_fix']}",
        f"- fix: {payload['steps']['fix']}",
        f"- run_after_fix: {payload['steps']['run_after_fix']}",
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
            "meta": {"project_dir": str(project_dir), "timestamp": timestamp},
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


def run_pipeline_command(opts: PipelineOptions) -> int:
    if opts.dry_run:
        steps = []
        if opts.idea:
            steps.append("generate")
        steps.append("run")
        steps.append("fix (on failure)")
        steps.append("run (after fix)")
        print("[DRY-RUN] pipeline plan:")
        for step in steps:
            print(f"- {step}")
        return 0

    if opts.profile in ("generic", "generic-shell") and not opts.cmds:
        print("[ERROR] --profile generic-shell requires at least one --cmd.", file=sys.stderr)
        return 64

    project_dir = _resolve_project_dir(opts)
    if project_dir is None:
        print("[ERROR] Provide --path or --idea for pipeline.", file=sys.stderr)
        return 2

    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 2

    run_config = _build_run_config(opts, project_dir)
    command = _build_command(opts)

    final_exit = 1
    fix_exit: Optional[int] = None
    rerun_exit: Optional[int] = None
    rerun_result: Optional[RunResult] = None
    run_result: Optional[RunResult] = None

    for iteration in range(1, opts.max_iterations + 1):
        run_result = run_pipeline(run_config)
        run_status, _ = compute_run_status(run_result)
        if run_status in ("SUCCESS", "SKIP"):
            final_exit = 0
            break

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
        if fix_exit != 0:
            final_exit = 1
            break

        rerun_result = run_pipeline(run_config)
        rerun_status, _ = compute_run_status(rerun_result)
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
    }

    payload = {
        "status": status,
        "project_dir": str(project_dir),
        "timestamp": timestamp,
        "command": command,
        "steps": {
            "generate": {
                "skipped": opts.idea is None,
                "ok": opts.idea is None or project_dir.exists(),
                "detail": "used --path" if opts.idea is None else "generated from idea",
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
    }

    result_json, _ = write_result(project_dir, payload)

    if status != "SUCCESS":
        summary = _latest_run_summary(project_dir)
        if summary:
            print("[FAIL] 마지막 run 요약:")
            print(summary)

    if status == "SUCCESS":
        print(f"[DONE] SUCCESS. result: {result_json}")
        return 0

    print(f"[FAIL] {status}. result: {result_json}")
    return 1
