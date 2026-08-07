# COMPILE_FAIL: Lib/ctypes/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py`

## Status (updated 2026-08-06)

Multiple distinct issues found across two investigation passes (original
auto-scan, then a manual pass this session). None fixed yet.

### 1. `type(self).__name__` used in `%`-formatting — `mojo_type` int/pointer mismatch

Original auto-generated scan (error text preserved below). Not
re-investigated this session — still open.

```
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:166:21: error: passing argument 1 of 'mojo_type' makes integer from pointer without a cast [-Wint-conversion]
  166 |             return "%s(<NULL>)" % type(self).__name__
      |                     ^~~~
      |                     |
      |                     py_object *
In file included from __init__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:317:19: note: expected 'int' but argument is of type 'py_object *'
  317 | int mojo_type(int obj);
      |               ~~~~^~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:166:15: error: invalid operands to binary % (have 'char *' and 'char *')
```

`py_object.__repr__` does `"%s(<NULL>)" % type(self).__name__` where
`self` is a `py_object *`. `mojo_type()`'s C signature takes `int obj`
(presumably a boxed/tagged representation) but is being called with the
raw `py_object *` pointer directly — a call-site coercion gap for
`type(x)` when `x` is a struct-typed local, not a generic/boxed value.
Not yet root-caused further; likely related to `type()` builtin lowering
choosing the wrong argument-passing convention for concrete struct
pointer types vs boxed/dynamic values.

### 2. `__ctype_le__`/`__ctype_be__` — dynamic-attribute hard bug instance

```python
def __ctype_le__(self):
    ...
    self.__ctype_le__ = ...
```
(pattern: a method assigns a NEW attribute onto `self` that wasn't part
of the struct's original field set). This is an instance of
bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md — tracked there,
not a standalone fix.

### 3. CFUNCTYPE / `(*args, **kwargs)`-signature functions called with literal (non-spread) arguments never get variadic packing

```python
def CFUNCTYPE(restype, *argtypes, **kw):
    ...
memmove = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_size_t)(_memmove_addr)
```

```
error: too many arguments to function 'CFUNCTYPE_07077a'; expected 3, have 4
```

Root-caused 2026-08-06, minimally reproduced standalone (`make_thing
(restype, *argtypes, **kw)` called as `make_thing(1, 2, 3, 4)` fails
identically). Full technical root cause, generated-C evidence, and a
concrete fix-direction plan are written up as a new hard bug:
**bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md**.

Summary: `_signature_ctypes` (gimple_codegen.py:19985) deliberately types
a function's `*args` parameter as a concrete `MojoList *` (not the `...`
packing sentinel) whenever the function ALSO has `**kwargs`, on the
assumption every such function is only ever called via spread-forwarding
(`f(*a, **k)`). This is correct for that idiom but wrong whenever a
`(*args, **kwargs)`-declared function is instead called with ordinary
literal positional arguments, as `CFUNCTYPE` is here. Not fixed — flagged
as architecturally risky given this exact call-lowering area caused two
broad compile_stdlib.py regressions elsewhere this session (see
bugs/COMPILE_FAIL_collections___init__.md's `_tuplegetter` section); see
the hard-bug doc for the full risk analysis and recommended fix shape.

Not yet checked whether the original auto-scan's 1043-line truncated
error log contains further, later errors beyond what's captured above —
worth re-running a fresh `mojo.py build` pass once issues #1-3 are fixed,
to see what (if anything) remains.
