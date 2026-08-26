# COMPILE_FAIL: Lib/zipfile/_path/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-25, worktree fix/rest-remainder12 — isolated generator/coroutine TU still compiles clean (unaffected by this session's 4 fixes elsewhere); a real end-to-end build now goes further before failing, but still fails, on both a new link-time gap and the previously-documented unrelated transitive-import failures)

Re-ran an isolated `compile_to_gimple_with_cpp(do_imports=False)`
check fresh, after this session's 4 coroutine-emitter fixes landed
for COMPILE_FAIL_Apple___main__.md (`mojo_c_getenv`/platform/
subprocess whitelist, zero-arg `print()`, string-repeat `*`, f-string
interpolation in `_cpp_expr`'s `StringLiteral` case): still `OK`, zero
exceptions — consistent with the 2026-08-24 entry below (this file's
own `_ancestry`/`_parents` generator TU was already clean; none of
this session's 4 fixes touch the still-unfixed `path`-param-type-
inference gap that keeps that generator's body dead code).

A real `python3 mojo.py build` (with imports, safety-bounded) now
gets further than before it fails — it reaches actual LINKING, not
just compilation — but still does not produce a binary:

```
link failed: Undefined symbols for architecture arm64:
  "_InitializedState_getinfo", referenced from:
      _CompleteDirs_getinfo in ...
  "_InitializedState_namelist", referenced from:
      _CompleteDirs_namelist in ...
  "_Path___class__", referenced from:
      _Path__next in ...
```

NOT investigated further this pass (this is a new-looking symptom —
worth a future session tracing whether `InitializedState`/`__class__`
resolve to real emitted symbols with a different mangled name, or are
genuinely unimplemented). The build then also still hits the
previously-documented unrelated transitive-import failures verbatim
(`collections`'s `Counter[...] = ...` subscript-store gap, `inspect`'s
same `OrderedDict[...] = ...` gap, PLUS a newly-surfaced third:
`glob.py`'s `self.select_exists` — a compiled GENERATOR method
referenced as a plain, uncalled value, which this codegen's
`MojoBoundMethod*` single-call scalar-return representation can't
express (a real generator's callable surface is its `<base>_start/
_resume/_value/_destroy` C++20-coroutine API, not a bound-method
value) — all three cause their respective modules to fall back to
source-interpretation, independent of this file's own code). None
attempted this pass (all in other files' scope). Doc kept open — this
file still does not build end-to-end.

## Status (updated 2026-08-24, worktree fix/rest-remainder, 2nd entry — the `'posixpath' was not declared` gap ALSO fixed; isolated coroutine TU for this file's own generators now compiles with ZERO g++ errors; still blocked overall by the pre-existing param-type-inference gap + unrelated transitive-dependency failures)

This session's `_cpp_expr` MemberExpr fix (see `bugs/CODEGEN_generator_
function_Lib_test_test_dbm.md`'s 2026-08-24 entry for the mechanism —
a module-import name read as a bare, uncalled attribute VALUE, e.g.
`path.rstrip(posixpath.sep)`'s `posixpath.sep`, previously emitted as
literal undeclared `posixpath` text) also resolves this file's own
`'posixpath' was not declared in this scope` error, noted in the
2026-08-23 entry below alongside the (separately-fixed, prior session)
`.rstrip()` gap.

Re-verified via a fresh isolated `compile_to_gimple_with_cpp(do_imports=
False)` + `g++-mp-15 -std=c++20 -fsyntax-only`: **ZERO** g++ errors for
this file's own generator translation unit (`_ancestry`/`_parents`,
both). Honest caveat, consistent with this doc's own prior analysis:
this does NOT make the file build end-to-end or behave correctly —
`path`'s parameter ctype is still the pre-existing, unfixed `int64_t`
default (the param-type-inference gap this doc already identified as
the BINDING blocker: `_ancestry(path)` has no literal call site
anywhere in the file for `_param_ctype` to learn from), so the whole
generator body is dead code either way (`path = 0; while (0) { ... }`).
A real `python3 mojo.py build` of this file also still fails from
unrelated transitive dependencies (`collections`/`inspect`'s
`Counter[...] = .../OrderedDict[...] = ...` subscript-store gap,
already documented elsewhere) — not re-run this session (no code
change to those paths), so overall build status is unchanged: still
does not build end-to-end.

Full mandatory gate: `test_gimple.py` 252/252, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
EXIT=0 with 0 skip lines.

Doc stays open.


## Status (updated 2026-08-24 — PARTIAL: one of the two stacked gaps below fixed, file still doesn't build)

This session (commit 753b199) added real `char *`-receiver dispatch for
`.strip()`/`.lstrip()`/`.rstrip()`/`.lower()`/`.upper()`/`.startswith()`/
`.endswith()` to the coroutine-body expression emitter (`_cpp_expr`,
`gimple_cpp_core.py`), routing through the same `mojo_str_*`/`string_*`
runtime helpers the ordinary (non-generator) GIMPLE path already uses —
directly motivated by this doc's own 2026-08-09 analysis ("this
codegen's generator/coroutine body expression emitter has no string-
method-call support at all"). Re-ran the repro fresh against the fixed
tree: confirmed via `MOJO_DEBUG=1` that `path.rstrip()` inside
`_ancestry` no longer falls into the raw-miscompile/opaque-stub path
via a wrong mechanism — it's still stubbed (`generator-body method call
on opaque scalar local path.rstrip()`), but that's now because `path`'s
OWN declared ctype is `int64_t` (the SEPARATE, still-unfixed param-type-
inference gap this doc's 2026-08-09 analysis already called out:
`_ancestry(path)` has no literal call-site anywhere in the file, so
`_param_ctype` never gets evidence to resolve it past its `int64_t`
default) — not because `.rstrip()` itself is unhandled. Confirmed via a
minimal isolated repro that a generator with a param whose type DOES
resolve to `char *` now compiles `.rstrip()`/`.lower()`/`.startswith()`
etc. correctly through the new dispatch. This file's actual build still
fails (fresh `python3 mojo.py build` of this file transitively pulls in
several other, unrelated, already-documented failing modules —
`collections`'s `Counter[...] = ...` subscript-store gap, `inspect`'s
`OrderedDict[...] = ...` same gap, and this file's own eventual link
failure) — the string-method fix is real forward progress but not
sufficient on its own to close this doc; the param-type-inference gap
for `_ancestry`/`_parents` remains the binding blocker. Full quality
gate clean: `test_gimple.py` 252/252, `test_module_cache.py` 76/76,
`make check-selfhost` clean, from-scratch stdlib dylib rebuild exit 0,
0 `skip <module>:` lines.

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — unchanged)

Re-ran the repro fresh; identical failure shape to the 2026-08-09
analysis below: the module-level generator `_ancestry` still fails in
the coroutine-body emitter with `request for member 'rstrip' in 'path',
which is of non-class type 'int64_t'` (now joined by `'posixpath' was
not declared in this scope`, same function). Both remain the documented
generator-body `_cpp_expr` structural gaps (no string-method dispatch,
no module-attribute-call dispatch in the coroutine emitter) plus the
param-type-inference gap (no literal call site for `_ancestry(path)`
anywhere). Not attempted this pass either — adding real method/module-
call dispatch to the coroutine body emitter is feature-sized work in
the same out-of-scope area.

## Status (updated 2026-08-09)

Re-verified against current master (`3d36ccd`) via `python3 mojo.py
build /Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py`. The
2026-08-07 property-chaining fix (below) is confirmed still in effect.
The file still does NOT compile, for the SAME remaining symptom the
2026-08-07 pass flagged but explicitly left un-investigated
("`request for member 'rstrip' in 'path'`") — now actually root-caused:

```
Generator (.cpp) compilation failed: ...
__init___gen.cpp: In function '_mojogen__ancestry_Task _mojogen__ancestry_impl(int64_t)':
__init___gen.cpp:105:17: error: request for member 'rstrip' in 'path', which is of non-class type 'int64_t' {aka 'long long int'}
  105 |     path = path.rstrip(posixpath.sep);
      |                 ^~~~~~
```

This is inside `_ancestry` — a module-level GENERATOR function (`def
_ancestry(path): ... yield path ...`, source lines 44-68) with an
unannotated `path` parameter, called elsewhere only as `_ancestry(path)`
(another unannotated parameter, in `_parents`) — never with a literal
string argument anywhere in the file, so this codegen's cross-call
scalar-contract inference (`_inferred_param_types`, the same mechanism
described in `bugs/hard/CODEGEN_unannotated_init_param_field_type_
defaults_int64.md` for constructor params) never gets any evidence to
resolve `path`'s real type, and `_param_ctype` falls back to its
`int64_t` default — this part is a general (non-generator-specific)
limitation of that inference pass, shared by the ordinary compiled path
too.

**However, confirmed via a minimal isolated repro that fixing JUST the
param-type inference would not be enough** — this codegen's generator/
coroutine body expression emitter (`_cpp_expr`, `gimple_codegen.py`
~line 23418) has **no string-method-call support at all** (no `.rstrip`/
`.split`/etc. dispatch), unlike the ordinary (non-generator) compiled
path's `_lower_call`/string-method lowering, which handles these
correctly. Repro: a free (non-generator) function with an unannotated
`path` param called `path.rstrip('/')` in a loop, invoked with a
string-literal argument elsewhere (`strip_sep("hello///")`) — the
ordinary path infers `path` as `char *` (literal call-site evidence
exists here, unlike `_ancestry`) AND compiles/links successfully. The
SAME body, turned into a generator (`yield path` added), still gets
`path` correctly inferred as `char *` by `_gen_cpp_generator_unit`
(same `_param_ctype` call, same literal-call-site evidence) — but then
fails to compile with the near-identical error `request for member
'rstrip' in 'path', which is of non-class type 'char*'`. This isolates
the two issues cleanly: `_ancestry`'s specific instance additionally
suffers the param-type-inference gap (no literal call site anywhere),
but even a correctly-`char *`-typed parameter's `.rstrip()` call fails
in a generator body — the coroutine `_cpp_expr` emitter simply has no
member-call dispatch for string methods, full stop.

**Classification: generator/coroutine-codegen structural gap** (this
session's `_cpp_expr`-is-narrower-than-the-ordinary-path theme,
already established for `LambdaExpr`-as-call-argument and `**kwargs`-
unpack-as-call-argument — see
`bugs/CODEGEN_generator_function_Lib_codecs.md`'s 2026-08-09 update for
a sibling instance in the exact same function). Not attempted here —
adding real string-method dispatch to the coroutine body emitter is
feature-sized work in this same out-of-scope area, per this session's
explicit mandate. Doc kept, root cause section updated with the precise
confirming construct (the exact generator/param/method combination)
rather than re-deriving from scratch in a future session.

## Status (updated 2026-08-07, superseded above)

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
