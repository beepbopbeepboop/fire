# COMPILE_FAIL: PC/layout/support/arch.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/layout/support/arch.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_log_debug", referenced from:
      _calculate_from_build_dir_0c85c9 in arch.o
  "_log_info", referenced from:
      _calculate_from_build_dir_0c85c9 in arch.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.05s
