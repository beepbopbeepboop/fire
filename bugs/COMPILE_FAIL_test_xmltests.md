# COMPILE_FAIL: Lib/test/xmltests.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/xmltests.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "___import__", referenced from:
      _runtest_0c85c9 in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      __toplevel in xmltests.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.04s
