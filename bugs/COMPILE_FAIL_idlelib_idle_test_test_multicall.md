# COMPILE_FAIL: Lib/idlelib/idle_test/test_multicall.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_multicall.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_MultiCallTest_assertIs", referenced from:
      _MultiCallTest_test_creator in test_multicall.o
      _MultiCallTest_test_creator in test_multicall.o
      _MultiCallTest_test_yview in test_multicall.o
      _MultiCallTest_test_yview in test_multicall.o
  "_MultiCallTest_assertIsInstance", referenced from:
      _MultiCallTest_test_init in test_multicall.o
  "_MultiCallTest_assertIsSubclass", referenced from:
      _MultiCallTest_test_creator in test_multicall.o
  "_MultiCallTest_mc", referenced from:
      _MultiCallTest_test_init in test_multicall.o
      _MultiCallTest_test_yview in test_multicall.o
  "_requires", referenced from:
      _MultiCallTest_setUpClass in test_multicall.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.27s
