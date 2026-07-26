# COMPILE_FAIL: Lib/idlelib/idle_test/test_textview.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py: In function '_alloc_VW':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 |         view = tv.view_file(root, 'Title', __file__, 'ascii', modal=False)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py: In function 'setUpModule':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:373:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py: In function 'tearDownModule':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:32:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   32 | # Have also gotten tk error 'can't invoke "event" command'.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:31:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   31 | # modal=True, _utest=False, test hangs on call to wait_window.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:30:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   30 | # If we call ViewWindow or wrapper functions with defaults
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:28:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   28 |     del root
      |           ^~ 
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py: In function 'ViewWindowTest_setUp':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:41:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   41 | # Call wrapper class VW with mock wait_window.
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:39:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   39 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:38:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   38 |     wait_window = Func()
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:37:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   37 |     grab_set = Func()
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:36:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   36 |     transient = Func()
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:35:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   35 | class VW(tv.ViewWindow):  # Used in ViewWindowTest.
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:34:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   34 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py: In function 'ViewWindowTest_test_init_modal':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:84:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   84 |         cls.root = root = Tk()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:82:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   82 |     @classmethod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_textview.py:81:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
... (1669 more lines)
```

Exit code: 1
Elapsed: 10.48s
