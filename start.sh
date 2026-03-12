#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ── Kill existing processes on ports 8000 and 5173 ──
echo "🔪 Killing existing processes..."
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# ── Activate venv ──
if [ ! -d ".venv" ]; then
  echo "❌ No .venv found. Run: python3 -m venv .venv && pip install -e ."
  exit 1
fi
source .venv/bin/activate

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
python -m agentagent.cli serve --port 8000 &
BACKEND_PID=$!

# ── Start frontend ──
echo "🚀 Starting frontend on :5173..."
cd web
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
