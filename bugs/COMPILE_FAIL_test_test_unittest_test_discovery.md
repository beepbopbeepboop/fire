# COMPILE_FAIL: Lib/test/test_unittest/test_discovery.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py: In function '_alloc_TestableTestProgram':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:329:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  329 |                         return [self.path + ' load_tests']
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py: In function 'TestableTestProgram___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:773:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  773 |         if os.name == 'nt':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py: In function 'TestDiscovery_test_get_name_from_path':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:43:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   43 |             loader._get_name_from_path('/bar/baz.py')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:42:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   42 |         with self.assertRaises(AssertionError):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |         self.addCleanup(restore_listdir)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:60:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   60 |                       ['test4.py', 'test3.py', ]]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:59:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   59 |                        'test.foo', 'test-not-a-module.py', 'another_dir'],
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:58:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   58 |         path_lists = [['test2.py', 'test1.py', 'not_a_test.py', 'test_dir',
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:57:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   57 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:56:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   56 |             os.path.isdir = original_isdir
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:55:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   55 |         def restore_isdir():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:54:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   54 |         original_isdir = os.path.isdir
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:53:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   53 |             os.path.isfile = original_isfile
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:52:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   52 |         def restore_isfile():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:51:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   51 |         original_isfile = os.path.isfile
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_discovery.py:50:9: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
... (7988 more lines)
```

Exit code: 1
Elapsed: 16.13s
