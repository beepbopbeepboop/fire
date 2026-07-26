# COMPILE_FAIL: Lib/idlelib/idle_test/test_text.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:101:11: warning: unused variable '_tag' [-Wunused-variable]
  101 |         Equal(get('1.0', 'end'), self.hwn)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:106:11: warning: unused variable '_tag' [-Wunused-variable]
  106 |         delete('insert', '5.5')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:121:11: warning: unused variable '_tag' [-Wunused-variable]
  121 |         delete('1.0')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:130:13: warning: unused variable '_tag' [-Wunused-variable]
  130 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function 'TextTest_test_init':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:312:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:310:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:309:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:308:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:307:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:306:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:305:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:304:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:303:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:302:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:301:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:300:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:299:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:298:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:297:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py: In function 'TextTest_test_index_empty':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:33:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   33 |         index = self.text.index
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:39:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   39 |         for dex in '1.0 lineend', '1.end', '1.33':
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:47:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   47 |         Equal = self.assertEqual
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_text.py:43:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   43 |             self.assertEqual(index(dex), '3.0')
      | ^   
... (6353 more lines)
```

Exit code: 1
Elapsed: 10.33s
