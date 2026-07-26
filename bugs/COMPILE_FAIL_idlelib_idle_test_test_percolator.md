# COMPILE_FAIL: Lib/idlelib/idle_test/test_percolator.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py: In function '_alloc_MyFilter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |         self.assertEqual(self.filter_one.delegate, self.percolator.bottom)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py: In function 'MyFilter___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:239:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:237:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:236:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:235:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:234:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:233:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:232:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py: In function 'MyFilter_insert':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:28:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   28 |         self.delegate.insert(index, chars)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:26:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   26 |     def lowercase_insert(self, index, chars, tags=None):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:25:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   25 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:24:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   24 |         self.delegate.insert(index, chars)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:23:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   23 |         chars = chars.upper()
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:22:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   22 |     def uppercase_insert(self, index, chars, tags=None):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:21:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   21 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:20:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   20 |         self.delegate.delete(*args)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:19:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   19 |         self.delete_called_with = args
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:18:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   18 |     def delete(self, *args):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:17:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   17 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py: In function 'MyFilter_delete':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_percolator.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   32 | 
... (945 more lines)
```

Exit code: 1
Elapsed: 10.79s
