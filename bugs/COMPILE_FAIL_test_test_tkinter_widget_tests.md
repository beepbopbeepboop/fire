# COMPILE_FAIL: Lib/test/test_tkinter/widget_tests.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:254:11: warning: unused variable '_tag' [-Wunused-variable]
  254 |         widget = self.create()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:259:11: warning: unused variable '_tag' [-Wunused-variable]
  259 |             self.checkPixelsParam(widget, 'bd', 0, 1.3, 2.6, 6, '10p')
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:264:11: warning: unused variable '_tag' [-Wunused-variable]
  264 |         self.checkPixelsParam(widget, 'highlightthickness',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:279:11: warning: unused variable '_tag' [-Wunused-variable]
  279 |     def test_configure_pady(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:288:13: warning: unused variable '_tag' [-Wunused-variable]
  288 | class StandardOptionsTests(PixelOptionsTests):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py: In function 'AbstractWidgetTest_scaling':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:33:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   33 |         if isinstance(value, tuple):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:30:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   30 |     def _str(self, value):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:37:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   37 |     def assertEqual2(self, actual, expected, msg=None, eq=object.__eq__):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:673:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   27 |             self._scaling = float(self.root.call('tk', 'scaling'))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:664:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:662:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:661:7: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:660:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:659:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:658:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:657:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:656:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:655:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:654:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:653:7: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:652:9: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:651:9: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:650:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/widget_tests.py:649:9: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
... (4616 more lines)
```

Exit code: 1
Elapsed: 61.04s
