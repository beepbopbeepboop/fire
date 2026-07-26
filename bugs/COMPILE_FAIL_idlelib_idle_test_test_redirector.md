# COMPILE_FAIL: Lib/idlelib/idle_test/test_redirector.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_redirector.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_InitCloseTest_assertEqual", referenced from:
      _InitCloseTest_test_init in test_redirector.o
      _InitCloseTest_test_init in test_redirector.o
      _InitCloseTest_test_close in test_redirector.o
  "_InitCloseTest_assertNotHasAttr", referenced from:
      _InitCloseTest_test_close in test_redirector.o
  "_InitCloseTest_assertRaises", referenced from:
      _InitCloseTest_test_init in test_redirector.o
  "_WidgetRedirectorTest_assertEqual", referenced from:
      _WidgetRedirectorTest_test_register in test_redirector.o
      _WidgetRedirectorTest_test_register in test_redirector.o
      _WidgetRedirectorTest_test_register in test_redirector.o
      _WidgetRedirectorTest_test_original_command in test_redirector.o
      _WidgetRedirectorTest_test_original_command in test_redirector.o
      _WidgetRedirectorTest_test_original_command in test_redirector.o
      _WidgetRedirectorTest_test_unregister in test_redirector.o
      ...
  "_WidgetRedirectorTest_assertFalse", referenced from:
      _WidgetRedirectorTest_test_dispatch_intercept in test_redirector.o
  "_WidgetRedirectorTest_assertIn", referenced from:
      _WidgetRedirectorTest_test_repr in test_redirector.o
      _WidgetRedirectorTest_test_repr in test_redirector.o
      _WidgetRedirectorTest_test_register in test_redirector.o
      _WidgetRedirectorTest_test_register in test_redirector.o
  "_WidgetRedirectorTest_assertIsNone", referenced from:
      _WidgetRedirectorTest_test_unregister in test_redirector.o
  "_WidgetRedirectorTest_assertNotIn", referenced from:
      _WidgetRedirectorTest_test_unregister in test_redirector.o
      _WidgetRedirectorTest_test_unregister in test_redirector.o
  "_WidgetRedirectorTest_assertTrue", referenced from:
      _WidgetRedirectorTest_test_dispatch_intercept in test_redirector.o
  "_WidgetRedirectorTest_orig_insert", referenced from:
      _WidgetRedirectorTest_test_original_command in test_redirector.o
      _WidgetRedirectorTest_test_dispatch_bypass in test_redirector.o
  "_requires", referenced from:
      _InitCloseTest_setUpClass in test_redirector.o
      _WidgetRedirectorTest_setUpClass in test_redirector.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.85s
