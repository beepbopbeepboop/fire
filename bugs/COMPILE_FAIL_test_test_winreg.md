# COMPILE_FAIL: Lib/test/test_winreg.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:242:11: warning: unused variable '_tag' [-Wunused-variable]
  242 |         h.Close()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:247:11: warning: unused variable '_tag' [-Wunused-variable]
  247 |         self.assertRaises(OSError, connect)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:252:11: warning: unused variable '_tag' [-Wunused-variable]
  252 |         self.assertEqual(r, os.environ["windir"] + "\\test")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:267:11: warning: unused variable '_tag' [-Wunused-variable]
  267 |         done = False
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:276:13: warning: unused variable '_tag' [-Wunused-variable]
  276 |                         use_short = not use_short
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function 'HeapTypeTests_test_have_gc':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:469:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  469 |             self.assertTrue(QueryReflectionKey(key))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:467:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  467 |         with OpenKey(HKEY_LOCAL_MACHINE, "Software") as key:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:466:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  466 |         # on a key which isn't on the reflection list with no consequences.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:465:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  465 |         # Test that we can call the query, enable, and disable functions
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:464:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  464 |     def test_reflection_functions(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py: In function 'HeapTypeTests_test_immutable':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |         except OSError:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:73:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   73 |         try:
      |          ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:72:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   72 |     def delete_tree(self, root, subkey):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winreg.py:71:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   71 | 
      |          ^  
... (6839 more lines)
```

Exit code: 1
Elapsed: 12.82s
