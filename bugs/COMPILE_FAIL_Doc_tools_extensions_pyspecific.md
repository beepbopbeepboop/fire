# COMPILE_FAIL: Doc/tools/extensions/pyspecific.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/pyspecific.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_super", referenced from:
      _PyAwaitableMixin_handle_signature in pyspecific.o
      _PyAwaitableFunction_handle_signature in pyspecific.o
      _PyAwaitableMethod_handle_signature in pyspecific.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.28s
