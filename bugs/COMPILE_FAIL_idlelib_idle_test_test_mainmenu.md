# COMPILE_FAIL: Lib/idlelib/idle_test/test_mainmenu.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_mainmenu.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_MainMenuTest_assertEqual", referenced from:
      _MainMenuTest_test_menudefs in test_mainmenu.o
  "_MainMenuTest_assertGreaterEqual", referenced from:
      _MainMenuTest_test_default_keydefs in test_mainmenu.o
  "_MainMenuTest_assertTrue", referenced from:
      _MainMenuTest_test_tcl_indexes in test_mainmenu.o
  "_MainMenuTest_subTest", referenced from:
      _MainMenuTest_test_tcl_indexes in test_mainmenu.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.47s
