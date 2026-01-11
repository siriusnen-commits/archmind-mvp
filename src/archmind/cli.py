# src/archmind/cli.py
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .generator import GenerateOptions, apply_template, generate_valid_spec, write_project


DEFAULT_PROMPT = Path("docs/architecture_prompt.md")


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="archmind")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate a runnable project from an idea")
    g.add_argument("--idea", required=True, help="Product idea in plain text")
    g.add_argument("--out", default="generated", help="Output root directory")
    g.add_argument("--force", action="store_true", help="Overwrite existing project folder")
    g.add_argument("--name", default=None, help="Override project name (folder name)")
    g.add_argument(
        "--template",
        default="fastapi",
        choices=["fastapi", "fastapi-ddd"],
        help="Project template",
    )
    g.add_argument("--prompt", default=str(DEFAULT_PROMPT), help="Prompt file path")
    g.add_argument("--model", default="llama3:latest", help="Ollama model name")
    g.add_argument("--ollama-base-url", default="http://localhost:11434", help="Ollama base URL")

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    try:
        prompt_text = _read_text(Path(args.prompt))
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        print("Hint: run from repo root, or pass --prompt docs/architecture_prompt.md", file=sys.stderr)
        return 2

    opt = GenerateOptions(
        out=Path(args.out),
        force=bool(args.force),
        name=args.name,
        template=args.template,
        model=args.model,
        ollama_base_url=args.ollama_base_url,
    )

    # 1) LLM으로 spec 생성
    spec = generate_valid_spec(prompt_text, args.idea, opt)

    # 2) 템플릿으로 프로젝트 구조 강제(여기서 project_name도 opt.name 우선으로 고정됨)
    spec = apply_template(spec, opt)

    # 3) 파일/폴더 생성
    project_root = write_project(spec, opt)

    print(f"[OK] Generated project: {project_root}")
    print(f"[OK] Model={opt.model}, template={opt.template}")

    print("\nNext steps:")
    print(f"  cd {project_root}")
    print("  python3 -m venv .venv && source .venv/bin/activate")
    print("  python -m pip install -r requirements.txt")

    if opt.template == "fastapi-ddd":
        print("  pytest -q")
        print("  uvicorn app.main:app --reload --port 8000")
    else:
        print("  PORT=8000 python main.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())