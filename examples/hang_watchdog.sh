#!/usr/bin/env bash
# Hang watchdog for the Phase-1.5 run: when the run log goes silent past STALL seconds, send SIGUSR1
# to the run so faulthandler dumps ALL thread stacks into the run log (red-handed deadlock capture,
# no sudo/py-spy). Non-destructive: it only DUMPS, never kills — killing a hung task stays a manual
# decision (so we don't silently lose it). Fires once per stall; re-arms when activity resumes.
# Usage: bash examples/hang_watchdog.sh <run_logfile> [stall_seconds]
set -u
LOG="$1"; STALL="${2:-720}"; PAT="run_phase1_5.py"; fired=0
echo "[watchdog] watching $LOG  (stall > ${STALL}s -> SIGUSR1 all-thread dump into the run log)"
while pgrep -f "$PAT" >/dev/null; do
  if [ -f "$LOG" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOG") ))
    if [ "$age" -gt "$STALL" ] && [ "$fired" -eq 0 ]; then
      pid=$(pgrep -f "$PAT" | head -1)
      echo "[watchdog] $(date '+%H:%M:%S') log stale ${age}s -> SIGUSR1 to pid $pid (thread dump -> run log)"
      kill -USR1 "$pid" 2>/dev/null
      fired=1
    elif [ "$age" -lt "$STALL" ]; then
      fired=0
    fi
  fi
  sleep 30
done
echo "[watchdog] $(date '+%H:%M:%S') run process gone; exiting"
