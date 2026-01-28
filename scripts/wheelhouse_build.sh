#!/usr/bin/env bash
set -euo pipefail

python -m pip install -U pip

# Build a wheelhouse for offline installs.
# If dependencies change, update the list below.
python -m pip download -d wheelhouse \
  "requests==2.32.5"

# Optional: include build tools for offline build checks
# python -m pip download -d wheelhouse "build==1.2.1" "twine==6.2.0" "setuptools>=68" "wheel"

# Produce the ArchMind wheel/sdist (online machine)
python -m build --no-isolation

echo "[OK] wheelhouse/ and dist/ are ready to move offline."
