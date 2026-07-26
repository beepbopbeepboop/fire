# COMPILE_FAIL: Lib/test/test_typechecks.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_typechecks.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_issubclass", referenced from:
      _TypeChecksTest_testIsSubclassBuiltin in test_typechecks.o
      _TypeChecksTest_testIsSubclassBuiltin in test_typechecks.o
      _TypeChecksTest_testIsSubclassBuiltin in test_typechecks.o
      _TypeChecksTest_testIsSubclassBuiltin in test_typechecks.o
      _TypeChecksTest_testIsSubclassActual in test_typechecks.o
      _TypeChecksTest_testIsSubclassActual in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      _TypeChecksTest_testSubclassBehavior in test_typechecks.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 17.61s
