# COMPILE_FAIL: Lib/unittest/case.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:425:32: error: expected declaration specifiers or '...' before '*' token
  425 |         self._testMethodName = methodName
      |                                ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:426:30: error: expected declaration specifiers or '...' before '*' token
  426 |         self._outcome = None
      |                              ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:427:32: error: expected declaration specifiers or '...' before '*' token
  427 |         self._testMethodDoc = 'No test'
      |                                ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:429:31: error: expected declaration specifiers or '...' before '*' token
  429 |             testMethod = getattr(self, methodName)
      |                               ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:430:30: error: expected declaration specifiers or '...' before '*' token
  430 |         except AttributeError:
      |                              ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:431:33: error: expected declaration specifiers or '...' before '*' token
  431 |             if methodName != 'runTest':
      |                                 ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:432:40: error: expected declaration specifiers or '...' before '*' token
  432 |                 # we allow instantiation with no explicit method name
      |                                        ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:433:42: error: expected declaration specifiers or '...' before '*' token
  433 |                 # but not an *incorrect* or missing method name
      |                                          ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:434:39: error: expected declaration specifiers or '...' before '*' token
  434 |                 raise ValueError("no such test method in %s: %s" %
      |                                       ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:435:37: error: expected declaration specifiers or '...' before '*' token
  435 |                       (self.__class__, methodName))
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:436:33: error: expected declaration specifiers or '...' before '*' token
  436 |         else:
      |                                 ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:437:31: error: expected declaration specifiers or '...' before '*' token
  437 |             self._testMethodDoc = testMethod.__doc__
      |                               ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:438:34: error: expected declaration specifiers or '...' before '*' token
  438 |         self._cleanups = []
      |                                  ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:439:36: error: expected declaration specifiers or '...' before '*' token
  439 |         self._subtest = None
      |                                    ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:440:37: error: expected declaration specifiers or '...' before '*' token
  440 | 
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:441:46: error: expected declaration specifiers or '...' before '*' token
  441 |         # Map types to custom assertEqual functions that will compare
      |                                              ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/case.py:442:38: error: expected declaration specifiers or '...' before '*' token
... (29482 more lines)
```

Exit code: 1
Elapsed: 15.43s
