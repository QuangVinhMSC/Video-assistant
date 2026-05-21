#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8080
FRONTEND_PORT=5173

# Kill any process currently occupying our ports
kill_port() {
  local port=$1
  local pid
  pid=$(powershell.exe -NoProfile -Command \
    "(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { \$_.LocalPort -eq $port }).OwningProcess" \
    2>/dev/null | tr -d '\r')
  if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]]; then
    powershell.exe -NoProfile -Command "Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue" > /dev/null 2>&1
    echo "Stopped existing process on port $port (PID $pid)"
  fi
}

echo "Stopping existing processes..."
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT

# Start backend
echo "Starting backend on port $BACKEND_PORT..."
cd "$SCRIPT_DIR"
uvicorn main:app --reload --port $BACKEND_PORT &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend on port $FRONTEND_PORT..."
cd "$SCRIPT_DIR/frontend"
npm run dev -- --port $FRONTEND_PORT &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:$BACKEND_PORT"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo ""
echo "Press Ctrl+C to stop both servers."

# Stop both on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

wait
