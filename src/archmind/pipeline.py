from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.fixer import run_fix_loop
from archmind.generator import GenerateOptions, generate_project
from archmind.runner import RunConfig, RunResult, run_pipeline


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
    timeout_s: int
    scope: str
    max_iterations: int
    model: str
    apply: bool
    dry_run: bool
    json_summary: bool


def _resolve_project_dir(opts: PipelineOptions) -> Optional[Path]:
    if opts.idea:
        opt_kwargs = _build_generate_options_kwargs(opts)
        opt = GenerateOptions(**opt_kwargs)
        generated = generate_project(opts.idea, opt)
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

    project_dir = _resolve_project_dir(opts)
    if project_dir is None:
        print("[ERROR] Provide --path or --idea for pipeline.", file=sys.stderr)
        return 2

    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 2

    run_config = _build_run_config(opts, project_dir)

    final_exit = 1
    fix_exit: Optional[int] = None
    rerun_exit: Optional[int] = None
    run_result: Optional[RunResult] = None

    for iteration in range(1, opts.max_iterations + 1):
        run_result = run_pipeline(run_config)
        if run_result.overall_exit_code == 0:
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
        )
        if fix_exit != 0:
            final_exit = 1
            break

        rerun_result = run_pipeline(run_config)
        rerun_exit = rerun_result.overall_exit_code
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

    if final_exit != 0:
        summary = _latest_run_summary(project_dir)
        if summary:
            print("[FAIL] 마지막 run 요약:")
            print(summary)

    return final_exit
