# COMPILE_FAIL: Lib/test/test_tools/test_freeze.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_freeze.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_imports_under_tool", referenced from:
      __toplevel in test_freeze.o
  "_skip_if_missing", referenced from:
      __toplevel in test_freeze.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 18.63s
