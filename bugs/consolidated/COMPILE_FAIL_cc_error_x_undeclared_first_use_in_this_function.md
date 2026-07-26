# COMPILE_FAIL: CC ERROR: 'X' undeclared (first use in this function)

**10 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:601:11: warning: unused variable '_tag' [-Wunused-variable]
  601 |         self.assertIn(gntn.result, idleConf.userCfg['highlight'])
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:606:11: warning: unused variable '_tag' [-Wunused-variable]
  606 |         eq = self.assertEqual
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:611:11: warning: unused variable '_tag' [-Wunused-variable]
  611 |         d.builtin_name.set('IDLE Classic')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:626:11: warning: unused variable '_tag' [-Wunused-variable]
  626 |         changes.add_option('highlight', first_new, 'hit-background', 'yellow')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:635:13: warning: unused variable '_tag' [-Wunused-variable]
  635 |            idleConf.GetThemeDict('user', second_new))
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function 'setUpModule':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:1032:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
 1032 |         b.insert(1, 'find')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py:1031:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1031 |         b.insert(0, 'copy')
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
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_configdialog.py: In function 'ConfigDialogTest_test_deactivate_current_co
```

## Affected files

- `Lib/idlelib/idle_test/test_configdialog.py`
- `Lib/test/profilee.py`
- `Lib/test/subprocessdata/sigchild_ignore.py`
- `Lib/test/test_asyncio/test_timeouts.py`
- `Lib/test/test_stable_abi_ctypes.py`
- `Lib/test/test_threading_local.py`
- `Lib/test/test_tkinter/test_loadtk.py`
- `Lib/test/test_urllib2net.py`
- `Lib/urllib/robotparser.py`
- `PC/validate_ucrtbase.py`
