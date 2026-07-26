# COMPILE_FAIL: Lib/idlelib/idle_test/test_macosx.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_macosx.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_InitTktypeTest_assertIn", referenced from:
      _InitTktypeTest_test_init_sets_tktype in test_macosx.o
  "_InitTktypeTest_subTest", referenced from:
      _InitTktypeTest_test_init_sets_tktype in test_macosx.o
  "_requires", referenced from:
      _InitTktypeTest_setUpClass in test_macosx.o
      _SetupTest_setUpClass in test_macosx.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.04s
