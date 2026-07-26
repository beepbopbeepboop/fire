# COMPILE_FAIL: Lib/test/test_userstring.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py: In function '_alloc_UserStringSubclass':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:81:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   81 |         self.assertEqual(u, "spameggs")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py: In function '_alloc_UserStringSubclass2':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:95:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   95 |         self.assertEqual(u, "spameggs")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py: In function 'UserStringTest_checkequal':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:261:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:259:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:258:11: warning: variable 'realresult' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:257:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:256:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:255:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py: In function 'UserStringTest_checkraises':
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 |         object = self.fixtype(object)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:49:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   49 |         # we don't fix the arguments, because UserString can't cope with it
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:61:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   61 |         self.assertIs(type(u.data), str)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:59:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   59 |         u = UserString(42)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:58:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   58 |         self.assertIs(type(u.data), str)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:57:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   57 |         self.assertEqual(u.data, "spam")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:56:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   56 |         u = UserString(u)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:55:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   55 |         self.assertIs(type(u.data), str)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:54:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   54 |         self.assertEqual(u.data, "spam")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:53:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   53 |         u = UserString("spam")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_userstring.py:52:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   52 |     def test_data(self):
      |           ^~~~
... (454 more lines)
```

Exit code: 1
Elapsed: 13.77s
