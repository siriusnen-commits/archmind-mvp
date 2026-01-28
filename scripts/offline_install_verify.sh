#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/offline_install_verify.sh [--wheelhouse PATH] [--venv PATH] [--keep]

Verify offline installation of ArchMind from a local wheelhouse.
Options:
  --wheelhouse PATH  Wheelhouse directory (default: ./wheelhouse)
  --venv PATH        Venv directory (default: /tmp/archmind_offline_test)
  --keep             Keep the venv after verification
  -h, --help         Show this help message
USAGE
}

WHEELHOUSE="wheelhouse"
VENV_DIR="/tmp/archmind_offline_test"
KEEP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --wheelhouse)
      shift
      WHEELHOUSE="$1"
      ;;
    --venv)
      shift
      VENV_DIR="$1"
      ;;
    --keep)
      KEEP=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
 done

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -d "$WHEELHOUSE" ]; then
  echo "[ERROR] Wheelhouse not found: $WHEELHOUSE" >&2
  exit 2
fi

if ! ls "$WHEELHOUSE"/archmind-*.whl >/dev/null 2>&1; then
  echo "[ERROR] archmind wheel not found in wheelhouse. Run make_wheelhouse.sh first." >&2
  exit 2
fi

rm -rf "$VENV_DIR"
python -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --no-index --find-links "$WHEELHOUSE" archmind

archmind --version
archmind --help
archmind generate --help
archmind run --help
archmind fix --help
archmind pipeline --help

if [ "$KEEP" -eq 0 ]; then
  deactivate
  rm -rf "$VENV_DIR"
fi

echo "[OK] Offline install verification completed."
