# COMPILE_FAIL: Lib/test/test_unittest/testmock/testcallable.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testcallable.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_create_autospec", referenced from:
      _TestCallable_test_create_autospec in testcallable.o
      _TestCallable_test_create_autospec in testcallable.o
      _TestCallable_test_create_autospec_instance in testcallable.o
  "_is_instance", referenced from:
      _TestCallable_assertNotCallable in testcallable.o
      _TestCallable_assertNotCallable in testcallable.o
      _TestCallable_test_patch_spec in testcallable.o
      _TestCallable_test_patch_spec in testcallable.o
      _TestCallable_test_patch_spec_instance in testcallable.o
      _TestCallable_test_patch_spec_instance in testcallable.o
      _TestCallable_test_patch_spec_callable_class in testcallable.o
      ...
  "_patch", referenced from:
      _TestCallable_test_patch_spec in testcallable.o
      _TestCallable_test_patch_spec_instance in testcallable.o
      _TestCallable_test_patch_spec_callable_class in testcallable.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.61s
