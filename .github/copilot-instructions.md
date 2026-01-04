### Quick context

This repository is a minimal Python "prompt + idea -> request file" pipeline. The main runner is [src/main.py](src/main.py). It reads a fixed prompt from [docs/architecture_prompt.md](docs/architecture_prompt.md) and an idea from [examples/sample_input.txt](examples/sample_input.txt), then writes a combined request to [examples/sample_output.md](examples/sample_output.md).

### Primary goal for an AI coding agent
- Preserve the exact prompt structure in `docs/architecture_prompt.md` (the 1–7 numbered sections). Many downstream tools and human reviewers expect that exact format.
- Implement a local LLM integration where `src/main.py` currently has a TODO stub. Replace the stub with a single responsibility: call a local or remote LLM, pass the composed `request`, and write the model's output to `examples/sample_output.md`.

### Project-specific patterns & conventions
- **Prompt-first pipeline:** The prompt lives in `docs/architecture_prompt.md` and must not be reformatted; changes to the prompt content are allowed but keep the 1–7 section layout.
- **File-based I/O:** Inputs and outputs are plain files under `examples/`. Avoid introducing networked ingestion for dev tasks unless adding an explicit adapter.
- **UTF-8 text handling:** All reads/writes use UTF-8. Keep this consistent when adding features or tests.
- **Single-file runner:** `src/main.py` is intentionally minimal and synchronous. Preserve its simple CLI-style behavior for day-to-day development.

### Integration points to be aware of
- LLM integration (where to plug in): `src/main.py` — replace the TODO comment with the LLM call. Keep the function signature local and avoid heavy refactors.
- Prompt source: [docs/architecture_prompt.md](docs/architecture_prompt.md) — used as the system instruction for the LLM.
- Input examples: [examples/sample_input.txt](examples/sample_input.txt) — treat these as canonical seeds for tests or manual runs.

### Useful examples from the codebase
- Composing the request (see `src/main.py`): it concatenates the prompt and idea with a divider `---` and the label `PRODUCT IDEA:`. Follow this exact framing when writing tests or adapters.

### Developer workflows (how to run & debug)
- Run locally from repo root: `python src/main.py` — this reads `docs/architecture_prompt.md` and `examples/sample_input.txt`, then writes `examples/sample_output.md`.
- To iterate on prompts: edit [docs/architecture_prompt.md](docs/architecture_prompt.md) and re-run the script.
- To test an LLM integration quickly, implement a small adapter that accepts the composed string and returns a deterministic placeholder (useful for unit tests).

### What NOT to change without a proposal
- Do not change the 1–7 numbered output format in `docs/architecture_prompt.md` — other tools expect that exact structure.
- Do not replace file-based I/O with a DB or network service without adding an adapter layer and updating README with new run steps.

### When you edit code, include these checks in your PR
- Update `examples/sample_output.md` by running `python src/main.py` and include its output in the PR so reviewers can verify the pipeline.
- Keep changes small and local to `src/` and `docs/` for iteration speed.

If anything here is unclear or you want additional, specific conventions (tests, CI, or LLM adapters), tell me which area to expand.
