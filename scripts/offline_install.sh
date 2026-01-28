#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate

python -m pip install --no-index --find-links wheelhouse dist/*.whl

archmind --version
archmind --help

echo "[OK] Offline install completed."
