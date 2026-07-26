# COMPILE_FAIL: Lib/test/test_unittest/testmock/testhelpers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testhelpers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_SpecSignatureTest_test_skip_attributeerrors_lambda_1", referenced from:
      _SpecSignatureTest_test_skip_attributeerrors in testhelpers.o
  "_SpecSignatureTest_test_skip_attributeerrors_lambda_2", referenced from:
      _SpecSignatureTest_test_skip_attributeerrors in testhelpers.o
  "_SpecSignatureTest_test_spec_function_no_name_lambda_3", referenced from:
      _SpecSignatureTest_test_spec_function_no_name in testhelpers.o
  "__Call", referenced from:
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      _CallTest_test_call_with_call in testhelpers.o
      ...
  "__callable", referenced from:
      _TestCallablePredicate_test_type in testhelpers.o
      _TestCallablePredicate_test_call_magic_method in testhelpers.o
      _TestCallablePredicate_test_staticmethod in testhelpers.o
      _TestCallablePredicate_test_non_callable_staticmethod in testhelpers.o
      _TestCallablePredicate_test_classmethod in testhelpers.o
      _TestCallablePredicate_test_non_callable_classmethod in testhelpers.o
  "_call", referenced from:
      _AnyTest_test_any_mock_calls_comparison_order in testhelpers.o
      _AnyTest_test_any_mock_calls_comparison_order in testhelpers.o
      _AnyTest_test_any_mock_calls_comparison_order in testhelpers.o
... (24 more lines)
```

Exit code: 1
Elapsed: 17.58s
