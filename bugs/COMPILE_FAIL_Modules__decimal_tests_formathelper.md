# COMPILE_FAIL: Modules/_decimal/tests/formathelper.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_format", referenced from:
      _printit_7a6366 in formathelper.o
      _check_fillchar_0c85c9 in formathelper.o
  "_import_fresh_module", referenced from:
      __toplevel in formathelper.o
      __toplevel in formathelper.o
  "_which", referenced from:
      __toplevel in formathelper.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.26s
