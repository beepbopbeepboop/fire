# COMPILE_FAIL: Lib/test/test_unparse.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unparse.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CosmeticTestCase_assertASTEqual", referenced from:
      _CosmeticTestCase_check_ast_roundtrip in test_unparse.o
      _CosmeticTestCase_test_docstrings_negative_cases in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      _CosmeticTestCase_test_multiquote_joined_string in test_unparse.o
      ...
  "_CosmeticTestCase_assertEqual", referenced from:
      _CosmeticTestCase_check_src_roundtrip in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      _CosmeticTestCase_test_simple_expressions_parens in test_unparse.o
      ...
  "_CosmeticTestCase_assertNotEqual", referenced from:
      _CosmeticTestCase_check_src_dont_roundtrip in test_unparse.o
      _CosmeticTestCase_test_docstrings_negative_cases in test_unparse.o
  "_CosmeticTestCase_assertRaises", referenced from:
... (117 more lines)
```

Exit code: 1
Elapsed: 17.63s
