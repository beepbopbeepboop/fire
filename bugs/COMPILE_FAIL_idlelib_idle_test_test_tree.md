# COMPILE_FAIL: Lib/idlelib/idle_test/test_tree.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_tree.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_TestScrollEvent_assertEqual", referenced from:
      _TestScrollEvent_test_wheel_event in test_tree.o
  "__Event", referenced from:
      _TestScrollEvent_test_wheel_event in test_tree.o
  "__Widget", referenced from:
      _TestScrollEvent_test_wheel_event in test_tree.o
  "_requires", referenced from:
      __toplevel in test_tree.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.13s
