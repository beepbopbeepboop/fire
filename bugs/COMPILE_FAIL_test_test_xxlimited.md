# COMPILE_FAIL: Lib/test/test_xxlimited.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xxlimited.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CommonTests_assertEqual", referenced from:
      _CommonTests_test_xxo_attributes in test_xxlimited.o
      _CommonTests_test_foo in test_xxlimited.o
      _CommonTests_test_str in test_xxlimited.o
      _CommonTests_test_str in test_xxlimited.o
      _CommonTests_test_new in test_xxlimited.o
  "_CommonTests_assertIsNot", referenced from:
      _CommonTests_test_str in test_xxlimited.o
  "_CommonTests_assertIsSubclass", referenced from:
      _CommonTests_test_str in test_xxlimited.o
  "_CommonTests_assertRaises", referenced from:
      _CommonTests_test_xxo_attributes in test_xxlimited.o
      _CommonTests_test_xxo_attributes in test_xxlimited.o
      _CommonTests_test_xxo_attributes in test_xxlimited.o
  "_memoryview", referenced from:
      _TestXXLimited_test_buffer in test_xxlimited.o
      _TestXXLimited_test_buffer in test_xxlimited.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 14.90s
