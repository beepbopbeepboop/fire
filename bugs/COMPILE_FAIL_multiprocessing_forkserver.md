# COMPILE_FAIL: Lib/multiprocessing/forkserver.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py: In function '_alloc_ForkServer':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:83:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   83 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py: In function 'ForkServer___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:311:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  311 |                             # This shouldn't happen really
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:309:14: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  309 |                             os.close(child_w)
      |              ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:308:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  308 |                                 pass
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:307:14: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  307 |                                 # client vanished
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:306:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  306 |                             except BrokenPipeError:
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:305:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  305 |                                 write_signed(child_w, returncode)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:304:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  304 |                             try:
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:303:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  303 |                             # Send exit code to client process
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:302:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  302 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:301:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  301 |                             returncode = os.waitstatus_to_exitcode(sts)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:300:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  300 |                         if child_w is not None:
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:299:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  299 |                         child_w = pid_to_fd.pop(pid, None)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py: In function 'ForkServer__stop':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:53:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   53 |             return
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:51:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   51 |     def _stop_unlocked(self):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/forkserver.py:50:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
... (1184 more lines)
```

Exit code: 1
Elapsed: 9.92s
