# COMPILE_FAIL: Lib/idlelib/idle_test/test_pyshell.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_pyshell.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_FunctionTest_assertEqual", referenced from:
      _FunctionTest_test_restart_line_narrow in test_pyshell.o
      _FunctionTest_test_restart_line_narrow in test_pyshell.o
  "_FunctionTest_subTest", referenced from:
      _FunctionTest_test_restart_line_wide in test_pyshell.o
      _FunctionTest_test_restart_line_narrow in test_pyshell.o
  "_PyShellFileListTest_assertEqual", referenced from:
      _PyShellFileListTest_test_init in test_pyshell.o
  "_PyShellFileListTest_assertIsNone", referenced from:
      _PyShellFileListTest_test_init in test_pyshell.o
  "_PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_assertEqual", referenced from:
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_all_removed in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_none_removed in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_check_result in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_empty in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      _PyShellRemoveLastNewlineAndSurroundingWhitespaceTest_test_whitespace_no_newline in test_pyshell.o
      ...
  "_requires", referenced from:
      _PyShellFileListTest_setUpClass in test_pyshell.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.99s
