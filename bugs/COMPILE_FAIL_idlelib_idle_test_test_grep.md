# COMPILE_FAIL: Lib/idlelib/idle_test/test_grep.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_grep.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_Dummy_grep_grep_it", referenced from:
      _Grep_itTest_report in test_grep.o
      _Grep_itTest_test_unfound in test_grep.o
      _Grep_itTest_test_found in test_grep.o
  "_FindfilesTest_assertEqual", referenced from:
      _FindfilesTest_test_invaliddir in test_grep.o
      _FindfilesTest_test_base in test_grep.o
  "_FindfilesTest_assertGreater", referenced from:
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
  "_FindfilesTest_assertIn", referenced from:
      _FindfilesTest_test_invaliddir in test_grep.o
      _FindfilesTest_test_curdir in test_grep.o
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
      ...
  "_FindfilesTest_assertNotEqual", referenced from:
      _FindfilesTest_test_base in test_grep.o
  "_FindfilesTest_assertNotIn", referenced from:
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_base in test_grep.o
      _FindfilesTest_test_recurse in test_grep.o
  "_Grep_itTest_assertEqual", referenced from:
      _Grep_itTest_test_unfound in test_grep.o
      _Grep_itTest_test_unfound in test_grep.o
      _Grep_itTest_test_found in test_grep.o
  "_Grep_itTest_assertIn", referenced from:
      _Grep_itTest_test_unfound in test_grep.o
      _Grep_itTest_test_found in test_grep.o
      _Grep_itTest_test_found in test_grep.o
      _Grep_itTest_test_found in test_grep.o
  "_Grep_itTest_assertStartsWith", referenced from:
      _Grep_itTest_test_found in test_grep.o
  "_captured_stdout", referenced from:
      _FindfilesTest_test_invaliddir in test_grep.o
      _Grep_itTest_report in test_grep.o
      _Grep_itTest_test_unfound in test_grep.o
      _Grep_itTest_test_found in test_grep.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.86s
