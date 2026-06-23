#!/usr/bin/env bash
# Launch Brave with remote debugging — automation attaches ONLY to this window.
#
# Usage:
#   ./launch_brave.sh default   # YOUR profile (recommended — keep LinkedIn login here)
#   ./launch_brave.sh           # separate automation profile (must log in again)

set -euo pipefail

PORT="${2:-9222}"
MODE="${1:-default}"
BRAVE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

if [[ ! -x "$BRAVE" ]]; then
  echo "Brave not found at: $BRAVE"
  exit 1
fi

echo "IMPORTANT: Quit ALL other Brave windows first (Cmd+Q) before starting."

if [[ "$MODE" == "default" ]]; then
  echo "Starting Brave (default profile) with remote debugging on port ${PORT}..."
  "$BRAVE" "--remote-debugging-port=${PORT}" "--no-first-run" &
else
  PROFILE_DIR="${HOME}/.second-innings-brave"
  mkdir -p "$PROFILE_DIR"
  echo "Starting Brave (automation profile) on port ${PORT}..."
  "$BRAVE" "--remote-debugging-port=${PORT}" "--user-data-dir=${PROFILE_DIR}" "--no-first-run" &
fi

sleep 3
echo ""
echo "Open LinkedIn in THIS Brave window and log in."
echo "Then run: python -m job_automation apply"