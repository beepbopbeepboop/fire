# COMPILE_FAIL: Lib/test/test_unittest/testmock/testpatch.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_alloc_Container':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:424:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  424 |         foo = sentinel.Foo
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_alloc_Foo':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:438:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  438 |         foo.Foo = sentinel.Foo
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:829:9: error: conflicting types for 'PatchTest_test_autospec_function'; have 'int64_t(PatchTest_test_autospec_function_env *, int64_t)' {aka 'long long int(PatchTest_test_autospec_function_env *, long long int)'}
  829 | 
      |         ^                               
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:683:6: note: previous declaration of 'PatchTest_test_autospec_function' with type 'void(PatchTest *)'
  683 |             support.target = original
      |      ^      ~~~~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_alloc__get_proxy___setattr___env':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1078:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1078 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_get_proxy___setattr__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1092:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1092 |         patcher = patch(foo_name, autospec=Bar)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1090:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
 1090 |             extra = []
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1089:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
 1089 |         class Bar(Foo):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1088:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
 1088 |     def test_autospec_with_object(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1087:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
 1087 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:1086:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1086 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_alloc__get_proxy___delattr___env':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:43:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   43 | # for use in the test
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py: In function '_get_proxy___delattr__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:53:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   53 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testpatch.py:51:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   51 |     def g(self): pass
      |           ^~~
... (12882 more lines)
```

Exit code: 1
Elapsed: 15.01s
