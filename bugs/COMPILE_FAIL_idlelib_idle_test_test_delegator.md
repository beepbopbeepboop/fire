# COMPILE_FAIL: Lib/idlelib/idle_test/test_delegator.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_delegator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_DelegatorTest_assertEqual", referenced from:
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
  "_DelegatorTest_assertIs", referenced from:
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
  "_DelegatorTest_assertNotIn", referenced from:
      _DelegatorTest_test_mydel in test_delegator.o
      _DelegatorTest_test_mydel in test_delegator.o
  "_DelegatorTest_assertRaises", referenced from:
      _DelegatorTest_test_mydel in test_delegator.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.47s
