# COMPILE_FAIL: Tools/clinic/libclinic/utils.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_alloc_NullType':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |     def get_value(
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |     def __repr__(self) -> str:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 | unknown: Final = Sentinels.unknown
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |     def __repr__(self) -> str:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:104:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:113:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function 'write_file_abb124':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:251:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:247:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:245:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:232:10: warning: unused variable '_t32' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:226:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:204:10: warning: unused variable '_t7' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:198:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function 'compute_checksum_0335d0':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:49:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   49 |     return re.compile(pattern)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:41:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   41 | ) -> re.Pattern[str]:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:39:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   39 | def create_regex(
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:38:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   38 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py: In function 'create_regex_b50b1b':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:78:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:57:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   57 |     e.g. after evaluating "string {a}, {b}, {c}, {a}"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/utils.py:50:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
... (120 more lines)
```

Exit code: 1
Elapsed: 15.17s
