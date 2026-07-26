# COMPILE_FAIL: CC ERROR: expected expression before 'X'

**5 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |         # Called at the beginning of each test. See TestCase.run.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |                                       args=(case, r, barrier),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 |         # Note: We can't call result.addError, result.addFailure, etc. because
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:69:13: warning: unused variable '_tag' [-Wunused-variable]
   69 |             result.unexpectedSuccesses.extend(r.unexpectedSuccesses)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function 'ParallelTestCase___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:152:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:150:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:149:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:148:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:147:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:146:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:145:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:144:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:143:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:142:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:141:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function 'ParallelTestCase___str__':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   32 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py: In function 'ParallelTestCase_run_worker':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/parallel_case.py:29:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   29 |             stopTestRun = getattr(result, 'stopTestRun', None)
      | ^   
/Users/mrs/net/Python-3.14.6/L
```

## Affected files

- `Lib/test/libregrtest/parallel_case.py`
- `Lib/test/test_named_expressions.py`
- `Lib/test/test_turtle.py`
- `Lib/test/test_type_params.py`
- `Lib/test/test_unittest/test_setups.py`
