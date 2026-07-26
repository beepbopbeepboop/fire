# COMPILE_FAIL: Lib/idlelib/idle_test/test_parenmatch.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_parenmatch.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ParenMatchTest_assertEqual", referenced from:
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
  "_ParenMatchTest_assertFalse", referenced from:
      _ParenMatchTest_test_handle_restore_timer in test_parenmatch.o
  "_ParenMatchTest_assertIn", referenced from:
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
  "_ParenMatchTest_assertNotIn", referenced from:
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
  "_ParenMatchTest_assertTrue", referenced from:
      _ParenMatchTest_test_handle_restore_timer in test_parenmatch.o
  "_ParenMatchTest_assertTupleEqual", referenced from:
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
  "_ParenMatchTest_get_parenmatch_lambda_1", referenced from:
      _ParenMatchTest_get_parenmatch in test_parenmatch.o
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
      _ParenMatchTest_test_paren_corner in test_parenmatch.o
      _ParenMatchTest_test_handle_restore_timer in test_parenmatch.o
  "_ParenMatchTest_subTest", referenced from:
      _ParenMatchTest_test_paren_styles in test_parenmatch.o
  "_requires", referenced from:
      __toplevel in test_parenmatch.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.61s
