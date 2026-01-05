# src/archmind/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .generator import GenerateOptions, apply_template, generate_valid_spec, write_project


DEFAULT_PROMPT = Path("docs/architecture_prompt.md")


def main():
    ap = argparse.ArgumentParser(prog="archmind")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate a runnable project from an idea")
    g.add_argument("--idea", required=True, help="Product idea in plain text")
    g.add_argument("--out", default="generated", help="Output root directory")
    g.add_argument("--force", action="store_true", help="Overwrite existing files")
    g.add_argument("--name", default=None, help="Override project name (folder name)")
    g.add_argument("--template", default="fastapi", choices=["fastapi", "fastapi-ddd"], help="Project template")
    g.add_argument("--prompt", default=str(DEFAULT_PROMPT), help="Prompt file path")
    g.add_argument("--model", default="llama3:latest", help="Ollama model name")
    g.add_argument("--ollama-base-url", default="http://localhost:11434", help="Ollama base URL")

    args = ap.parse_args()

    prompt_text = Path(args.prompt).read_text(encoding="utf-8")

    opt = GenerateOptions(
        out=Path(args.out),
        force=args.force,
        name=args.name,
        template=args.template,
        model=args.model,
        ollama_base_url=args.ollama_base_url,
    )

    spec = generate_valid_spec(prompt_text, args.idea, opt)

    # CLI --name always wins (final override)
    if args.name:
        spec["project_name"] = args.name

    spec = apply_template(spec, opt)
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

if __name__ == "__main__":
    main()