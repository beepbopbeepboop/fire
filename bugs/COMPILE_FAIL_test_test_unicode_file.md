# COMPILE_FAIL: Lib/test/test_unicode_file.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unicode_file.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_change_cwd", referenced from:
      _TestUnicodeFiles__do_directory in test_unicode_file.o
  "_create_empty_file", referenced from:
      _TestUnicodeFiles__test_single in test_unicode_file.o
  "_rmtree", referenced from:
      _TestUnicodeFiles__do_directory in test_unicode_file.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 17.43s
