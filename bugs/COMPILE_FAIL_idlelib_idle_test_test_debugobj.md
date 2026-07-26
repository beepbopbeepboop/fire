# COMPILE_FAIL: Lib/idlelib/idle_test/test_debugobj.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugobj.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_AtomicObjectTreeItemTest_assertFalse", referenced from:
      _AtomicObjectTreeItemTest_test_isexpandable in test_debugobj.o
  "_ClassTreeItemTest_assertTrue", referenced from:
      _ClassTreeItemTest_test_isexpandable in test_debugobj.o
  "_DictTreeItemTest_assertEqual", referenced from:
      _DictTreeItemTest_test_keys in test_debugobj.o
  "_DictTreeItemTest_assertFalse", referenced from:
      _DictTreeItemTest_test_isexpandable in test_debugobj.o
  "_DictTreeItemTest_assertTrue", referenced from:
      _DictTreeItemTest_test_isexpandable in test_debugobj.o
  "_ObjectTreeItemTest_assertEqual", referenced from:
      _ObjectTreeItemTest_test_init in test_debugobj.o
      _ObjectTreeItemTest_test_init in test_debugobj.o
      _ObjectTreeItemTest_test_init in test_debugobj.o
  "_SequenceTreeItemTest_assertEqual", referenced from:
      _SequenceTreeItemTest_test_keys in test_debugobj.o
  "_SequenceTreeItemTest_assertFalse", referenced from:
      _SequenceTreeItemTest_test_isexpandable in test_debugobj.o
  "_SequenceTreeItemTest_assertTrue", referenced from:
      _SequenceTreeItemTest_test_isexpandable in test_debugobj.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.74s
