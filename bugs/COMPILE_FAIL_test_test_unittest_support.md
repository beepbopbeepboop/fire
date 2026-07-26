# COMPILE_FAIL: Lib/test/test_unittest/support.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |         self._events.append('addSkip')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |         super().addExpectedFailure(*args)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 |     A TestResult implementation which records its method calls.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:108:13: warning: unused variable '_tag' [-Wunused-variable]
  108 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function 'TestEquality_test_eq':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:231:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:229:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:228:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function 'TestEquality_test_ne':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:19:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   19 | class TestHashing(object):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:17:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   17 |             self.assertNotEqual(obj_2, obj_1)
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:16:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   16 |             self.assertNotEqual(obj_1, obj_2)
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py: In function 'TestHashing_test_hash':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   27 |                     self.fail("%r and %r do not hash equal" % (obj_1, obj_2))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:25:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   25 |             try:
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:24:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   24 |         for obj_1, obj_2 in self.eq_pairs:
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:23:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   23 |     def test_hash(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/support.py:22:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   22 |     # Check for a valid __hash__ implementation
... (1108 more lines)
```

Exit code: 1
Elapsed: 14.96s
