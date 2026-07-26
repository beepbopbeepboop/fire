# COMPILE_FAIL: Lib/test/test_tools/test_makeunicodedata.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_makeunicodedata.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_imports_under_tool", referenced from:
      __toplevel in test_makeunicodedata.o
  "_skip_if_missing", referenced from:
      __toplevel in test_makeunicodedata.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 18.18s
