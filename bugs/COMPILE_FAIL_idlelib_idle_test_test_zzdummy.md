# COMPILE_FAIL: Lib/idlelib/idle_test/test_zzdummy.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py: In function '_alloc_DummyEditwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:56:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   56 |         cls.root.update_idletasks()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py: In function 'DummyEditwin___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:260:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:258:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:257:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:256:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:255:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:254:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:253:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:252:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:251:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:250:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:249:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:248:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:247:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:246:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:245:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:244:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:243:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:242:18: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:241:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:240:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:239:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:238:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:237:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py: In function 'ZZDummyTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:46:6: error: request for member 'root' in something not a structure or union
   46 |         root = cls.root = Tk()
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:48:6: error: request for member 'text' in something not a structure or union
   48 |         text = cls.text = Text(cls.root)
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:69:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   69 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:67:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   67 |         zz = self.zz = zzdummy.ZzDummy(self.editor)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:66:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   66 |         text.undo_block_stop.reset_mock()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:65:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   65 |         text.undo_block_start.reset_mock()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_zzdummy.py:64:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   64 |         text.insert('1.0', code_sample)
... (1024 more lines)
```

Exit code: 1
Elapsed: 10.96s
