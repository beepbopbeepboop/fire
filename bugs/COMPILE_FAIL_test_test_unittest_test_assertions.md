# COMPILE_FAIL: Lib/test/test_unittest/test_assertions.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:121:11: warning: unused variable '_tag' [-Wunused-variable]
  121 |                 self.assertRaises(ValueError, self.foo)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:126:11: warning: unused variable '_tag' [-Wunused-variable]
  126 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:131:11: warning: unused variable '_tag' [-Wunused-variable]
  131 |         gc_collect()  # For PyPy or other GCs.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:146:11: warning: unused variable '_tag' [-Wunused-variable]
  146 |     This actually tests all the message behaviour for
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:155:13: warning: unused variable '_tag' [-Wunused-variable]
  155 |                 pass
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py: In function 'Test_Assertions_test_AlmostEqual':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:414:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  414 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:412:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
  412 |                                '^"regex" does not match "foo"$',
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:411:10: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  411 |                               ['^"regex" does not match "foo"$', '^oops$',
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:410:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
  410 |                               raise_wrong_message,
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:409:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
  409 |         self.assertMessagesCM('assertWarnsRegex', (UserWarning, 'regex'),
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:408:10: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
  408 |             warnings.warn('foo')
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:407:7: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
  407 |         def raise_wrong_message():
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:406:7: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
  406 |         # test warning raised but with wrong message
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:405:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  405 |                                '^UserWarning not triggered : oops$'])
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_assertions.py:404:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
... (2884 more lines)
```

Exit code: 1
Elapsed: 15.57s
