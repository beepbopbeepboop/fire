# COMPILE_FAIL: Lib/idlelib/idle_test/test_statusbar.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_statusbar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_Test_assertEqual", referenced from:
      _Test_test_init in test_statusbar.o
      _Test_test_set_label in test_statusbar.o
      _Test_test_set_label in test_statusbar.o
      _Test_test_set_label in test_statusbar.o
      _Test_test_set_label in test_statusbar.o
  "_Test_assertIn", referenced from:
      _Test_test_set_label in test_statusbar.o
  "_requires", referenced from:
      _Test_setUpClass in test_statusbar.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.19s
