# COMPILE_FAIL: Lib/concurrent/futures/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_InterpreterPoolExecutor", referenced from:
      ___getattr___0c85c9 in __init__.o
  "_ProcessPoolExecutor", referenced from:
      ___getattr___0c85c9 in __init__.o
  "_ThreadPoolExecutor", referenced from:
      ___getattr___0c85c9 in __init__.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.98s
