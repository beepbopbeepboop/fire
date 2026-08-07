# COMPILE_FAIL: Tools/build/deepfreeze.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/deepfreeze.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error is entirely in a transitively-imported sibling:

```
error: 'MojoList' has no member named 'co_argcount'
error: 'MojoList' has no member named 'co_posonlyargcount'
... (one per Code field)
```

Same root cause as `bugs/COMPILE_FAIL_Tools_build_umarshal.md`
(`deepfreeze.py` imports `umarshal.py`): `Reader._r_object`'s big
`if/elif` type-tag dispatch reuses one local variable `retval` across
branches holding structurally different real types; the `Type.CODE`
branch's `retval` loses its `Code *` identity to whatever the
unification across all branches picks (`MojoList *`). Not fixed here
— see that doc for the fuller trace and why a real fix needs per-branch
local retyping rather than a narrow patch. Nothing specific to
`deepfreeze.py` itself was found.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Code':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Reader':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 | class Reader:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code___init__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:52:13: error: 'Code' has no member named '__dict__'
   52 |         self.__dict__.update(kwds)
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  174 |         old_level = self.level
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:172:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  172 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:171:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  171 |         return obj
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code___repr__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:55:13: error: 'Code' has no member named '__dict__'
   55 |         return f"Code(**{self.__dict__})"
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |                 varnames.append(name)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code_get_localsplus_names':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:73:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   73 |     def co_cellvars(self) -> tuple[str, ...]:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:72:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   72 |     @property
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:71:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   71 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:70:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   70 |         return self.get_localsplus_names(CO_FAST_LOCAL)
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:69:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   69 |     def co_varnames(self) -> tuple[str, ...]:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:68:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   68 |     @property
... (3268 more lines)
```

Exit code: 1
Elapsed: 14.17s
