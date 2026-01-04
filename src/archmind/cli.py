from __future__ import annotations
from pathlib import Path
import argparse
from .generator import generate_project

DEFAULT_PROMPT = Path("docs/architecture_prompt.md")

def main():
    ap = argparse.ArgumentParser(prog="archmind")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate a runnable project from an idea")
    g.add_argument("--idea", required=True, help="Product idea in plain text")
    g.add_argument("--out", default="generated", help="Output root directory")
    g.add_argument("--force", action="store_true", help="Overwrite existing files")
    g.add_argument("--prompt", default=str(DEFAULT_PROMPT), help="Prompt file path")

    args = ap.parse_args()

    prompt_text = Path(args.prompt).read_text(encoding="utf-8")
    project_root = generate_project(prompt_text, args.idea, Path(args.out), force=args.force)

    print(f"[OK] Generated: {project_root}")
    print("Next steps:")
    print(f"  cd {project_root}")
    print("  python3 -m venv .venv && source .venv/bin/activate")
    print("  python -m pip install -r requirements.txt")
    print("  PORT=8000 python main.py")

if __name__ == "__main__":
    main()