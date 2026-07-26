# COMPILE_FAIL: Lib/idlelib/idle_test/test_pyparse.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_pyparse.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ParseMapTest_assertEqual", referenced from:
      _ParseMapTest_test_parsemap in test_pyparse.o
      _ParseMapTest_test_parsemap in test_pyparse.o
      _ParseMapTest_test_parsemap in test_pyparse.o
      _ParseMapTest_test_trans in test_pyparse.o
  "_PyParseTest_assertEqual", referenced from:
      _PyParseTest_test_init in test_pyparse.o
      _PyParseTest_test_init in test_pyparse.o
      _PyParseTest_test_set_lo in test_pyparse.o
      _PyParseTest_test_set_lo in test_pyparse.o
  "_PyParseTest_assertIsNone", referenced from:
      _PyParseTest_test_find_good_parse_start in test_pyparse.o
      _PyParseTest_test_study1 in test_pyparse.o
      _PyParseTest_test_study2 in test_pyparse.o
  "_PyParseTest_assertRaises", referenced from:
      _PyParseTest_test_set_code in test_pyparse.o
      _PyParseTest_test_find_good_parse_start in test_pyparse.o
      _PyParseTest_test_find_good_parse_start in test_pyparse.o
      _PyParseTest_test_set_lo in test_pyparse.o
      _PyParseTest_test_get_num_lines_in_stmt in test_pyparse.o
      _PyParseTest_test_compute_bracket_indent in test_pyparse.o
      _PyParseTest_test_compute_backslash_indent in test_pyparse.o
      ...
  "_PyParseTest_subTest", referenced from:
      _PyParseTest_test_set_code in test_pyparse.o
      _PyParseTest_test_study1 in test_pyparse.o
      _PyParseTest_test_get_continuation_type in test_pyparse.o
      _PyParseTest_test_study2 in test_pyparse.o
      _PyParseTest_test_get_num_lines_in_stmt in test_pyparse.o
      _PyParseTest_test_compute_backslash_indent in test_pyparse.o
      _PyParseTest_test_compute_backslash_indent in test_pyparse.o
      ...
  "_namedtuple", referenced from:
      _PyParseTest_test_study1 in test_pyparse.o
      _PyParseTest_test_get_continuation_type in test_pyparse.o
      _PyParseTest_test_study2 in test_pyparse.o
      _PyParseTest_test_get_num_lines_in_stmt in test_pyparse.o
      _PyParseTest_test_compute_bracket_indent in test_pyparse.o
      _PyParseTest_test_compute_backslash_indent in test_pyparse.o
      _PyParseTest_test_get_base_indent_string in test_pyparse.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.73s
