# COMPILE_FAIL: Tools/ftscalingbench/ftscalingbench.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function '_alloc_Counter':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:81:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   81 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function '_alloc_MyClassMethod':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:95:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   95 |     for i in range(100 * WORK_SCALE):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function '_alloc_MyContextManager':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:109:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  109 | def pymethod():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function '_alloc_MyDataClass':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:123:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  123 |     return accu
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function '_alloc_MyObject':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:137:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  137 | class MyObject:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'object_cfunction':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:63:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   63 | def object_lookup_special():
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:62:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   62 | @register_benchmark
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'cmodule_function':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:67:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   67 |         round(i / N)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:66:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   66 |     for i in range(N):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'object_lookup_special':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:67:3: warning: statement with no effect [-Wunused-value]
   67 |         round(i / N)
      |   ^     ~~~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'MyContextManager___enter__':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:81:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   81 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'MyContextManager___exit__':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:76:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   76 | def context_manager():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py: In function 'context_manager':
/Users/mrs/net/Python-3.14.6/Tools/ftscalingbench/ftscalingbench.py:81:3: error: too few arguments to function 'MyContextManager___exit__'; expected 4, have 1
   81 | 
... (218 more lines)
```

Exit code: 1
Elapsed: 13.77s
