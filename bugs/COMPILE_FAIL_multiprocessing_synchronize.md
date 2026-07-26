# COMPILE_FAIL: Lib/multiprocessing/synchronize.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:133:11: warning: unused variable '_tag' [-Wunused-variable]
  133 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:138:11: warning: unused variable '_tag' [-Wunused-variable]
  138 |         '''Returns current value of Semaphore.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:143:11: warning: unused variable '_tag' [-Wunused-variable]
  143 |         return self._semlock._get_value()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:158:11: warning: unused variable '_tag' [-Wunused-variable]
  158 |     def __init__(self, value=1, *, ctx):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:167:13: warning: unused variable '_tag' [-Wunused-variable]
  167 |                (self.__class__.__name__, value, self._semlock.maxvalue)
      |             ^  ~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function 'SemLock___init____after_fork':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:371:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  371 |         set_status = 'set' if self.is_set() else 'unset'
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:369:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  369 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:368:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  368 |             return False
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:367:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  367 |                 return True
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:366:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  366 |                 self._flag.release()
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py: In function 'SemLock___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:83:1: warning: label 'bb_22' defined but not used [-Wunused-label]
   83 |     @staticmethod
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:86:1: warning: label 'bb_21' defined but not used [-Wunused-label]
   86 |         sem_unlink(name)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:75:1: warning: label 'bb_20' defined but not used [-Wunused-label]
   75 |             # We only get here if we are on Unix with forking
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/synchronize.py:80:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   80 |             util.Finalize(self, SemLock._cleanup, (self._semlock.name,),
      | ^    
... (2723 more lines)
```

Exit code: 1
Elapsed: 9.72s
