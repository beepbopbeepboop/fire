# COMPILE_FAIL: Lib/test/test_userdict.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_alloc_UserDictSubclass':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:121:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  121 |         for i in u2.keys():
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_alloc_UserDictSubclass2':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:135:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  135 |         # Test setdefault
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:149:11: warning: unused variable '_tag' [-Wunused-variable]
  149 |         # Test popitem
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:154:11: warning: unused variable '_tag' [-Wunused-variable]
  154 |     def test_init(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:159:11: warning: unused variable '_tag' [-Wunused-variable]
  159 |                          [('dict', 42)])
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:174:11: warning: unused variable '_tag' [-Wunused-variable]
  174 |         self.assertEqual(u.data, d)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:183:13: warning: unused variable '_tag' [-Wunused-variable]
  183 |         u = UserDict(a=1, b=2)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py: In function 'UserDictTest_test_all':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userdict.py:132:3: internal compiler error: in build2, at tree.cc:5208
  132 |         keys = u2.keys()
      |   ^    
Please submit a full bug report, with preprocessed source (by using -freport-bug).
See <https://trac.macports.org/newticket> for instructions.

```

Exit code: 1
Elapsed: 13.83s
