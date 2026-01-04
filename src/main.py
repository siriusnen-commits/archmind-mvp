from pathlib import Path

PROMPT_PATH = Path("docs/architecture_prompt.md")
INPUT_PATH = Path("examples/sample_input.txt")
OUTPUT_PATH = Path("examples/sample_output.md")

def main():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    idea = INPUT_PATH.read_text(encoding="utf-8")

    # TODO: Replace this stub with your local LLM call (Ollama/WebUI/etc.)
    # For Day 2, we just generate a combined "request" file to prove the pipeline works.
    request = f"{prompt}\n\n---\n\nPRODUCT IDEA:\n{idea}\n"

    OUTPUT_PATH.write_text(request, encoding="utf-8")
    print(f"[OK] Wrote request to: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()