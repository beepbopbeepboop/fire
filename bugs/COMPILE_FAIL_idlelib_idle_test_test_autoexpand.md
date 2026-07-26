# COMPILE_FAIL: Lib/idlelib/idle_test/test_autoexpand.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autoexpand.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_AutoExpandTest_assertNotEqual", referenced from:
      _AutoExpandTest_test_other_expand_cases in test_autoexpand.o
  "_AutoExpandTest_setUpClass_lambda_1", referenced from:
      _AutoExpandTest_setUpClass in test_autoexpand.o
  "_requires", referenced from:
      _AutoExpandTest_setUpClass in test_autoexpand.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.72s
