# COMPILE_FAIL: Lib/test/test_unittest/test_break.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_break.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_TestBreakDefaultIntHandler_assertEqual", referenced from:
      _TestBreakDefaultIntHandler_testTwoResults_test_function in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      ...
  "_TestBreakDefaultIntHandler_assertFalse", referenced from:
      _TestBreakDefaultIntHandler_testTwoResults_test_function in test_break.o
      _TestBreakDefaultIntHandler_testRemoveResult in test_break.o
      _TestBreakDefaultIntHandler_testRemoveResult in test_break.o
  "_TestBreakDefaultIntHandler_assertIn", referenced from:
      _TestBreakDefaultIntHandler_testRegisterResult in test_break.o
      _TestBreakDefaultIntHandler_testRunner in test_break.o
  "_TestBreakDefaultIntHandler_assertIsNone", referenced from:
      _TestBreakDefaultIntHandler_testWeakReferences in test_break.o
  "_TestBreakDefaultIntHandler_assertNotEqual", referenced from:
      _TestBreakDefaultIntHandler_testInstallHandler in test_break.o
      _TestBreakDefaultIntHandler_testInterruptCaught_test_function in test_break.o
      _TestBreakDefaultIntHandler_testMainInstallsHandler in test_break.o
      _TestBreakDefaultIntHandler_testRemoveHandlerAsDecorator in test_break.o
  "_TestBreakDefaultIntHandler_assertNotIn", referenced from:
      _TestBreakDefaultIntHandler_testRegisterResult in test_break.o
  "_TestBreakDefaultIntHandler_assertRaises", referenced from:
      _TestBreakDefaultIntHandler_testSecondInterrupt_test_function in test_break.o
  "_TestBreakDefaultIntHandler_assertTrue", referenced from:
      _TestBreakDefaultIntHandler_testInstallHandler in test_break.o
      _TestBreakDefaultIntHandler_testInterruptCaught_test in test_break.o
      _TestBreakDefaultIntHandler_testInterruptCaught_test_function in test_break.o
      _TestBreakDefaultIntHandler_testSecondInterrupt_test in test_break.o
      _TestBreakDefaultIntHandler_testSecondInterrupt_test_function in test_break.o
      _TestBreakDefaultIntHandler_testTwoResults_test_function in test_break.o
      _TestBreakDefaultIntHandler_testTwoResults_test_function in test_break.o
      ...
  "_TestBreakDefaultIntHandler_fail", referenced from:
      _TestBreakDefaultIntHandler_testInstallHandler in test_break.o
      _TestBreakDefaultIntHandler_testInterruptCaught_test_function in test_break.o
      _TestBreakDefaultIntHandler_testSecondInterrupt_test in test_break.o
      _TestBreakDefaultIntHandler_testTwoResults_test_function in test_break.o
      _TestBreakDefaultIntHandler_testHandlerReplacedButCalled_test_function in test_break.o
  "_TestBreakDefaultIntHandler_skipTest", referenced from:
      _TestBreakDefaultIntHandler_testSecondInterrupt in test_break.o
      _TestBreakDefaultIntHandler_testHandlerReplacedButCalled in test_break.o
  "_TestBreakDefaultIntHandler_subTest", referenced from:
      _TestBreakDefaultIntHandler_withRepeats in test_break.o
  "_TestBreakSignalDefault_assertEqual", referenced from:
... (117 more lines)
```

Exit code: 1
Elapsed: 18.29s
