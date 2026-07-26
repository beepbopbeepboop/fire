# COMPILE_FAIL: Tools/scripts/var_access_benchmark.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function '_alloc_A':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:56:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   56 |         v_global; v_global; v_global; v_global; v_global
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'A_m':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:361:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'B___init__':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:21:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   21 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:19:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   19 |     def __init__(self, x):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'C___init__':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   27 |     v_local = 1
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:25:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   25 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'read_local_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:29:11: warning: variable 'v_local' set but not used [-Wunused-but-set-variable]
   29 |         v_local;    v_local;    v_local;    v_local;    v_local
      |           ^~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function '_alloc_make_nonlocal_reader_inner_env':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |     def inner(trials=trials):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'make_nonlocal_reader_inner':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:47:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   47 | read_nonlocal = make_nonlocal_reader()
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:45:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   45 |     return inner
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'read_classvar_from_instance_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:78:7: error: '_t5' undeclared (first use in this function); did you mean '_t4'?
   78 |     for t in trials:
      |       ^~~
      |       _t4
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:78:7: note: each undeclared identifier is reported only once for each function it appears in
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:79:7: error: 'a' undeclared (first use in this function)
   79 |         a.x;    a.x;    a.x;    a.x;    a.x
      |       ^
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'read_namedtuple_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py:101:11: warning: variable 'a' set but not used [-Wunused-but-set-variable]
  101 | def read_namedtuple(trials=trials, D=namedtuple('D', ['x'])):
      |           ^
/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py: In function 'write_local_0c85c9':
... (87 more lines)
```

Exit code: 1
Elapsed: 13.83s
