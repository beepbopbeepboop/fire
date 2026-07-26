# COMPILE_FAIL: Lib/idlelib/idle_test/test_rpc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_rpc.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CodePicklerTest_assertEqual", referenced from:
      _CodePicklerTest_test_pickle_unpickle in test_rpc.o
  "_CodePicklerTest_assertIn", referenced from:
      _CodePicklerTest_test_pickle_unpickle in test_rpc.o
      _CodePicklerTest_test_code_pickler in test_rpc.o
      _CodePicklerTest_test_dumps in test_rpc.o
  "_CodePicklerTest_assertIs", referenced from:
      _CodePicklerTest_test_pickle_unpickle in test_rpc.o
  "_CodePicklerTest_test_code_pickler_lambda_1", referenced from:
      _CodePicklerTest_test_code_pickler in test_rpc.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.01s
