# COMPILE_FAIL: Tools/peg_generator/pegen/sccutils.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:27:11: warning: unused variable '_tag' [-Wunused-variable]
   27 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:32:11: warning: unused variable '_tag' [-Wunused-variable]
   32 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 |                 while index[w] < boundaries[-1]:
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 | def topsort(
      |           ^~  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:61:13: warning: unused variable '_tag' [-Wunused-variable]
   61 |             self-dependencies are removed and entries representing
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function '_alloc_strongly_connected_components_dfs_env':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:140:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py: In function 'strongly_connected_components_dfs':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 |         if v not in index:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:46:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   46 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:187:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:185:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:184:7: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:183:13: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:182:14: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:181:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:180:14: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:179:14: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:178:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:177:13: warning: variable 'scc' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:176:14: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:175:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:174:14: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:173:14: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:172:13: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:171:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:170:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:169:7: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:168:14: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/sccutils.py:167:9: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
... (172 more lines)
```

Exit code: 1
Elapsed: 14.02s
