# COMPILE_FAIL: Lib/idlelib/idle_test/test_outwin.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 |     def test_write(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 |         eq(get('1.0', '1.end'), 'test text')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |         eq(get('2.0', '2.end'), 'Line 2')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:95:13: warning: unused variable '_tag' [-Wunused-variable]
   95 |         eq(get('mytag.first', 'mytag.last'), test_text)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py: In function 'OutputWindowTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:19:6: error: request for member 'root' in something not a structure or union
   19 |         root = cls.root = Tk()
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:21:6: error: request for member 'window' in something not a structure or union
   21 |         w = cls.window = outwin.OutputWindow(None, None, None, root)
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:22:6: error: request for member 'text' in something not a structure or union
   22 |         cls.text = w.text = Text(root)
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:22:4: error: request for member 'text' in something not a structure or union
   22 |         cls.text = w.text = Text(root)
      |    ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   27 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:35:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   35 |     def setUp(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:267:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:265:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:264:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:263:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:262:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:261:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:260:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:259:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:258:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_outwin.py:257:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
... (1275 more lines)
```

Exit code: 1
Elapsed: 10.81s
