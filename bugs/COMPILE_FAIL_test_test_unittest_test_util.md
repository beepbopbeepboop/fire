# COMPILE_FAIL: Lib/test/test_unittest/test_util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_safe_repr", referenced from:
      _TestUtil_test_safe_repr in test_util.o
      _TestUtil_test_safe_repr in test_util.o
      _TestUtil_test_safe_repr in test_util.o
  "_sorted_list_difference", referenced from:
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      _TestUtil_test_sorted_list_difference in test_util.o
      ...
  "_unorderable_list_difference", referenced from:
      _TestUtil_test_unorderable_list_difference in test_util.o
      _TestUtil_test_unorderable_list_difference in test_util.o
      _TestUtil_test_unorderable_list_difference in test_util.o
      _TestUtil_test_unorderable_list_difference in test_util.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.41s
