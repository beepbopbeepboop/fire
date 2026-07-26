# COMPILE_FAIL: Lib/idlelib/idle_test/test_history.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_history.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_FetchTest_assertEqual", referenced from:
      _FetchTest_test_history_prev_next in test_history.o
      _FetchTest_test_history_prev_next in test_history.o
  "_StoreTest_assertEqual", referenced from:
      _StoreTest_test_init in test_history.o
      _StoreTest_test_init in test_history.o
      _StoreTest_test_store_short in test_history.o
      _StoreTest_test_store_short in test_history.o
      _StoreTest_test_store_dup in test_history.o
      _StoreTest_test_store_dup in test_history.o
      _StoreTest_test_store_dup in test_history.o
      ...
  "_StoreTest_assertIs", referenced from:
      _StoreTest_test_init in test_history.o
  "_StoreTest_assertIsNone", referenced from:
      _StoreTest_test_init in test_history.o
      _StoreTest_test_init in test_history.o
      _StoreTest_test_store_reset in test_history.o
      _StoreTest_test_store_reset in test_history.o
  "_TextWrapper_insert", referenced from:
      _FetchTest_setUp in test_history.o
  "_TextWrapper_mark_gravity", referenced from:
      _FetchTest_setUp in test_history.o
  "_TextWrapper_mark_set", referenced from:
      _FetchTest_setUp in test_history.o
  "_mkText", referenced from:
      _StoreTest_setUpClass in test_history.o
  "_requires", referenced from:
      _FetchTest_setUpClass in test_history.o
  "_tkText", referenced from:
      _TextWrapper___init__ in test_history.o
      _FetchTest_setUp in test_history.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.78s
