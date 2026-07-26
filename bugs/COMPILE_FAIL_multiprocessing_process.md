# COMPILE_FAIL: Lib/multiprocessing/process.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function '_alloc_AuthenticationString':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:143:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  143 |         '''
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function '_alloc__MainProcess':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:157:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  157 |         if res is not None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function '_alloc__ParentProcess':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:171:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  171 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:421:16: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
  421 |     def close(self):
      |                ^~~~
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/_stdlib.h:70,
                 from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdlib.h:58,
                 from process.ci:5:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/sys/wait.h:246:9: note: previous declaration of 'wait' with type 'pid_t(int *)' {aka 'int(int *)'}
  246 | pid_t   wait(int *) __DARWIN_ALIAS_C(wait);
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function 'current_process':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:584:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function 'active_children':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:46:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   46 |     '''
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function 'parent_process':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:53:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   53 |     Return process object representing the parent process
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function '_cleanup':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:85:7: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   85 |         self._config = _current_process._config.copy()
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function 'BaseProcess__Popen':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:83:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   83 |         count = next(_process_counter)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py: In function 'BaseProcess___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:99:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   99 |     def _check_closed(self):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:99:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   99 |     def _check_closed(self):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/process.py:94:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   94 |                      ':'.join(str(i) for i in self._identity)
... (4046 more lines)
```

Exit code: 1
Elapsed: 9.90s
