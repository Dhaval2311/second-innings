#!/usr/bin/env bash
# Launch Brave (Chromium) with remote debugging so automation can attach to your logged-in session.

set -euo pipefail

PORT="${1:-9222}"
PROFILE_DIR="${HOME}/.second-innings-brave"
BRAVE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

if [[ ! -x "$BRAVE" ]]; then
  echo "Brave not found at: $BRAVE"
  echo "Install Brave or set browser.executable_path in config.yaml"
  exit 1
fi

mkdir -p "$PROFILE_DIR"

"$BRAVE" \
  "--remote-debugging-port=${PORT}" \
  "--user-data-dir=${PROFILE_DIR}" \
  "--no-first-run" \
  "--no-default-browser-check" &

echo "Brave started with remote debugging on port ${PORT}"
echo "Profile dir: ${PROFILE_DIR}"
echo "Log into Naukri/LinkedIn/Indeed in this window, then run:"
echo "  python -m job_automation apply"