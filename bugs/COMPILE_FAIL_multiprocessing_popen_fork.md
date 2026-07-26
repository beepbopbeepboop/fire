# COMPILE_FAIL: Lib/multiprocessing/popen_fork.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     def _send_signal(self, sig):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |                 pass
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |     def interrupt(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         # (gh-80849) rather than closing it and launching its own.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |         if self.pid == 0:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function 'Popen___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:162:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:161:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:160:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:159:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:158:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function 'Popen_duplicate_for_child':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |         if self.returncode is None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py: In function 'Popen_poll':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:37:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   37 |     def wait(self, timeout=None):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:43:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   43 |             # This shouldn't block if wait() returned successfully.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:34:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   34 |                 self.returncode = os.waitstatus_to_exitcode(sts)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:111:1: warning: label 'bb_9' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:37:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   37 |     def wait(self, timeout=None):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:85:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   85 |                 os.close(parent_r)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_fork.py:101:1: warning: label 'bb_6' defined but not used [-Wunused-label]
... (632 more lines)
```

Exit code: 1
Elapsed: 9.90s
