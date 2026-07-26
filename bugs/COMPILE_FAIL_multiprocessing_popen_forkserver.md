# COMPILE_FAIL: Lib/multiprocessing/popen_forkserver.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         # Keep a duplicate of the data pipe's write end as a sentinel of the
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         with open(w, 'wb', closefd=True) as f:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |         if self.returncode is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:86:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:127:16: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/_stdlib.h:70,
                 from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdlib.h:58,
                 from popen_forkserver.ci:5:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/sys/wait.h:246:9: note: previous declaration of 'wait' with type 'pid_t(int *)' {aka 'int(int *)'}
  246 | pid_t   wait(int *) __DARWIN_ALIAS_C(wait);
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_DupFd___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:159:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:157:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py: In function '_DupFd_detach':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:33:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   33 |     def __init__(self, process_obj):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:31:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   31 |     DupFd = _DupFd
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:30:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   30 |     method = 'forkserver'
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:29:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   29 | class Popen(popen_fork.Popen):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:28:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   28 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:27:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   27 | #
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_forkserver.py:26:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   26 | # Start child process using a server process
      |           ^~~
... (319 more lines)
```

Exit code: 1
Elapsed: 10.01s
