# COMPILE_FAIL: Lib/test/test_tuple.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 |     # Does something only if RUN_ALL_HASH_TESTS is true.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:128:11: warning: unused variable '_tag' [-Wunused-variable]
  128 |     # - https://bugs.python.org/issue34751
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:133:11: warning: unused variable '_tag' [-Wunused-variable]
  133 |             return
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:148:11: warning: unused variable '_tag' [-Wunused-variable]
  148 |             del c
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:157:13: warning: unused variable '_tag' [-Wunused-variable]
  157 |                 prefix += f"FAIL {got} != {expected}; "
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py: In function 'TupleTest_test_getitem_error':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:307:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  307 |         gc.collect()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:305:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  305 |     def _tracked(self, t):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:304:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  304 |     # Checks that t continues to be tracked even after GC collection.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:303:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  303 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:302:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  302 |         self.assertFalse(gc.is_tracked(t), t)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:301:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  301 |         gc.collect()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:300:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  300 |         gc.collect()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:299:10: warning: variable 'msg' set but not used [-Wunused-but-set-variable]
  299 |         # Nested tuples can take several collections to untrack
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:298:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  298 |     def _not_tracked(self, t):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tuple.py:297:14: warning: variable 't' set but not used [-Wunused-but-set-variable]
... (4257 more lines)
```

Exit code: 1
Elapsed: 15.21s
