# COMPILE_FAIL: Lib/test/test_unittest/testmock/testwith.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testwith.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_call", referenced from:
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      ...
  "_catch_warnings", referenced from:
      _WithTest_test_with_statement_nested in testwith.o
  "_is_instance", referenced from:
      _WithTest_test_with_statement_as in testwith.o
  "_mock_open", referenced from:
      _TestMockOpen_test_mock_open in testwith.o
      _TestMockOpen_test_mock_open_context_manager in testwith.o
      _TestMockOpen_test_mock_open_context_manager_multiple_times in testwith.o
      _TestMockOpen_test_explicit_mock in testwith.o
      _TestMockOpen_test_read_data in testwith.o
      _TestMockOpen_test_readline_data in testwith.o
      _TestMockOpen_test_readline_data in testwith.o
      ...
  "_next", referenced from:
      _TestMockOpen_test_dunder_iter_data in testwith.o
      _TestMockOpen_test_next_data in testwith.o
      _TestMockOpen_test_next_data in testwith.o
  "_patch", referenced from:
      _WithTest_test_with_statement in testwith.o
      _WithTest_test_with_statement_exception in testwith.o
      _WithTest_test_with_statement_as in testwith.o
      _WithTest_test_with_statement_nested in testwith.o
      _WithTest_test_with_statement_nested in testwith.o
      _WithTest_test_with_statement_specified in testwith.o
      _WithTest_test_with_statement_same_attribute in testwith.o
      _WithTest_test_with_statement_same_attribute in testwith.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 17.33s
