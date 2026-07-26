# COMPILE_FAIL: Lib/idlelib/idle_test/test_replace.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_replace.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ReplaceDialogTest_assertIn", referenced from:
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_regex in test_replace.o
      _ReplaceDialogTest_test_replace_all in test_replace.o
      _ReplaceDialogTest_test_replace_all in test_replace.o
      ...
  "_ReplaceDialogTest_assertNotIn", referenced from:
      _ReplaceDialogTest_test_replace_all in test_replace.o
  "_ReplaceDialogTest_setUpClass_lambda_1", referenced from:
      _ReplaceDialogTest_setUpClass in test_replace.o
  "_requires", referenced from:
      __toplevel in test_replace.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.17s
