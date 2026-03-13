#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Pick an available Python executable (prefer 3.12 because pyproject requires it).
if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "❌ python3 not found. Install Python 3.12+ and try again."
  exit 1
fi

# ── Kill existing processes on ports 8000 and 5173 ──
echo "🔪 Killing existing processes..."
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# ── Activate venv ──
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate

# Ensure backend dependencies are available in the venv.
if ! python -c "import agentagent" >/dev/null 2>&1; then
  echo "📦 Installing backend dependencies..."
  python -m pip install -e .
fi

# ── Load API key from .env if it exists ──
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "❌ OPENAI_API_KEY not set. Export it or add it to .env"
  exit 1
fi

# ── Start backend ──
echo "🚀 Starting backend on :8000..."
PYTHONPATH="${DIR}/src${PYTHONPATH:+:$PYTHONPATH}" python -m agentagent.cli serve --port 8000 &
BACKEND_PID=$!

# ── Wait for backend to be ready ──
echo "⏳ Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/configs >/dev/null 2>&1; then
    echo "✅ Backend ready"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "❌ Backend process died"
    exit 1
  fi
  sleep 1
done

# ── Start frontend ──
echo "🚀 Starting frontend on :5173..."
cd web
# Install frontend dependencies when missing.
if [ ! -d "node_modules" ]; then
  echo "📦 Installing frontend dependencies..."
  npm install
fi
npm run dev &
FRONTEND_PID=$!
cd "$DIR"

# ── Trap cleanup on exit ──
cleanup() {
  echo ""
  echo "🛑 Shutting down..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null
  echo "✅ Done."
}
trap cleanup EXIT INT TERM

# ── Wait for both ──
echo ""
echo "✅ AgentAgent running"
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:5173"
echo "   Press Ctrl+C to stop"
echo ""
wait
