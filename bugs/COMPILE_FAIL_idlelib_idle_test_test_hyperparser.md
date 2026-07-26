# COMPILE_FAIL: Lib/idlelib/idle_test/test_hyperparser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py: In function '_alloc_DummyEditwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:83:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   83 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py: In function 'DummyEditwin___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:346:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:344:14: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:343:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:342:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:341:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:340:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:339:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:338:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:337:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:336:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:335:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:334:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:333:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py: In function 'HyperParserTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 |         del cls.root
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:47:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   47 |         del cls.text, cls.editwin
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:46:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   46 |     def tearDownClass(cls):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:45:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   45 |     @classmethod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:44:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   44 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:43:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   43 |         cls.editwin = DummyEditwin(cls.text)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:42:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   42 |         cls.text = Text(cls.root)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:41:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   41 |         cls.root.withdraw()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:40:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   40 |         cls.root = Tk()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_hyperparser.py:39:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   39 |         requires('gui')
      |          ^~~~
... (1804 more lines)
```

Exit code: 1
Elapsed: 10.09s
