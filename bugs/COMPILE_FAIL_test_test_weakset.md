# COMPILE_FAIL: Lib/test/test_weakset.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py: In function '_alloc_Foo':
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:153:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  153 |         self.assertFalse(self.abcde_weakset >= self.def_weakset)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py: In function '_alloc_RefCycle':
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:167:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  167 |         self.assertFalse(self.abcde_weakset > self.def_weakset)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py: In function 'RefCycle___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:399:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  399 |         with testcontext() as u:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:397:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  397 |         self.assertIn(u, s)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:396:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  396 |             s.add(u)
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:395:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  395 |         with testcontext() as u:
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:394:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  394 |         self.assertNotIn(u, s)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py: In function 'TestWeakSet_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:32:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   32 |         self.ab_items = [ustr(c) for c in 'ab']
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:32:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   32 |         self.ab_items = [ustr(c) for c in 'ab']
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:32:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   32 |         self.ab_items = [ustr(c) for c in 'ab']
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:32:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   32 |         self.ab_items = [ustr(c) for c in 'ab']
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:31:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   31 |         self.items2 = [ustr(c) for c in ('x', 'y', 'z')]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:31:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   31 |         self.items2 = [ustr(c) for c in ('x', 'y', 'z')]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:31:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   31 |         self.items2 = [ustr(c) for c in ('x', 'y', 'z')]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_weakset.py:31:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   31 |         self.items2 = [ustr(c) for c in ('x', 'y', 'z')]
      | ^   
... (4242 more lines)
```

Exit code: 1
Elapsed: 12.74s
