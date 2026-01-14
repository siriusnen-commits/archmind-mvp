# src/archmind/cli.py
from __future__ import annotations

import argparse
import inspect
import sys
from dataclasses import is_dataclass
from typing import Any, Callable, Dict, Optional, Sequence
from pathlib import Path

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
    base = ["fastapi", "fastapi-ddd"]
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
    r.add_argument("--cmd", default="pytest", help="Command preset (default: pytest)")
    r.add_argument("--pytest-args", default=None, help="Extra pytest arguments")
    r.add_argument("--timeout-s", type=int, default=240, help="Command timeout seconds")
    r.add_argument("--fix", action="store_true", help="Auto-fix failing tests")
    r.add_argument("--max-iter", type=int, default=3, help="Max fix iterations")
    r.add_argument("--dry-run", action="store_true", help="Print diff only (no apply)")
    r.add_argument("--auto-commit", action="store_true", help="Auto-commit on success")
    r.set_defaults(func=run_run)
    return p


def run_run(args: argparse.Namespace) -> int:
    from archmind.runner import run_project, run_project_with_fix

    project_dir = Path(args.path).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Path not found: {project_dir}", file=sys.stderr)
        return 2
    if not project_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {project_dir}", file=sys.stderr)
        return 2

    if args.fix:
        return run_project_with_fix(
            project_dir=project_dir,
            cmd=args.cmd,
            pytest_args=args.pytest_args,
            timeout_s=args.timeout_s,
            max_iter=args.max_iter,
            dry_run=args.dry_run,
            auto_commit=args.auto_commit,
        )

    return run_project(
        project_dir=project_dir,
        cmd=args.cmd,
        pytest_args=args.pytest_args,
        timeout_s=args.timeout_s,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    # ✅ 여기서 “출력 없이 EXIT=0” 문제를 원천 차단
    if not argv:
        parser.print_help()
        return 0

    args = parser.parse_args(list(argv))

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
