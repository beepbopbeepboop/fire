#!/bin/bash
# Safe wrapper for mojo.py builds against CPython 3.14 source.
# Usage: ./safe_build.sh <logfile> <mojo.py args...>
# Runs under RLIMIT_AS=8GB, backgrounded, with a watcher that
# kill -9's the process if wall-clock > 300s or RSS > 6GB.
LOG="$1"; shift
( exec python3 -c "
import resource, sys, os
try:
    lim = 8 << 30
    resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
except (ValueError, OSError):
    pass  # macOS may refuse RLIMIT_AS changes; RSS watcher below still guards
argv = sys.argv[1:]
if not os.path.dirname(argv[0]):
    argv[0] = os.path.join(os.getcwd(), argv[0])
os.execvp(argv[0], argv)
" "$@" ) > "$LOG" 2>&1 &
PID=$!
echo "pid=$PID" >&2
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
wait $PID
exit $?
