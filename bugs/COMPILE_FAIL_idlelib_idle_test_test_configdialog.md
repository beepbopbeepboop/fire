# COMPILE_FAIL: Lib/idlelib/idle_test/test_configdialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:265:11: warning: unused variable '_tag' [-Wunused-variable]
  265 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:270:11: warning: unused variable '_tag' [-Wunused-variable]
  270 |     @classmethod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:275:11: warning: unused variable '_tag' [-Wunused-variable]
  275 |         page.paint_theme_sample = Func()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:290:11: warning: unused variable '_tag' [-Wunused-variable]
  290 |         for section in idleConf.GetSectionList('user', 'highlight'):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:299:13: warning: unused variable '_tag' [-Wunused-variable]
  299 |         tracers.detach()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function 'setUpModule':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:761:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  761 |         eq(d.custom_theme_on.state(), ('disabled',))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:760:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  760 |         eq(idleConf.GetSectionList('user', 'highlight'), [])
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function 'tearDownModule':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:50:3: error: 'root' undeclared (first use in this function)
   50 |     root = dialog = None
      |   ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:50:3: note: each undeclared identifier is reported only once for each function it appears in
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:50:3: error: 'dialog' undeclared (first use in this function)
   50 |     root = dialog = None
      |   ^ ~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:62:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   62 | class ButtonTest(unittest.TestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:60:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   60 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:58:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   58 |     def activate_config_changes(self):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:54:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   54 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:50:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   50 |     root = dialog = None
... (17724 more lines)
```

Exit code: 1
Elapsed: 12.74s
