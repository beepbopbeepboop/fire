# COMPILE_FAIL: Lib/idlelib/idle_test/test_window.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_window.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ListedToplevelTest_assertEqual", referenced from:
      _ListedToplevelTest_test_init in test_window.o
  "_ListedToplevelTest_assertIn", referenced from:
      _ListedToplevelTest_test_init in test_window.o
  "_WindowListTest_assertEqual", referenced from:
      _WindowListTest_test_init in test_window.o
      _WindowListTest_test_init in test_window.o
  "_requires", referenced from:
      _ListedToplevelTest_setUpClass in test_window.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.74s
