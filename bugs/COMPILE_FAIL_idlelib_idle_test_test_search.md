# COMPILE_FAIL: Lib/idlelib/idle_test/test_search.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_search.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_SearchDialogTest_assertFalse", referenced from:
      _SearchDialogTest_test_find_again in test_search.o
      _SearchDialogTest_test_find_again in test_search.o
  "_SearchDialogTest_assertTrue", referenced from:
      _SearchDialogTest_test_find_again in test_search.o
      _SearchDialogTest_test_find_again in test_search.o
      _SearchDialogTest_test_find_again in test_search.o
      _SearchDialogTest_test_find_again in test_search.o
      _SearchDialogTest_test_find_selection in test_search.o
      _SearchDialogTest_test_find_selection in test_search.o
      _SearchDialogTest_test_find_selection in test_search.o
      ...
  "_SearchDialogTest_setUp_lambda_1", referenced from:
      _SearchDialogTest_setUp in test_search.o
  "_SearchDialogTest_test_find_again_lambda_2", referenced from:
      _SearchDialogTest_test_find_again in test_search.o
  "_requires", referenced from:
      __toplevel in test_search.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.68s
