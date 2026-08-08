# COMPILE_FAIL: Lib/zipfile/_path/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-07)

**The property-chaining bug (`self.filename.parent` resolving to the
bound-method value instead of the getter's result) is FIXED.** The
`'MojoBoundMethod' has no member named 'parent'` error is gone. This
file still does NOT fully compile — but the remaining failure
(`request for member 'rstrip' in 'path', which is of non-class type
'int64_t'` in the C++ generator-codegen output, `__init___gen.cpp`) is
a genuinely SEPARATE, pre-existing bug, confirmed present byte-for-byte
identically both before and after this fix (via `git stash`) — not
something this session investigated further; out of scope for this
pass. See below for the property-chaining root cause and fix.

### Root cause and fix (2026-08-07)

Two independent gaps in `gimple_codegen.py`, both needed for the fix
to be complete and correct:

1. **Value lowering** (`_lower_MemberExpr`'s general object-lowering
   path, `else: ot, ov = self.lower_expr(node.obj)`): when `node.obj`
   (here, `self.filename`) lowers to a `MojoBoundMethod *` — the
   deferred, uncalled representation ANY bare `self.foo` (no `()`)
   gets, whether `foo` is a `@property` or an ordinary method; this
   codegen has no separate representation for the two — chaining a
   member access directly off it must auto-invoke the getter/method
   FIRST, then look up the member on the RESULT. This mirrors a fix
   already made for the analogous subscript case (`self.prop[key]`,
   `_lower_subscript`) but had never been applied to plain member
   access. Fixed by adding the identical `if ot == 'MojoBoundMethod
   *': ...auto-invoke via mojo_bound_method_call_0...` check right
   after the object is lowered.

2. **Static return-type inference** (`_quick_type`'s `MemberExpr`
   case, used by `_infer_return_type`/`_collect_return_types` to guess
   a function's own C return type from its `return` statements, a
   completely separate pre-pass from the value-lowering above): it
   only ever consulted `struct_field_types` (real instance FIELDS),
   never recognizing that `node.member` might be a bound METHOD
   returning a pointer. For `return self.filename.parent`, this made
   `_quick_type(self.filename)` return `'int64_t'` (the default for
   "not a known field"), so the OUTER `_quick_type(self.filename.
   parent)` also defaulted to `'int64_t'` — even after fixing gap 1
   above, the VALUE was computed correctly (a real `char *`/struct-
   pointer field read), but the enclosing function's C SIGNATURE still
   declared `int64_t` as its return type, silently truncating/
   reinterpreting the real pointer through a same-width integer cast —
   wrong output, not a compile error (confirmed via a minimal repro:
   printed a raw pointer address instead of the real field value).
   Fixed by teaching `_quick_type`'s `MemberExpr` case to fall back to
   the same struct-method detection `_lower_MemberExpr` itself already
   uses (`f"{struct}_{member}" in func_return_types` or `(struct,
   member) in _struct_method_signatures`) and return THAT method's
   return type instead of defaulting to `int64_t` when `node.member`
   isn't a real field.

Both gaps had to be fixed together — fixing only gap 1 leaves gap 2's
wrong-return-type bug fully intact (confirmed: a minimal isolated
repro with fix 1 alone compiled clean but printed a garbage pointer
address instead of the real string value).

### Verification

Minimal repro (`@property` returning a struct, chained field read
inside another method's `return` statement) now compiles AND RUNS
correctly, printing the real field value (previously either a hard
compile error pre-fix-1, or — with fix 1 alone — a garbage pointer-
address integer). Full 5-part mandated gate clean: `test_gimple.py`
247/247, `test_module_cache.py` 76/76, `make check-selfhost` clean,
from-scratch stdlib dylib rebuild 0 skips, `compile_stdlib.py -j8`
664/664 0 unexpected.

## Original report (2026-08-06, superseded above)

Re-ran; current error:

```
error: 'MojoBoundMethod' has no member named 'parent'
error: expected expression before ';' token
```

at:
```python
@property
def filename(self):
    return pathlib.Path(self.root.filename).joinpath(self.at)
...
    return self.filename.parent   # (a different method, chains off the property)
```

Root-caused: `filename` is a `@property`. `self.filename.parent`
resolves `self.filename` to the property's own `MojoBoundMethod *`
VALUE (the getter itself, uncalled) rather than actually invoking the
getter and using ITS result — so `.parent` is then looked up on a
`MojoBoundMethod`, which has no such member. This looks like a gap
specific to CHAINING an attribute access directly off a `@property`
read (`self.prop.attr`) as opposed to a simple `x = self.prop`
assignment (properties clearly work in general elsewhere in this
codebase's passing stdlib compiles) — not confirmed further, not
fixed. Minimal repro to try in a future session: `class C: @property
def p(self): return SomeStruct() ... def f(self): return self.p.field`.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |     def __getstate__(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |         super().__init__(*args, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:103:11: warning: unused variable '_tag' [-Wunused-variable]
  103 |     A ZipFile subclass that ensures that implied directories
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:118:11: warning: unused variable '_tag' [-Wunused-variable]
  118 |     def namelist(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:127:13: warning: unused variable '_tag' [-Wunused-variable]
  127 |         If the name represents a directory, return that name
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_parents_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:290:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  290 |     ...
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:287:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  287 |     >>> zf.filename = None
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_ancestry_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:89:11: warning: variable 'tail' set but not used [-Wunused-but-set-variable]
   89 |         self.__args = args
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:75:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   75 | def _difference(minuend, subtrahend):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:70:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:66:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   66 |     while path.rstrip(posixpath.sep):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:56:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   56 |     ['b']
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:52:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   52 |     ['/b/d', '/b']
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:46:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   46 |     Given a path with elements separated by
      |          ^~~
... (2270 more lines)
```

Exit code: 1
Elapsed: 13.28s
