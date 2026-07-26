# COMPILE_FAIL: Lib/idlelib/idle_test/test_editor.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editor.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_EditorWindowTest_assertEqual", referenced from:
      _EditorWindowTest_test_init in test_editor.o
  "_GetLineIndentTest_assertEqual", referenced from:
      _GetLineIndentTest_test_empty_lines in test_editor.o
      _GetLineIndentTest_test_tabwidth_4 in test_editor.o
      _GetLineIndentTest_test_tabwidth_8 in test_editor.o
  "_GetLineIndentTest_subTest", referenced from:
      _GetLineIndentTest_test_empty_lines in test_editor.o
      _GetLineIndentTest_test_tabwidth_4 in test_editor.o
      _GetLineIndentTest_test_tabwidth_8 in test_editor.o
  "_IndentAndNewlineTest_subTest", referenced from:
      _IndentAndNewlineTest_test_indent_and_newline_event in test_editor.o
  "_IndentSearcherTest_assertEqual", referenced from:
      _IndentSearcherTest_test_searcher in test_editor.o
  "_IndentSearcherTest_subTest", referenced from:
      _IndentSearcherTest_test_searcher in test_editor.o
  "_namedtuple", referenced from:
      _IndentAndNewlineTest_test_indent_and_newline_event in test_editor.o
  "_requires", referenced from:
      _EditorWindowTest_setUpClass in test_editor.o
      _IndentAndNewlineTest_setUpClass in test_editor.o
      _IndentSearcherTest_setUpClass in test_editor.o
      _RMenuTest_setUpClass in test_editor.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.43s
