# COMPILE_FAIL: Tools/c-analyzer/c_common/iterutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/iterutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_callable", referenced from:
      _iter_many_1ce6ce in iterutil.o
      _iter_many_1ce6ce in iterutil.o
  "_next", referenced from:
      _peek_and_iter_0c85c9 in iterutil.o
      _iter_many_1ce6ce in iterutil.o
      _iter_many_1ce6ce in iterutil.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.89s
