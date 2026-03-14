# src/archmind/cli.py
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from dataclasses import is_dataclass
from typing import Any, Callable, Dict, Optional, Sequence
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version


def _get_version() -> str:
    try:
        return version("archmind")
    except PackageNotFoundError:
        return "0.0.0"

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Pass only kwargs that 'fn' accepts."""
    sig = inspect.signature(fn)
    accepted = set(sig.parameters.keys())
    return {k: v for k, v in kwargs.items() if k in accepted}


def _make_generate_options(**kwargs: Any) -> Any:
    """
    Create GenerateOptions while tolerating field-name mismatches.
    (Only passes keys that GenerateOptions.__init__ accepts.)
    """
    from archmind.generator import GenerateOptions  # type: ignore

    # dataclass or normal class 모두 대응
    init = GenerateOptions.__init__  # type: ignore[attr-defined]
    filtered = _filter_kwargs_for_callable(init, kwargs)
    return GenerateOptions(**filtered)


def _resolve_generator_entry() -> Callable[..., Any]:
    """
    Find a callable generator entrypoint in archmind.generator.
    Supports multiple historical function names.
    """
    import archmind.generator as gen  # type: ignore

    candidates = [
        "generate_project",         # ideal
        "generate",                 # common alt
        "generate_from_idea",
        "generate_project_from_idea",
        "run_generate",
    ]
    for name in candidates:
        fn = getattr(gen, name, None)
        if callable(fn):
            return fn

    # last resort: scan module for something callable that looks right
    for name, obj in vars(gen).items():
        if callable(obj) and name.startswith("generate"):
            return obj

    raise RuntimeError(
        "No generator entrypoint found in archmind.generator. "
        "Expected one of: generate_project / generate / generate_from_idea / generate_project_from_idea."
    )


def _templates_choices() -> list[str]:
    """
    Provide template choices. If a template module exists, include it.
    """
    base = ["fastapi", "fastapi-ddd", "nextjs"]
    try:
        # optional template
        import archmind.templates.fullstack_ddd  # noqa: F401
        if "fullstack-ddd" not in base:
            base.append("fullstack-ddd")
    except Exception:
        pass
    return base


def run_generate(args: argparse.Namespace) -> int:
    gen_entry = _resolve_generator_entry()

    # Build GenerateOptions safely (only accepted kwargs will be passed)
    opt = _make_generate_options(
        out=Path(args.out),
        force=args.force,
        name=args.name,
        template=args.template,
        prompt=args.prompt,
        model=args.model,
        base_url=args.ollama_base_url,
        ollama_base_url=args.ollama_base_url,
        max_retries=args.max_retries,
        timeout_s=args.timeout_s,
    )

    # Call generator entry with best-effort signature matching
    # 가능한 시그니처:
    # - fn(idea: str, opt: GenerateOptions) -> Path
    # - fn(prompt: str, idea: str, opt: GenerateOptions) ...
    # - fn(spec/prompt/idea..., opt=...) 등
    call_kwargs = {
        "idea": args.idea,
        "prompt": args.prompt,
        "opt": opt,
        "options": opt,
    }

    # positional-first 시도
    try_orders = [
        (args.idea, opt),
        (args.prompt, args.idea, opt),
        (args.idea,),
        (),
    ]

    # 1) positional 시도
    for tup in try_orders:
        try:
            return_value = gen_entry(*tup)
            # generate가 Path를 리턴해도 OK. print는 generator가 하거나, 여기서 해도 됨.
            if isinstance(return_value, int):
                return return_value
            if return_value is not None:
                print(f"[OK] Generated project: {return_value}")
            return 0
        except TypeError:
            pass

    # 2) keyword 시도 (fn이 받는 것만 필터)
    filtered = _filter_kwargs_for_callable(gen_entry, call_kwargs)
    try:
        return_value = gen_entry(**filtered)
        if isinstance(return_value, int):
            return return_value
        if return_value is not None:
            print(f"[OK] Generated project: {return_value}")
        return 0
    except TypeError as e:
        raise SystemExit(f"[ERROR] Could not call generator entry: {e}") from e


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="archmind", description="ArchMind CLI")
    p.add_argument("--version", action="version", version=f"archmind {_get_version()}")
    sub = p.add_subparsers(dest="cmd")

    g = sub.add_parser("generate", help="Generate a runnable project from an idea")
    g.add_argument("--idea", required=True, help="Project idea (free text)")
    g.add_argument("--out", default="generated_test", help="Output directory base")
    g.add_argument("--force", action="store_true", help="Overwrite if exists")
    g.add_argument("--name", default=None, help="Project name (folder name)")
    g.add_argument("--template", default="fastapi", choices=_templates_choices(), help="Template name")
    g.add_argument("--prompt", default=None, help="Override system prompt (advanced)")
    g.add_argument("--model", default="llama3:latest", help="Ollama model name")
    g.add_argument("--ollama-base-url", default="http://127.0.0.1:11434", help="Ollama base URL")
    g.add_argument("--max-retries", type=int, default=3, help="Max retries for model/spec generation")
    g.add_argument("--timeout-s", type=int, default=240, help="HTTP timeout seconds for Ollama calls")

    g.set_defaults(func=run_generate)

    r = sub.add_parser("run", help="Run tests in a project and collect logs")
    r.add_argument("--path", required=True, help="Project root path")
    r.add_argument("--all", action="store_true", help="Run backend + frontend checks")
    r.add_argument("--backend-only", action="store_true", help="Run backend checks only")
    r.add_argument("--frontend-only", action="store_true", help="Run frontend checks only")
    r.add_argument(
        "--profile",
        choices=["python-pytest", "node-vite", "generic-shell", "generic"],
        default=None,
        help="Run a named profile (overrides legacy backend/frontend flags)",
    )
    r.add_argument(
        "--cmd",
        action="append",
        default=[],
        help="Command for generic-shell profile (can be repeated)",
    )
    r.add_argument("--no-install", action="store_true", help="Skip frontend install step")
    r.add_argument("--timeout-s", type=int, default=240, help="Timeout per command")
    r.add_argument("--log-dir", default=None, help="Log directory (relative to project or absolute)")
    r.add_argument("--json-summary", action="store_true", help="Write summary.json alongside summary.txt")
    r.set_defaults(func=run_run)

    f = sub.add_parser("fix", help="Run auto-fix loop with plans")
    f.add_argument("--path", required=True, help="Project root path")
    f.add_argument("--max-iterations", type=int, default=3, help="Max fix iterations")
    f.add_argument("--model", choices=["ollama", "openai", "none"], default="ollama", help="Patch model")
    f.add_argument("--ollama-model", default="llama3:latest", help="Ollama model name")
    f.add_argument("--openai-model", default="gpt-4.1-mini", help="OpenAI model name")
    f.add_argument("--dry-run", action="store_true", help="Plan only, no changes")
    f.add_argument("--timeout-s", type=int, default=240, help="Timeout per step")
    f.add_argument("--scope", choices=["backend", "frontend", "all"], default="all", help="Fix scope")
    f.add_argument(
        "--profile",
        choices=["python-pytest", "node-vite", "generic-shell", "generic"],
        default=None,
        help="Run a named profile during fix loop",
    )
    f.add_argument(
        "--cmd",
        action="append",
        default=[],
        help="Command for generic-shell profile (can be repeated)",
    )
    f.add_argument("--apply", action="store_true", help="Apply changes (required to modify files)")
    f.set_defaults(func=run_fix)

    ppipe = sub.add_parser("pipeline", help="Generate -> run -> fix -> run pipeline")
    ppipe.add_argument("--path", default=None, help="Existing project path (skip generate)")
    ppipe.add_argument("--idea", default=None, help="Project idea (generate step)")
    ppipe.add_argument("--out", default="generated_test", help="Output directory base")
    ppipe.add_argument("--name", default=None, help="Project name (folder name)")
    ppipe.add_argument("--template", default="fastapi", choices=_templates_choices(), help="Template name")
    ppipe.add_argument("--prompt", default=None, help="Override system prompt (advanced)")
    ppipe.add_argument("--gen-model", default="llama3:latest", help="Ollama model name for generate")
    ppipe.add_argument("--gen-ollama-base-url", default="http://127.0.0.1:11434", help="Ollama base URL")
    ppipe.add_argument("--gen-max-retries", type=int, default=3, help="Max retries for model/spec generation")
    ppipe.add_argument("--gen-timeout-s", type=int, default=240, help="HTTP timeout seconds for generate calls")
    ppipe.add_argument("--all", action="store_true", help="Run backend + frontend checks")
    ppipe.add_argument("--backend-only", action="store_true", help="Run backend checks only")
    ppipe.add_argument("--frontend-only", action="store_true", help="Run frontend checks only")
    ppipe.add_argument(
        "--profile",
        choices=["python-pytest", "node-vite", "generic-shell", "generic"],
        default=None,
        help="Run a named profile instead of legacy backend/frontend checks",
    )
    ppipe.add_argument(
        "--cmd",
        action="append",
        default=[],
        help="Command for generic-shell profile (can be repeated)",
    )
    ppipe.add_argument("--no-install", action="store_true", help="Skip frontend install step")
    ppipe.add_argument("--timeout-s", type=int, default=240, help="Timeout per step")
    ppipe.add_argument("--scope", choices=["backend", "frontend", "all"], default="all", help="Fix scope")
    ppipe.add_argument("--max-iterations", type=int, default=3, help="Max fix iterations")
    ppipe.add_argument("--model", choices=["ollama", "openai", "none"], default="ollama", help="Patch model")
    ppipe.add_argument("--apply", action="store_true", help="Apply fix changes")
    ppipe.add_argument("--dry-run", action="store_true", help="Plan only, no execution")
    ppipe.add_argument("--json-summary", action="store_true", help="Write pipeline summary.json")
    ppipe.add_argument("--auto-deploy", action="store_true", help="After successful pipeline, auto deploy (local only)")
    ppipe.add_argument("--deploy-target", default="local", help="Auto deploy target (currently: local)")
    ppipe.set_defaults(func=run_pipeline_cmd)

    d = sub.add_parser("deploy", help="Deploy a project to a target provider")
    d.add_argument("--path", required=True, help="Project root path")
    d.add_argument("--target", default="railway", help="Deploy target (phase 1: railway)")
    d.add_argument("--allow-real-deploy", action="store_true", help="Allow non-mock deploy path")
    d.set_defaults(func=run_deploy)

    s = sub.add_parser("stop", help="Stop local services started by local deploy")
    s.add_argument("--path", required=True, help="Project root path")
    s.set_defaults(func=run_stop)

    rs = sub.add_parser("restart", help="Restart local services started by local deploy")
    rs.add_argument("--path", required=True, help="Project root path")
    rs.set_defaults(func=run_restart)

    dp = sub.add_parser("delete-project", help="Delete project resources (local/repo/all)")
    dp.add_argument("--path", required=True, help="Project root path")
    dp.add_argument("--mode", choices=["local", "repo", "all"], default="local", help="Deletion mode")
    dp.add_argument("--confirm", action="store_true", help="Required for destructive repo/all deletion")
    dp.set_defaults(func=run_delete_project)

    rn = sub.add_parser("running", help="List running local services across projects")
    rn.add_argument("--projects-dir", default=None, help="Projects root directory (defaults to ARCHMIND_PROJECTS_DIR)")
    rn.set_defaults(func=run_running)

    lg = sub.add_parser("logs", help="Show local service logs")
    lg.add_argument("--path", required=True, help="Project root path")
    lg.add_argument("--local", action="store_true", help="Read local runtime logs")
    lg.add_argument("--backend", action="store_true", help="Show backend local logs")
    lg.add_argument("--frontend", action="store_true", help="Show frontend local logs")
    lg.set_defaults(func=run_logs)

    pl = sub.add_parser("plan", help="Generate project plan artifacts")
    pl.add_argument("--idea", required=True, help="Plan idea / goal")
    pl.add_argument("--path", default=".", help="Existing project path")
    pl.set_defaults(func=run_plan)

    t = sub.add_parser("tasks", help="List tasks and initialize from plan when missing")
    t.add_argument("--path", required=True, help="Project root path")
    t.set_defaults(func=run_tasks)

    n = sub.add_parser("next", help="Show next pending task")
    n.add_argument("--path", required=True, help="Project root path")
    n.set_defaults(func=run_next)

    c = sub.add_parser("complete", help="Update task status")
    c.add_argument("--path", required=True, help="Project root path")
    c.add_argument("--id", required=True, type=int, help="Task id")
    c.add_argument("--blocked", action="store_true", help="Mark task as blocked")
    c.add_argument("--doing", action="store_true", help="Mark task as doing")
    c.set_defaults(func=run_complete)

    ev = sub.add_parser("evaluate", help="Evaluate project completion state")
    ev.add_argument("--path", required=True, help="Project root path")
    ev.set_defaults(func=run_evaluate)

    st = sub.add_parser("state", help="Show state memory summary")
    st.add_argument("--path", required=True, help="Project root path")
    st.add_argument("--json", action="store_true", help="Print raw state.json")
    st.set_defaults(func=run_state)
    return p


def run_run(args: argparse.Namespace) -> int:
    from archmind.environment import ensure_environment_readiness
    from archmind.runner import RunConfig, compute_run_status, print_run_result, run_pipeline
    from archmind.state import set_agent_state, update_after_run

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    if not args.profile and sum(bool(x) for x in (args.all, args.backend_only, args.frontend_only)) > 1:
        print("[ERROR] Use only one of --all/--backend-only/--frontend-only.", file=sys.stderr)
        return 64

    if args.profile in ("generic", "generic-shell") and not args.cmd:
        print("[ERROR] --profile generic-shell requires at least one --cmd.", file=sys.stderr)
        return 64

    if args.log_dir:
        log_dir = Path(args.log_dir)
        if not log_dir.is_absolute():
            log_dir = (project_dir / log_dir).resolve()
    else:
        log_dir = project_dir / ".archmind" / "run_logs"

    command = "archmind " + " ".join(getattr(args, "_argv", []))
    ensure_environment_readiness(project_dir)
    set_agent_state(project_dir, "RUNNING", action=command.strip(), summary="run started")
    config = RunConfig(
        project_dir=project_dir,
        run_all=args.all,
        backend_only=args.backend_only,
        frontend_only=args.frontend_only,
        no_install=args.no_install,
        timeout_s=args.timeout_s,
        log_dir=log_dir,
        json_summary=args.json_summary,
        command=command.strip(),
        profile=args.profile,
        cmds=args.cmd,
    )

    result = run_pipeline(config)
    print_run_result(result)
    run_status, run_reason = compute_run_status(result)
    update_after_run(
        project_dir,
        action=command.strip(),
        run_status=run_status,
        summary=run_reason or f"run finished with {run_status}",
    )
    return result.overall_exit_code


def run_fix(args: argparse.Namespace) -> int:
    from archmind.fixer import run_fix_loop
    from archmind.state import set_agent_state, update_after_fix

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64
    structure_ok = any(
        (
            (project_dir / "pytest.ini").exists(),
            (project_dir / "tests").exists(),
            (project_dir / "app").exists(),
            (project_dir / "frontend" / "package.json").exists(),
        )
    )
    if not structure_ok:
        print(f"[ERROR] Path does not look like a project root: {project_dir}", file=sys.stderr)
        return 64

    if args.profile in ("generic", "generic-shell") and not args.cmd:
        print("[ERROR] --profile generic-shell requires at least one --cmd.", file=sys.stderr)
        return 64

    command = "archmind " + " ".join(getattr(args, "_argv", []))
    try:
        set_agent_state(project_dir, "FIXING", action=command.strip(), summary="fix started")
        exit_code = run_fix_loop(
            project_dir=project_dir,
            max_iterations=args.max_iterations,
            model=args.model,
            dry_run=args.dry_run,
            timeout_s=args.timeout_s,
            scope=args.scope,
            apply_changes=args.apply,
            command=command.strip(),
            profile=args.profile,
            cmds=args.cmd,
        )
        update_after_fix(project_dir, action=command.strip(), exit_code=exit_code)
        return exit_code
    except Exception as exc:
        set_agent_state(project_dir, "FAILED", action=command.strip(), summary=f"fix failed: {exc}", record_history=True)
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 70


def run_pipeline_cmd(args: argparse.Namespace) -> int:
    from archmind.pipeline import PipelineOptions, run_pipeline_command

    if args.path:
        path = Path(args.path).expanduser().resolve()
    else:
        path = None

    opts = PipelineOptions(
        idea=args.idea,
        path=path,
        out=args.out,
        name=args.name,
        template=args.template,
        template_explicit="--template" in list(getattr(args, "_argv", [])),
        prompt=args.prompt,
        gen_model=args.gen_model,
        gen_ollama_base_url=args.gen_ollama_base_url,
        gen_max_retries=args.gen_max_retries,
        gen_timeout_s=args.gen_timeout_s,
        run_all=args.all,
        backend_only=args.backend_only,
        frontend_only=args.frontend_only,
        no_install=args.no_install,
        profile=args.profile,
        cmds=args.cmd,
        timeout_s=args.timeout_s,
        scope=args.scope,
        max_iterations=args.max_iterations,
        model=args.model,
        apply=args.apply,
        dry_run=args.dry_run,
        json_summary=args.json_summary,
        auto_deploy=bool(args.auto_deploy),
        auto_deploy_target=str(args.deploy_target or "local"),
    )

    return run_pipeline_command(opts)


def run_deploy(args: argparse.Namespace) -> int:
    from archmind.deploy import deploy_project
    from archmind.state import update_after_deploy

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    command = "archmind " + " ".join(getattr(args, "_argv", []))
    result = deploy_project(
        project_dir=project_dir,
        target=args.target,
        allow_real_deploy=bool(args.allow_real_deploy),
    )
    update_after_deploy(project_dir, result, action=command.strip())

    print(f"[DEPLOY] target={result.get('target') or args.target}")
    print(f"[DEPLOY] mode={result.get('mode') or 'mock'}")
    kind = str(result.get("kind") or "backend").strip().lower()
    print(f"[DEPLOY] kind={kind}")
    if kind == "fullstack":
        backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
        frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
        print()
        print(f"[BACKEND] status={backend.get('status') or 'UNKNOWN'}")
        backend_url = str(backend.get("url") or "").strip()
        if backend_url:
            print(f"[BACKEND] url={backend_url}")
        backend_detail = str(backend.get("detail") or "").strip()
        if backend_detail:
            print(f"[BACKEND] detail={backend_detail}")
        backend_smoke_url = str(result.get("backend_smoke_url") or "").strip()
        backend_smoke_status = str(result.get("backend_smoke_status") or "").strip().upper()
        backend_smoke_detail = str(result.get("backend_smoke_detail") or "").strip()
        if backend_smoke_url:
            print(f"[BACKEND-SMOKE] url={backend_smoke_url}")
        if backend_smoke_status:
            print(f"[BACKEND-SMOKE] status={backend_smoke_status}")
        if backend_smoke_detail:
            print(f"[BACKEND-SMOKE] detail={backend_smoke_detail}")

        print()
        print(f"[FRONTEND] status={frontend.get('status') or 'UNKNOWN'}")
        frontend_url = str(frontend.get("url") or "").strip()
        if frontend_url:
            print(f"[FRONTEND] url={frontend_url}")
        frontend_detail = str(frontend.get("detail") or "").strip()
        if frontend_detail:
            print(f"[FRONTEND] detail={frontend_detail}")
        frontend_smoke_url = str(result.get("frontend_smoke_url") or "").strip()
        frontend_smoke_status = str(result.get("frontend_smoke_status") or "").strip().upper()
        frontend_smoke_detail = str(result.get("frontend_smoke_detail") or "").strip()
        if frontend_smoke_url:
            print(f"[FRONTEND-SMOKE] url={frontend_smoke_url}")
        if frontend_smoke_status:
            print(f"[FRONTEND-SMOKE] status={frontend_smoke_status}")
        if frontend_smoke_detail:
            print(f"[FRONTEND-SMOKE] detail={frontend_smoke_detail}")
    else:
        print(f"[DEPLOY] status={result.get('status') or 'UNKNOWN'}")
        if result.get("url"):
            print(f"[DEPLOY] url={result.get('url')}")
        detail = str(result.get("detail") or "").strip()
        if detail:
            print(f"[DEPLOY] detail={detail}")
        health_status = str(result.get("healthcheck_status") or "").strip().upper()
        if health_status:
            health_url = str(result.get("healthcheck_url") or "").strip()
            if health_url:
                print(f"[HEALTH] url={health_url}")
            print(f"[HEALTH] status={health_status}")
            health_detail = str(result.get("healthcheck_detail") or "").strip()
            if health_detail:
                print(f"[HEALTH] detail={health_detail}")
        backend_smoke_url = str(result.get("backend_smoke_url") or "").strip()
        backend_smoke_status = str(result.get("backend_smoke_status") or "").strip().upper()
        backend_smoke_detail = str(result.get("backend_smoke_detail") or "").strip()
        frontend_smoke_url = str(result.get("frontend_smoke_url") or "").strip()
        frontend_smoke_status = str(result.get("frontend_smoke_status") or "").strip().upper()
        frontend_smoke_detail = str(result.get("frontend_smoke_detail") or "").strip()
        if backend_smoke_url:
            print(f"[BACKEND-SMOKE] url={backend_smoke_url}")
        if backend_smoke_status:
            print(f"[BACKEND-SMOKE] status={backend_smoke_status}")
        if backend_smoke_detail:
            print(f"[BACKEND-SMOKE] detail={backend_smoke_detail}")
        if frontend_smoke_url:
            print(f"[FRONTEND-SMOKE] url={frontend_smoke_url}")
        if frontend_smoke_status:
            print(f"[FRONTEND-SMOKE] status={frontend_smoke_status}")
        if frontend_smoke_detail:
            print(f"[FRONTEND-SMOKE] detail={frontend_smoke_detail}")

    return 0 if bool(result.get("ok")) else 1


def run_stop(args: argparse.Namespace) -> int:
    from archmind.deploy import stop_local_services

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    result = stop_local_services(project_dir)
    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}

    backend_status = str(backend.get("status") or "NOT RUNNING")
    frontend_status = str(frontend.get("status") or "NOT RUNNING")
    print(f"[STOP] backend {backend_status.lower()}")
    backend_detail = str(backend.get("detail") or "").strip()
    if backend_detail:
        print(f"[STOP] backend detail={backend_detail}")
    print(f"[STOP] frontend {frontend_status.lower()}")
    frontend_detail = str(frontend.get("detail") or "").strip()
    if frontend_detail:
        print(f"[STOP] frontend detail={frontend_detail}")
    return 0


def run_running(args: argparse.Namespace) -> int:
    from archmind.deploy import list_running_local_projects

    if args.projects_dir:
        projects_root = Path(args.projects_dir).expanduser().resolve()
    else:
        raw = os.getenv("ARCHMIND_PROJECTS_DIR", "").strip()
        projects_root = Path(raw).expanduser().resolve() if raw else (Path.home() / "archmind-telegram-projects")

    rows = list_running_local_projects(projects_root)
    if not rows:
        print("No local services running.")
        return 0

    for item in rows:
        name = str(item.get("project_name") or "")
        backend = item.get("backend") if isinstance(item.get("backend"), dict) else {}
        frontend = item.get("frontend") if isinstance(item.get("frontend"), dict) else {}
        print(f"[RUNNING] {name}")
        backend_status = str(backend.get("status") or "NOT RUNNING")
        backend_pid = backend.get("pid")
        backend_url = str(backend.get("url") or "").strip()
        print(f"  backend: {backend_status} pid={backend_pid} url={backend_url or '-'}")
        frontend_status = str(frontend.get("status") or "NOT RUNNING")
        frontend_pid = frontend.get("pid")
        frontend_url = str(frontend.get("url") or "").strip()
        print(f"  frontend: {frontend_status} pid={frontend_pid} url={frontend_url or '-'}")
    return 0


def run_logs(args: argparse.Namespace) -> int:
    from archmind.deploy import read_last_lines

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    if not args.local:
        print("[ERROR] Only --local logs are supported in this command.", file=sys.stderr)
        return 64

    show_backend = bool(args.backend)
    show_frontend = bool(args.frontend)
    if not show_backend and not show_frontend:
        show_backend = True
        show_frontend = True

    backend_text = read_last_lines(project_dir / ".archmind" / "backend.log", lines=20) if show_backend else None
    frontend_text = read_last_lines(project_dir / ".archmind" / "frontend.log", lines=20) if show_frontend else None
    if (show_backend and not backend_text) and (show_frontend and not frontend_text):
        print("No logs available.")
        return 0

    if show_backend:
        print("[BACKEND LOGS]")
        print(backend_text or "No logs available.")
        if show_frontend:
            print()
    if show_frontend:
        print("[FRONTEND LOGS]")
        print(frontend_text or "No logs available.")
    return 0


def run_restart(args: argparse.Namespace) -> int:
    from archmind.deploy import restart_local_services

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    result = restart_local_services(project_dir)
    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
    backend_status = str(backend.get("status") or "NOT RUNNING")
    frontend_status = str(frontend.get("status") or "NOT RUNNING")
    print(f"[RESTART] backend {backend_status.lower()}")
    backend_detail = str(backend.get("detail") or "").strip()
    if backend_detail and backend_status.upper() == "FAIL":
        print(f"[RESTART] backend detail={backend_detail}")
    print(f"[RESTART] frontend {frontend_status.lower()}")
    frontend_detail = str(frontend.get("detail") or "").strip()
    if frontend_detail and frontend_status.upper() == "FAIL":
        print(f"[RESTART] frontend detail={frontend_detail}")
    return 0


def run_delete_project(args: argparse.Namespace) -> int:
    from archmind.deploy import delete_project

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    mode = str(args.mode or "local").strip().lower()
    if mode in ("repo", "all") and not bool(args.confirm):
        print(f"[DELETE] confirmation required for {mode} deletion. Re-run with --confirm")
        return 1

    result = delete_project(project_dir, mode=mode)
    local_status = str(result.get("local_status") or "UNCHANGED").upper()
    repo_status = str(result.get("repo_status") or "UNCHANGED").upper()
    local_detail = str(result.get("local_detail") or "").strip()
    repo_detail = str(result.get("repo_detail") or "").strip()

    if mode == "local":
        if local_status == "DELETED":
            print("[DELETE] local project deleted")
        else:
            print(f"[DELETE] local deletion status: {local_status}")
            if local_detail:
                print(f"[DELETE] local deletion detail: {local_detail}")
        return 0 if bool(result.get("ok")) else 1

    if mode == "repo":
        if repo_status == "DELETED":
            print("[DELETE] github repo deleted")
        else:
            print(f"[DELETE] repo deletion failed: {repo_detail or repo_status.lower()}")
        return 0 if bool(result.get("ok")) else 1

    if bool(result.get("ok")):
        print("[DELETE] all resources deleted")
    else:
        print("[DELETE] all deletion completed with errors")
    print(f"[DELETE] local: {local_status}")
    print(f"[DELETE] repo: {repo_status}")
    if local_detail and local_status != "DELETED":
        print(f"[DELETE] local detail: {local_detail}")
    if repo_detail and repo_status != "DELETED":
        print(f"[DELETE] repo detail: {repo_detail}")
    return 0 if bool(result.get("ok")) else 1


def run_plan(args: argparse.Namespace) -> int:
    from archmind.planner import write_project_plan

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 64
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    artifacts = write_project_plan(project_dir, args.idea)
    print(f"[OK] plan markdown: {artifacts.plan_md_path}")
    print(f"[OK] plan json: {artifacts.plan_json_path}")
    return 0


def run_tasks(args: argparse.Namespace) -> int:
    from archmind.tasks import format_task_line, list_tasks

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    tasks = list_tasks(project_dir)
    if not tasks:
        print("no tasks")
        return 0
    for task in tasks:
        print(format_task_line(task))
    return 0


def run_next(args: argparse.Namespace) -> int:
    from archmind.tasks import next_task

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    task = next_task(project_dir)
    if task is None:
        print("no pending tasks")
        return 0
    print(f"NEXT: [{task.id}] {task.title}")
    return 0


def run_complete(args: argparse.Namespace) -> int:
    from archmind.tasks import update_task_status
    from archmind.state import sync_from_tasks

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    selected = "done"
    if args.blocked:
        selected = "blocked"
    elif args.doing:
        selected = "doing"

    task = update_task_status(project_dir, args.id, selected)
    if task is None:
        print(f"[ERROR] task id not found: {args.id}", file=sys.stderr)
        return 64
    sync_from_tasks(project_dir, action=f"complete --id {task.id}", status="UNKNOWN")
    print(f"UPDATED: [{task.id}] -> {task.status}")
    return 0


def run_evaluate(args: argparse.Namespace) -> int:
    from archmind.evaluator import format_evaluation_summary, write_evaluation

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64

    payload, eval_path = write_evaluation(project_dir)
    print(format_evaluation_summary(payload))
    print(f"[OK] evaluation: {eval_path}")
    return 0


def run_state(args: argparse.Namespace) -> int:
    from archmind.state import ensure_state, format_state_text, state_path

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 64
    payload = ensure_state(project_dir)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(format_state_text(project_dir))
    print(f"[OK] state: {state_path(project_dir)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    # ✅ 여기서 “출력 없이 EXIT=0” 문제를 원천 차단
    if not argv:
        parser.print_help()
        return 0

    args = parser.parse_args(list(argv))
    setattr(args, "_argv", list(argv))

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return int(args.func(args))
    except SystemExit:
        raise
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
