# COMPILE_FAIL: Lib/test/test_unittest/testmock/testmagicmethods.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:185:11: warning: unused variable '_tag' [-Wunused-variable]
  185 |         self.assertRaises(TypeError, lambda: MagicMock() < object())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:190:11: warning: unused variable '_tag' [-Wunused-variable]
  190 |         self.assertRaises(TypeError, lambda: MagicMock() > MagicMock())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:195:11: warning: unused variable '_tag' [-Wunused-variable]
  195 |         self.assertRaises(TypeError, lambda: object() >= MagicMock())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:210:11: warning: unused variable '_tag' [-Wunused-variable]
  210 |             mock.__eq__ = eq
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:219:13: warning: unused variable '_tag' [-Wunused-variable]
  219 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py: In function 'TestMockingMagicMethods_test_deleting_magic_methods':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:444:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  444 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:442:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  442 |         self.assertEqual(_get_type(returned), MagicMock)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:441:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  441 |         returned = mock()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:440:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  440 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:439:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  439 |         self.assertEqual(_get_type(attr), MagicMock)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:438:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  438 |             return type(obj).__mro__[1]
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:437:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  437 |             # so the real type is the second in the mro
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:436:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  436 |             # the type of every mock (or magicmock) is a custom subclass
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:435:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  435 |         def _get_type(obj):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmagicmethods.py:434:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
... (4127 more lines)
```

Exit code: 1
Elapsed: 14.44s
