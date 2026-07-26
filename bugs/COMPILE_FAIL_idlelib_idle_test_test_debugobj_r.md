# COMPILE_FAIL: Lib/idlelib/idle_test/test_debugobj_r.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugobj_r.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_StubObjectTreeItemTest_assertEqual", referenced from:
      _StubObjectTreeItemTest_test_init in test_debugobj_r.o
      _StubObjectTreeItemTest_test_init in test_debugobj_r.o
  "_WrappedObjectTreeItemTest_assertEqual", referenced from:
      _WrappedObjectTreeItemTest_test_getattr in test_debugobj_r.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.51s
