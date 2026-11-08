#!/usr/bin/env bash
set -e

# ==========================================================
# Samsung Photo Frame Service Launcher (Docker & Native)
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN_MODE="docker"
MOCK_FLAG=""
PORT=8080
HOST="0.0.0.0"

# Parse command line options
while [[ $# -gt 0 ]]; do
  case $1 in
    --docker)
      RUN_MODE="docker"
      shift
      ;;
    --native)
      RUN_MODE="native"
      shift
      ;;
    --mock)
      MOCK_FLAG="1"
      shift
      ;;
    --down)
      echo "Stopping Docker container..."
      docker compose -f docker/docker-compose.yml down
      exit 0
      ;;
    --build)
      echo "Rebuilding Docker image..."
      docker compose -f docker/docker-compose.yml build
      exit 0
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
      echo "Execution Modes:"
      echo "  (default)     Run in Docker using Docker Compose"
      echo "  --docker      Run in Docker container (default)"
      echo "  --native      Run natively on host using local Python virtual environment"
      echo ""
      echo "Options:"
      echo "  --mock        Force MOCK simulator mode (simulates SPF-87H without USB device)"
      echo "  --port <num>  Set web server port (default: 8080)"
      echo "  --host <ip>   Set bind address for native mode (default: 0.0.0.0)"
      echo "  --down        Stop running Docker containers"
      echo "  --build       Rebuild the Docker image"
      echo "  -h, --help    Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Ensure config.json exists before volume mounting
if [ ! -f "config.json" ]; then
    echo "{}" > config.json
fi

echo "=========================================================="
echo " Starting Samsung Photo Frame Control Center"
echo "=========================================================="

# ----------------------------------------------------------
# Mode 1: Docker (Default)
# ----------------------------------------------------------
if [ "$RUN_MODE" = "docker" ]; then
    # Verify docker and docker compose are available
    if ! command -v docker &> /dev/null; then
        echo "Error: Docker is not installed or not in PATH."
        echo "Tip: Run with --native to execute directly using host Python environment."
        exit 1
    fi

    export PORT="$PORT"
    if [ "$MOCK_FLAG" = "1" ]; then
        export FRAME_MOCK=1
        export FRAME_FORCE_PHYSICAL=""
        echo "Mode: DOCKER CONTAINER [FORCED MOCK SIMULATOR]"
    else
        export FRAME_MOCK=""
        export FRAME_FORCE_PHYSICAL=1
        echo "Mode: DOCKER CONTAINER [ALWAYS PHYSICAL USB HARDWARE]"
    fi

    # Check if container is already running
    RUNNING_CONTAINERS=$(docker compose -f docker/docker-compose.yml ps -q --status running 2>/dev/null || true)
    BUILD_FLAG=""

    if [ -n "$RUNNING_CONTAINERS" ]; then
        echo ""
        echo "Notice: samsungframe container is currently RUNNING."
        echo "  [c] Continue with running container (attach / restart)"
        echo "  [r] Rebuild container image before continuing"
        echo "  [q] Quit / Abort"
        read -r -p "Select option [c/r/q] (default: c): " USER_CHOICE
        case "${USER_CHOICE,,}" in
            r|rebuild)
                echo "Rebuilding container..."
                docker compose -f docker/docker-compose.yml down
                BUILD_FLAG="--build"
                ;;
            q|quit|exit)
                echo "Aborted by user."
                exit 0
                ;;
            *)
                echo "Continuing with existing container..."
                ;;
        esac
    fi

    echo "Launching container with docker compose..."
    echo "Web Dashboard: http://localhost:${PORT}"
    echo "----------------------------------------------------------"
    exec docker compose -f docker/docker-compose.yml up $BUILD_FLAG
fi

# ----------------------------------------------------------
# Mode 2: Native Host Execution
# ----------------------------------------------------------
if [ "$RUN_MODE" = "native" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"

    if [ ! -d "$VENV_DIR" ]; then
        echo "[1/3] Creating virtual environment (.venv)..."
        python3 -m venv "$VENV_DIR" 2>/dev/null || {
            echo "      (Standard venv creation without-pip fallback enabled)"
            python3 -m venv --without-pip --system-site-packages "$VENV_DIR"
        }
    fi

    echo "[2/3] Activating virtual environment..."
    source "$VENV_DIR/bin/activate"

    if [ "$MOCK_FLAG" = "1" ]; then
        export FRAME_MOCK=1
        export FRAME_FORCE_PHYSICAL=""
        echo "[3/3] Mode: NATIVE [FORCED MOCK SIMULATOR]"
    else
        export FRAME_MOCK=""
        export FRAME_FORCE_PHYSICAL=1
        echo "[3/3] Mode: NATIVE [ALWAYS PHYSICAL USB HARDWARE]"
    fi

    echo ""
    echo "----------------------------------------------------------"
    echo " Web Dashboard:  http://localhost:${PORT}"
    echo " Press CTRL+C to terminate the service."
    echo "----------------------------------------------------------"
    echo ""

    exec python3 -m uvicorn service.main:app --host "$HOST" --port "$PORT"
fi
