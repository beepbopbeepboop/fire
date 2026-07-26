# COMPILE_FAIL: Programs/_freeze_module.py

Source file: `/Users/mrs/net/Python-3.14.6/Programs/_freeze_module.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_compile", referenced from:
      _compile_and_marshal_0335d0 in _freeze_module.o
      __gimple_main in _freeze_module.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.67s
