#!/usr/bin/env bash
set -e

# ==========================================================
# Samsung Photo Frame Service Launcher & Virtual Environment
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PORT=8080
HOST="0.0.0.0"
MOCK_FLAG=""

# Parse command line options
while [[ $# -gt 0 ]]; do
  case $1 in
    --mock)
      MOCK_FLAG="1"
      shift
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./start.sh [options]"
      echo ""
      echo "Options:"
      echo "  --mock        Force MOCK simulator mode (simulates SPF-87H without USB device)"
      echo "  --port <num>  Set web server port (default: 8080)"
      echo "  --host <ip>   Set bind address (default: 0.0.0.0)"
      echo "  -h, --help    Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "=========================================================="
echo " Starting Samsung Photo Frame Control Center"
echo "=========================================================="

# 1. Initialize Python virtual environment if not present
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Creating virtual environment (.venv)..."
    # Try standard venv first; if ensurepip is unavailable on Debian/Ubuntu, fall back to --without-pip --system-site-packages
    python3 -m venv "$VENV_DIR" 2>/dev/null || {
        echo "      (Standard venv creation without-pip fallback enabled)"
        python3 -m venv --without-pip --system-site-packages "$VENV_DIR"
    }
fi

# 2. Activate virtual environment
echo "[2/3] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 3. Check / configure execution mode
if [ "$MOCK_FLAG" = "1" ]; then
    export FRAME_MOCK=1
    echo "[3/3] Execution Mode: FORCED MOCK SIMULATOR"
else
    echo "[3/3] Execution Mode: AUTO (Physical hardware preferred, auto-mock fallback)"
fi

echo ""
echo "----------------------------------------------------------"
echo " Web Dashboard:  http://localhost:${PORT}"
echo " Local Network:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT}"
echo " Press CTRL+C to terminate the service."
echo "----------------------------------------------------------"
echo ""

exec python3 -m uvicorn service.main:app --host "$HOST" --port "$PORT"
