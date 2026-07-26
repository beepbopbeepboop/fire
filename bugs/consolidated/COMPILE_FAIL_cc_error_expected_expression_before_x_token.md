# COMPILE_FAIL: CC ERROR: expected expression before 'X' token

**4 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |             if x != 0.0:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |             else:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 | class ComplexesAreIdenticalMixin(FloatsAreIdenticalMixin):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:80:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py: In function 'ExceptionIsLikeMixin_assertExceptionIsLike':
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:42:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   42 |         if isnan(x) or isnan(y):
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:26:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   26 |             self.assertEqual(len(exc.exceptions), len(template.exceptions))
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:29:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   29 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:22:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   22 |             self.assertEqual(exc.__class__, template.__class__)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:25:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   25 |             self.assertEqual(exc.message, template.message)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:19:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   19 |             self.fail(f"expected an exception like {template!r}, got None")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:22:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   22 |             self.assertEqual(exc.__class__, template.__class__)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:16:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   16 |             self.fail(f"unexpected exception: {exc}")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:26:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   26 |             self.assertEqual(len(exc.exceptions), len(template.exceptions))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:23:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   23 |             self.assertEqual(exc.args[0], template.args[0])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:12:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   12 |         if exc is None and template is None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:16:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   16 |             self.fail(f"unexpected exception: {exc}")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/testcase.py:238:1: warning: label 'bb_2' defined but not used [-Wunuse
```

## Affected files

- `Lib/test/support/testcase.py`
- `Lib/test/test_type_aliases.py`
- `Lib/test/test_unittest/test_runner.py`
- `Tools/jit/_targets.py`
