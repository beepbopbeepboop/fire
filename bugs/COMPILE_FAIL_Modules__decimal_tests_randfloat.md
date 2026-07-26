# COMPILE_FAIL: Modules/_decimal/tests/randfloat.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_divmod", referenced from:
      _test_halfway_cases in randfloat.o
      __toplevel in randfloat.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.20s
