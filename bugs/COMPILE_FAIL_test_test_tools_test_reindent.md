# COMPILE_FAIL: Lib/test/test_tools/test_reindent.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_reindent.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_assert_python_ok", referenced from:
      _ReindentTests_test_noargs in test_reindent.o
      _ReindentTests_test_help in test_reindent.o
      _ReindentTests_test_reindent_file_with_bad_encoding in test_reindent.o
  "_findfile", referenced from:
      _ReindentTests_test_reindent_file_with_bad_encoding in test_reindent.o
  "_skip_if_missing", referenced from:
      __toplevel in test_reindent.o
      _main in test_reindent.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 18.72s
