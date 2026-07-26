# COMPILE_FAIL: Lib/test/test_tkinter/test_simpledialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_simpledialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_askinteger", referenced from:
      _DefaultRootTest_test_askinteger in test_simpledialog.o
      _DefaultRootTest_test_askinteger in test_simpledialog.o
  "_requires", referenced from:
      __toplevel in test_simpledialog.o
  "_swap_attr", referenced from:
      _DefaultRootTest_test_askinteger in test_simpledialog.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 64.70s
