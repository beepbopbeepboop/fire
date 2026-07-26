# COMPILE_FAIL: Doc/includes/mp_newtype.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/mp_newtype.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_GeneratorProxy__callmethod", referenced from:
      _GeneratorProxy___next__ in mp_newtype.o
  "_MyManager_Foo1", referenced from:
      _test in mp_newtype.o
  "_MyManager_Foo2", referenced from:
      _test in mp_newtype.o
  "_MyManager_baz", referenced from:
      _test in mp_newtype.o
  "_MyManager_operator", referenced from:
      _test in mp_newtype.o
  "_MyManager_start", referenced from:
      _test in mp_newtype.o
  "_freeze_support", referenced from:
      __toplevel in mp_newtype.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 6.21s
