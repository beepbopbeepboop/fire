# COMPILE_FAIL: Tools/clinic/libclinic/function.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:145:11: warning: unused variable '_tag' [-Wunused-variable]
  145 |             l: list[Parameter] = []
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:150:11: warning: unused variable '_tag' [-Wunused-variable]
  150 |                 l.append(p)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:155:11: warning: unused variable '_tag' [-Wunused-variable]
  155 |         if self.kind.new_or_init:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:170:11: warning: unused variable '_tag' [-Wunused-variable]
  170 |     def __repr__(self) -> str:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:179:13: warning: unused variable '_tag' [-Wunused-variable]
  179 |         return f
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function 'Module___post_init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:325:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:323:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:322:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:321:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:320:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:319:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:318:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:317:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:316:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function 'Module___repr__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:54:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   54 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py: In function 'Class___post_init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:48:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   48 |         self.classes: ClassDict = {}
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 |         self.classes: ClassDict = {}
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:48:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   48 |         self.classes: ClassDict = {}
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:51:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   51 |     def __repr__(self) -> str:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/function.py:49:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   49 |         self.functions: list[Function] = []
... (412 more lines)
```

Exit code: 1
Elapsed: 14.25s
