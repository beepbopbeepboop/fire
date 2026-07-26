# COMPILE_FAIL: Lib/test/test_tkinter/test_widgets.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:785:11: warning: unused variable '_tag' [-Wunused-variable]
  785 |         'xscrollcommand', 'xscrollincrement',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:790:11: warning: unused variable '_tag' [-Wunused-variable]
  790 |     else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:795:11: warning: unused variable '_tag' [-Wunused-variable]
  795 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:810:11: warning: unused variable '_tag' [-Wunused-variable]
  810 |                              conv=float)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:819:13: warning: unused variable '_tag' [-Wunused-variable]
  819 |         self.checkParams(widget, 'offset',
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py: In function 'AbstractToplevelTest_test_configure_class':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 |         self.assertEqual(widget2['container'], 1 if self.wantobjects else '1')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:57:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   57 |                 errmsg="can't modify -container option after widget is created")
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:56:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   56 |         self.checkInvalidParam(widget, 'container', 1,
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:55:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   55 |         self.assertEqual(widget['container'], 0 if self.wantobjects else '0')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:54:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   54 |         widget = self.create()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:53:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   53 |     def test_configure_container(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:52:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   52 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:51:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   51 |         self.assertEqual(widget2['colormap'], 'new')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:50:14: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   50 |         widget2 = self.create(colormap='new')
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_widgets.py:49:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
... (16361 more lines)
```

Exit code: 1
Elapsed: 61.38s
