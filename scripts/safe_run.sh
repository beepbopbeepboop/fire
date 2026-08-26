#!/bin/bash
# safe_run.sh <logfile> <mojo.py args...>
# Runs `python3 <args>` backgrounded under an ACTIVE WATCHER loop that
# kill -9's it if wall-clock exceeds 300s or RSS exceeds ~6GB.
# (RLIMIT_AS is deliberately NOT used here: on macOS it makes execvp
# itself fail with ENOENT, so the RSS/wall watcher is the real guard.)
LOG="$1"; shift
( exec python3 "$@" ) > "$LOG" 2>&1 &
PID=$!
echo "pid=$PID log=$LOG" >&2
START=$(date +%s)
while kill -0 $PID 2>/dev/null; do
  NOW=$(date +%s)
  ELAPSED=$((NOW-START))
  RSS=$(ps -o rss= -p $PID 2>/dev/null | tr -d ' ')
  RSS=${RSS:-0}
  if [ "$ELAPSED" -gt 300 ]; then
    echo "WATCHER: timeout ${ELAPSED}s, killing $PID" >&2
    kill -9 $PID; wait $PID 2>/dev/null; exit 124
  fi
  if [ "$RSS" -gt 6000000 ]; then
    echo "WATCHER: rss ${RSS}KB > 6GB, killing $PID" >&2
    kill -9 $PID; wait $PID 2>/dev/null; exit 125
  fi
  sleep 2
done
wait $PID 2>/dev/null
exit $?
