# COMPILE_FAIL: Lib/idlelib/idle_test/test_iomenu.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_iomenu.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_FiletypesTest_assertTrue", referenced from:
      _FiletypesTest_test_text_files in test_iomenu.o
      _FiletypesTest_test_all_files in test_iomenu.o
  "_IOBindingTest_assertIs", referenced from:
      _IOBindingTest_test_init in test_iomenu.o
  "_requires", referenced from:
      _IOBindingTest_setUpClass in test_iomenu.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.87s
