# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error (multiple identical occurrences):

```
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:289:1: error: type mismatch in binary expression
```

at `ColumnSpec._parse`'s classmethod: `*values, _ = raw` (starred-target
unpack) then `return cls(*values)` — calling the classmethod's own
`cls` (an opaque, dynamically-typed class reference, boxed `int64_t`)
with a SPREAD `*values` argument. Root-caused via the generated `.ci`:
this lowers to `mojo_fnptr_call_1(cls_as_voidptr, (int64_t)values)` —
the `MojoList *` holding the real per-element values gets cast whole
to `int64_t` and passed as a SINGLE argument, rather than actually
spreading its elements into separate call arguments. `cls(*values)`
against a dynamic/opaque callable reference doesn't perform real
argument spreading at all.

Not fixed here — this is call-argument handling for a spread call
against a DYNAMIC callable (as opposed to a statically-known
constructor/function, which this codegen handles correctly elsewhere),
one of the explicitly flagged high-risk categories (call-argument
coercion) this session treats with extra caution. Plausibly related to
(but a distinct shape from) `bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
— that doc covers a *declared* `*args`/`**kwargs` function being
called with literal positional args; this is the mirror case, a
spread *call site* against an opaque *callee*. Worth checking whether
the two share a fix location before attempting either.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 |             values = _fix_read_default(row)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     return fix_row
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 |         fix = empty
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |                fix=None,
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:95:13: warning: unused variable '_tag' [-Wunused-variable]
   95 |                 header,
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:216:59: warning: trigraph '??-' ignored, use '-trigraphs' to enable [-Wtrigraphs]
  216 |             sep = None
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:219:67: warning: trigraph '??-' ignored, use '-trigraphs' to enable [-Wtrigraphs]
  219 | 
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function 'fix_row_a64463':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:56:11: warning: variable 'val' set but not used [-Wunused-but-set-variable]
   56 |         def fix_row(row):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_alloc__normalize_fix_read_fix_row_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:57:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   57 |             values = fix(row)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py: In function '_normalize_fix_read_fix_row':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 |     if callable(fix):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:70:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   70 |     if fix is None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:69:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   69 | def _normalize_fix_write(fix, empty=''):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:68:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   68 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:67:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   67 | 
      |              ^  
... (964 more lines)
```

Exit code: 1
Elapsed: 14.26s
