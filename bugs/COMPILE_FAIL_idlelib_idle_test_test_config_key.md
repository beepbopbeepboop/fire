# COMPILE_FAIL: Lib/idlelib/idle_test/test_config_key.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:133:11: warning: unused variable '_tag' [-Wunused-variable]
  133 |                 if child._name == 'keyseq_advanced':
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:138:11: warning: unused variable '_tag' [-Wunused-variable]
  138 |         self.assertFalse(dialog.advanced)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:143:11: warning: unused variable '_tag' [-Wunused-variable]
  143 |         # Toggle to advanced.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:158:11: warning: unused variable '_tag' [-Wunused-variable]
  158 | class KeySelectionTest(unittest.TestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:167:13: warning: unused variable '_tag' [-Wunused-variable]
  167 |                 yview = Func()
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py: In function 'ValidationTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:360:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:358:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:357:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:356:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  356 |     unittest.main(verbosity=2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:355:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  355 | if __name__ == '__main__':
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:354:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  354 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:353:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  353 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:352:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  352 |         eq(tr('*', ['Shift']), 'Key-asterisk')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:351:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  351 |         # 'Shift' doesn't change case when it's not a single char.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:350:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  350 |         eq(tr('Page Up', []), 'Key-Prior')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:349:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  349 |         # Convert key name to keysym.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config_key.py:348:14: warning: variable 'keylist' set but not used [-Wunused-but-set-variable]
... (2997 more lines)
```

Exit code: 1
Elapsed: 12.07s
