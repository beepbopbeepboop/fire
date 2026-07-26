# COMPILE_FAIL: Lib/multiprocessing/popen_spawn_win32.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |         else:
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         with open(wfd, 'wb', closefd=True) as to_child:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |                     None, None, False, 0, env, None,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |             # send information to child
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:102:13: warning: unused variable '_tag' [-Wunused-variable]
  102 |         assert self is get_spawning_popen()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_path_eq_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:193:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:189:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function '_close_handles':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:38:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   38 | #
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:37:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   37 | # whose constructor takes a process object as its argument.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py: In function 'Popen___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:109:1: warning: label 'bb_15' defined but not used [-Wunused-label]
  109 |         if timeout is None:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:102:1: warning: label 'bb_17' defined but not used [-Wunused-label]
  102 |         assert self is get_spawning_popen()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:99:1: warning: label 'bb_16' defined but not used [-Wunused-label]
   99 |                 set_spawning_popen(None)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:103:1: warning: label 'bb_13' defined but not used [-Wunused-label]
  103 |         return reduction.duplicate(handle, self.sentinel)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:106:1: warning: label 'bb_14' defined but not used [-Wunused-label]
  106 |         if self.returncode is not None:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_win32.py:86:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   86 |             self.pid = pid
      | ^    
... (713 more lines)
```

Exit code: 1
Elapsed: 9.84s
