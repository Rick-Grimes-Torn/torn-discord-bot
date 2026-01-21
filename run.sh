#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")" || exit 1

LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/bot.log"

# If you installed python via micromamba:
eval "$(~/bin/micromamba shell hook -s bash)"
micromamba activate tornbot

echo "$(date -Is) [runner] starting restart loop" | tee -a "$LOG_FILE"

FAILS=0

while true; do
  echo "$(date -Is) [runner] launching bot" | tee -a "$LOG_FILE"

  # Run bot; capture exit code without killing the script on failure
  set +e
  python -m bot.main 2>&1 | tee -a "$LOG_FILE"
  EXIT_CODE=${PIPESTATUS[0]}
  set -e

  echo "$(date -Is) [runner] bot exited with code $EXIT_CODE" | tee -a "$LOG_FILE"

  # Backoff if it’s crash-looping
  if [ "$EXIT_CODE" -ne 0 ]; then
    FAILS=$((FAILS + 1))
  else
    FAILS=0
  fi

  if [ "$FAILS" -ge 5 ]; then
    echo "$(date -Is) [runner] crash loop detected, sleeping 60s" | tee -a "$LOG_FILE"
    sleep 60
    FAILS=0
  else
    sleep 5
  fi
done
