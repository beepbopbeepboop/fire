# COMPILE_FAIL: Lib/test/test_unicode_file_functions.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unicode_file_functions.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_UnicodeNFCFileTests_addCleanup", referenced from:
      _UnicodeNFCFileTests_setUp in test_unicode_file_functions.o
  "_UnicodeNFCFileTests_assertEqual", referenced from:
      _UnicodeNFCFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_listdir in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_listdir in test_unicode_file_functions.o
  "_UnicodeNFCFileTests_assertRaises", referenced from:
      _UnicodeNFCFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFCFileTests_test_normalize in test_unicode_file_functions.o
      ...
  "_UnicodeNFDFileTests_addCleanup", referenced from:
      _UnicodeNFDFileTests_setUp in test_unicode_file_functions.o
  "_UnicodeNFDFileTests_assertEqual", referenced from:
      _UnicodeNFDFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_listdir in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_listdir in test_unicode_file_functions.o
  "_UnicodeNFDFileTests_assertRaises", referenced from:
      _UnicodeNFDFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFDFileTests_test_normalize in test_unicode_file_functions.o
      ...
  "_UnicodeNFKCFileTests_addCleanup", referenced from:
      _UnicodeNFKCFileTests_setUp in test_unicode_file_functions.o
  "_UnicodeNFKCFileTests_assertEqual", referenced from:
      _UnicodeNFKCFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_listdir in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_listdir in test_unicode_file_functions.o
  "_UnicodeNFKCFileTests_assertRaises", referenced from:
      _UnicodeNFKCFileTests__apply_failure in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      _UnicodeNFKCFileTests_test_normalize in test_unicode_file_functions.o
      ...
  "_UnicodeNFKDFileTests_addCleanup", referenced from:
      _UnicodeNFKDFileTests_setUp in test_unicode_file_functions.o
  "_UnicodeNFKDFileTests_assertEqual", referenced from:
      _UnicodeNFKDFileTests__apply_failure in test_unicode_file_functions.o
... (20 more lines)
```

Exit code: 1
Elapsed: 17.83s
