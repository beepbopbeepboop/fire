# COMPILE_FAIL: Lib/idlelib/idle_test/test_colorizer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:144:11: warning: unused variable '_tag' [-Wunused-variable]
  144 |     def setUp(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:149:11: warning: unused variable '_tag' [-Wunused-variable]
  149 |         self.text.delete('1.0', 'end')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:154:11: warning: unused variable '_tag' [-Wunused-variable]
  154 |         color = self.color
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:169:11: warning: unused variable '_tag' [-Wunused-variable]
  169 |     @classmethod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:178:13: warning: unused variable '_tag' [-Wunused-variable]
  178 |     @classmethod
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py: In function 'FunctionTest_test_any':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:81:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   81 |         eq(m.groupdict()['KEYWORD'], 'def')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:79:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   79 |         line = 'def f():\n    print("hello")\n'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:78:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   78 |         eq = self.assertEqual
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:77:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   77 |         prog = colorizer.prog
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:76:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   76 |     def test_prog(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:75:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   75 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:74:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   74 |         self.assertTrue(colorizer.make_pat())
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:73:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   73 |         # Tested in more detail by testing prog.
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:72:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   72 |     def test_make_pat(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_colorizer.py:71:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (5709 more lines)
```

Exit code: 1
Elapsed: 12.72s
