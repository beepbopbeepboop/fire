# COMPILE_FAIL: Lib/idlelib/idle_test/test_calltip_w.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip_w.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CallTipWindowTest_assertEqual", referenced from:
      _CallTipWindowTest_test_init in test_calltip_w.o
  "_requires", referenced from:
      _CallTipWindowTest_setUpClass in test_calltip_w.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.82s
