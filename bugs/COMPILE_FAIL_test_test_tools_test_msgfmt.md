# COMPILE_FAIL: Lib/test/test_tools/test_msgfmt.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_msgfmt.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_assert_python_failure", referenced from:
      _CompilationTest_test_po_with_bom in test_msgfmt.o
      _CompilationTest_test_invalid_msgid_plural in test_msgfmt.o
      _CompilationTest_test_plural_without_msgid_plural in test_msgfmt.o
      _CompilationTest_test_indexed_msgstr_without_msgid_plural in test_msgfmt.o
      _CompilationTest_test_generic_syntax_error in test_msgfmt.o
      _CLITest_test_invalid_option in test_msgfmt.o
      _CLITest_test_nonexistent_file in test_msgfmt.o
      ...
  "_assert_python_ok", referenced from:
      _compile_messages_1ce6ce in test_msgfmt.o
      _CompilationTest_test_binary_header in test_msgfmt.o
      _CLITest_test_help in test_msgfmt.o
      _CLITest_test_version in test_msgfmt.o
      _CLITest_test_no_input_file in test_msgfmt.o
  "_imports_under_tool", referenced from:
      __toplevel in test_msgfmt.o
  "_skip_if_missing", referenced from:
      __toplevel in test_msgfmt.o
  "_temp_cwd", referenced from:
      _CompilationTest_test_compilation in test_msgfmt.o
      _CompilationTest_test_binary_header in test_msgfmt.o
      _CompilationTest_test_po_with_bom in test_msgfmt.o
      _CompilationTest_test_invalid_msgid_plural in test_msgfmt.o
      _CompilationTest_test_plural_without_msgid_plural in test_msgfmt.o
      _CompilationTest_test_indexed_msgstr_without_msgid_plural in test_msgfmt.o
      _CompilationTest_test_generic_syntax_error in test_msgfmt.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 18.57s
