#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/make_wheelhouse.sh [--clean] [--dev] [--wheelhouse PATH]

Build an offline wheelhouse for ArchMind (run on an online machine).
Options:
  --clean           Remove existing wheelhouse before download
  --dev             Include dev extras in wheelhouse
  --wheelhouse PATH Output directory (default: wheelhouse)
  -h, --help        Show this help message

Notes:
  - Wheelhouse generation requires network access (online machine).
  - Copy wheelhouse/ and dist/archmind-*.whl to the offline machine.
  - Then run: ./scripts/offline_install_verify.sh --wheelhouse wheelhouse
USAGE
}

CLEAN=0
DEV=0
WHEELHOUSE="wheelhouse"

while [ $# -gt 0 ]; do
  case "$1" in
    --clean)
      CLEAN=1
      ;;
    --dev)
      DEV=1
      ;;
    --wheelhouse)
      shift
      WHEELHOUSE="$1"
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

if [ "$CLEAN" -eq 1 ] && [ -d "$WHEELHOUSE" ]; then
  rm -rf "$WHEELHOUSE"
fi

mkdir -p "$WHEELHOUSE"

if ! ls dist/archmind-*.whl >/dev/null 2>&1; then
  echo "[INFO] No dist wheel found. Building..."
  python -m build --no-isolation
fi

BASE_DEPS="requests==2.32.5"
DEV_DEPS="pytest==9.0.2 fastapi==0.115.0 uvicorn[standard]==0.30.6 sqlmodel==0.0.21 pydantic==2.8.2 pydantic-settings==2.4.0 httpx==0.27.0 build==1.2.1 twine==6.2.0"

TMP_CHECK=$(mktemp -d)
trap 'rm -rf "$TMP_CHECK"' EXIT

CHECK_LOG="$TMP_CHECK/pip_check.log"
if ! python -m pip download -d "$TMP_CHECK" $BASE_DEPS >"$CHECK_LOG" 2>&1; then
  echo "[ERROR] Network check failed. This appears to be an offline/blocked environment." >&2
  echo "[INFO] Wheelhouse must be generated on an online machine." >&2
  echo "[INFO] After generation, copy: wheelhouse/ and dist/archmind-*.whl" >&2
  echo "[INFO] Offline verification: ./scripts/offline_install_verify.sh --wheelhouse wheelhouse" >&2
  echo "--- pip output (last 20 lines) ---" >&2
  tail -n 20 "$CHECK_LOG" >&2
  exit 2
fi

python -m pip download -d "$WHEELHOUSE" $BASE_DEPS

if [ "$DEV" -eq 1 ]; then
  python -m pip download -d "$WHEELHOUSE" $DEV_DEPS
fi

cp dist/archmind-*.whl "$WHEELHOUSE"/

echo "[OK] Wheelhouse ready: $WHEELHOUSE"
ls -1 "$WHEELHOUSE"
