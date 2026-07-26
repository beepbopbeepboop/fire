# COMPILE_FAIL: Lib/multiprocessing/pool.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:171:9: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
  171 |             self.notifier.put(None)
      |         ^   
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/_stdlib.h:70,
                 from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdlib.h:58,
                 from pool.ci:5:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/sys/wait.h:246:9: note: previous declaration of 'wait' with type 'pid_t(int *)' {aka 'int(int *)'}
  246 | pid_t   wait(int *) __DARWIN_ALIAS_C(wait);
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_ApplyResult':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:330:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  330 |             pool.append(w)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_ExceptionWithTraceback':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:344:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  344 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_IMapIterator':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:358:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  358 |         Pool must be running.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_IMapUnorderedIterator':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:372:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  372 |         be iterables as well and will be unpacked as arguments. Hence
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_MapResult':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:386:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  386 |         '''Provides a generator of tasks for imap and imap_unordered with
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_MaybeEncodingError':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:400:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  400 |         self._check_running()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc_RemoteTraceback':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:414:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  414 |             task_batches = Pool._get_tasks(func, iterable, chunksize)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function '_alloc__PoolCache':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:428:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  428 |         '''
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:983:34: error: 'Pool_close' undeclared here (not in a function)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:1019:40: error: 'ThreadPool_close' undeclared here (not in a function); did you mean 'ThreadPool_join'?
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py: In function 'RemoteTraceback___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 |     def __init__(self, tb):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/pool.py:56:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
... (9656 more lines)
```

Exit code: 1
Elapsed: 10.24s
