# COMPILE_FAIL: Tools/build/umarshal.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error:

```
error: 'MojoList' has no member named 'co_argcount'
error: 'MojoList' has no member named 'co_posonlyargcount'
... (one per Code field)
```

at `Reader._r_object`'s `Type.CODE` branch:
```python
elif type == Type.CODE:
    retval = R_REF(Code())
    retval.co_argcount = self.r_long()
    ...
```

Root-caused (partially): `_r_object` is a large `if/elif` chain over a
type tag byte, reusing the SAME local variable `retval` to hold a
completely different real type per branch (`int`, `str`, `list`, `set`,
`frozenset`, `Code`, ...). This codegen has no real union/variant local
type — it must pick ONE declared C type for `retval` across the WHOLE
function, and confirmed via the generated `.ci` that `R_REF` itself
(a locally-nested closure: `def R_REF(obj: Any) -> Any: ... return
obj`) is correctly boxed generic (`int64_t Reader__r_object_R_REF
(Reader__r_object_R_REF_env *, int64_t)` — takes and returns a boxed
value, not the bug). The bug is downstream: whatever unifies `retval`'s
declared type across this function's many branches picks `MojoList *`
(plausibly because an earlier/other branch assigns a genuine list/
set-shaped value to the same `retval` name, and the unification logic
joins to that rather than treating each branch as needing per-use
narrowing), losing the `Code *` identity by the time the `Type.CODE`
branch's own `retval.co_argcount = ...` field writes run.

Not fully traced to the exact unification code site (this is LOCAL
variable type inference across if/elif branches sharing one name — not
one of this session's three explicitly-flagged highest-risk categories,
but clearly adjacent/related machinery). Not fixed here given the time
this session had left; a real fix likely needs per-branch local
retyping (a fresh C variable per branch instead of one shared `retval`
declaration) rather than a narrow patch.

`bugs/COMPILE_FAIL_Tools_build_deepfreeze.md` shares this exact root
cause (transitively imports this file).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Code':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:105:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  105 |     def r_short(self) -> int:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Reader':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:119:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  119 |         return x
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code___init__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:52:13: error: 'Code' has no member named '__dict__'
   52 |         self.__dict__.update(kwds)
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:347:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:345:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:344:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code___repr__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:55:13: error: 'Code' has no member named '__dict__'
   55 |         return f"Code(**{self.__dict__})"
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |                 varnames.append(name)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code_get_localsplus_names':
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
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:67:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   67 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:66:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   66 |         return tuple(varnames)
... (1836 more lines)
```

Exit code: 1
Elapsed: 13.15s
