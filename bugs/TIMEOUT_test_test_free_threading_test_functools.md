# TIMEOUT: Lib/test/test_free_threading/test_functools.py

## Status
**Fixed** (side effect, 2026-07-25) — root cause was the multi-name
`import a, b, c` binding bug fixed in commit 52ea4d7. Re-running this
file after that fix completes without a timeout (exit code 5, no hang).


Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_free_threading/test_functools.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
(timeout after 90s)
```

Exit code: -1
Elapsed: 90.01s
