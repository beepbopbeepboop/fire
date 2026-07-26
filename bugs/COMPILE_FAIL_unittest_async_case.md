# COMPILE_FAIL: Lib/unittest/async_case.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     async def asyncTearDown(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         # the function exists because it has a different semantics
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         # We intentionally don't add inspect.iscoroutinefunction() check
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         # statement.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |                 cls.__enter__
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function 'IsolatedAsyncioTestCase___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:175:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:173:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:172:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:171:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:170:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:169:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function 'IsolatedAsyncioTestCase_asyncSetUp':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:48:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   48 |         pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function 'IsolatedAsyncioTestCase_asyncTearDown':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:50:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   50 |     def addAsyncCleanup(self, func, /, *args, **kwargs):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py: In function 'IsolatedAsyncioTestCase_addAsyncCleanup':
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 |         # to check for async function reliably:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:57:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   57 |         # We intentionally don't add inspect.iscoroutinefunction() check
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:56:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   56 |         #
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:55:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   55 |         # but addAsyncCleanup() accepts coroutines
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/async_case.py:54:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (735 more lines)
```

Exit code: 1
Elapsed: 14.37s
