# COMPILE_FAIL: Lib/idlelib/idle_test/test_searchengine.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_searchengine.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ForwardBackwardTest_setUpClass_lambda_3", referenced from:
      _ForwardBackwardTest_setUpClass in test_searchengine.o
  "_GetLineColTest_assertEqual", referenced from:
      _GetLineColTest_test_get_line_col in test_searchengine.o
      _GetLineColTest_test_get_line_col in test_searchengine.o
  "_GetLineColTest_assertRaises", referenced from:
      _GetLineColTest_test_get_line_col in test_searchengine.o
      _GetLineColTest_test_get_line_col in test_searchengine.o
  "_GetSelectionTest_assertEqual", referenced from:
      _GetSelectionTest_test_get_selection in test_searchengine.o
      _GetSelectionTest_test_get_selection in test_searchengine.o
  "_GetTest_assertIs", referenced from:
      _GetTest_test_get in test_searchengine.o
      _GetTest_test_get in test_searchengine.o
  "_GetTest_assertIsInstance", referenced from:
      _GetTest_test_get in test_searchengine.o
  "_SearchEngineTest_assertEqual", referenced from:
      _SearchEngineTest_test_setcookedpat in test_searchengine.o
      _SearchEngineTest_test_setcookedpat in test_searchengine.o
  "_SearchTest_setUpClass_lambda_1", referenced from:
      _SearchTest_setUpClass in test_searchengine.o
  "_SearchTest_setUpClass_lambda_2", referenced from:
      _SearchTest_setUpClass in test_searchengine.o
  "_mockText", referenced from:
      _GetSelectionTest_test_get_selection in test_searchengine.o
      _SearchTest_setUpClass in test_searchengine.o
      _ForwardBackwardTest_setUpClass in test_searchengine.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.72s
