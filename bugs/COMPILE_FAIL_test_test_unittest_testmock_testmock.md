# COMPILE_FAIL: Lib/test/test_unittest/testmock/testmock.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function '_alloc_Iter':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:241:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  241 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function '_alloc_Something':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:255:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  255 |             with self.assertRaisesRegex(InvalidSpecError,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function '_alloc_SomethingElse':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:269:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  269 |         result = "real result"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:651:51: error: 'something_0c85c9' undeclared here (not in a function)
  651 |         mock = Mock()
      |                                                   ^               
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function 'Iter___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:928:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  928 |                                 mock.assert_called_with)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:926:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  926 |         mock = Mock()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:925:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  925 |     def test_assert_called_with_message(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:924:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  924 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:923:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  923 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:922:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  922 |         self.assertRaises(KeyboardInterrupt, mock)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:921:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  921 |         mock = Mock(side_effect=KeyboardInterrupt('foo'))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:920:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  920 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:919:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  919 |         self.assertRaises(KeyboardInterrupt, mock)
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function 'Iter___iter__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |         return next(self.thing)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testmock.py: In function 'Iter_next':
... (19710 more lines)
```

Exit code: 1
Elapsed: 14.87s
