# COMPILE_FAIL: Programs/freeze_test_frozenmain.py

Source file: `/Users/mrs/net/Python-3.14.6/Programs/freeze_test_frozenmain.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_bytes", referenced from:
      _writecode_132aaf in freeze_test_frozenmain.o
  "_compile", referenced from:
      _dump_d02436 in freeze_test_frozenmain.o
      __gimple_main in freeze_test_frozenmain.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.82s
