# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-23 — fails EARLIER now, on `**kwargs`→generator-callee forwarding; old GCC errors no longer reached)

Re-ran against current master tip (`626f3f0`). The build now aborts in
the eligibility pre-pass before ever emitting the `__init___gen.cpp`
whose GCC errors the 2026-08-09 update below quotes — so that
diagnosis is unreachable/masked today, not refuted. The new first
refusals:

```
[gimple_codegen] generator '_parse' not eligible for C++ coroutine
path, falling back to honest refusal: a `*`/`**`-unpack call argument
is not supported in a compiled generator/coroutine body
[gimple_codegen] generator 'parse' not eligible ... : `for ... in
_parse(...)` does not consume a generator this compile has itself
already translated via the C++20-coroutine path (either it's not a
generator this codegen supports, or it's defined LATER in this module
— the consumed generator must be defined earlier)
```

Root cause for `_parse`: its body's FIRST statement is `source =
_iter_source(srclines, **srckwargs)` — a `**kwargs` spread forwarded to
a statically-known GENERATOR callee defined later in the module.
`_cpp_try_kwargs_forward_call` deliberately excludes generator callees
(no directly-callable C symbol; only the `_start`/`_resume`/`_value`
API), there is no generator-object-value representation in a coroutine
body (so even holding the result would refuse), and `_iter_source`
itself — whose SourceInfo-based state machine needs struct-typed
locals/fields the scalar body model can't represent — never becomes
eligible either. `parse` then refuses consuming `_parse` via the same
ordering constraint (`parse` also yields a cross-module struct,
`ParsedItem.from_raw(result)`, per the 2026-08-09 analysis, which still
applies once these earlier gates are passed). Same tracked
compiled-generator project scope; not attempted.

## Status (re-verified 2026-08-09): still fails, same generator/coroutine gap, confirmed precisely

Re-ran on current `master` (`python3 mojo.py build .../c_parser/parser/__init__.py`,
exit 1). Error set in the generated `__init___gen.cpp` is unchanged from
2026-08-06 (`invalid conversion from 'MojoBoundMethod*' to 'int64_t'`,
`'ParsedItem' was not declared in this scope`, `request for member
'filename' in 'fileinfo', which is of non-class type 'int64_t'`, etc.).

Confirmed precisely which generators/yields trigger it: this module has
three coroutine-lowered generator functions —
- `parse()` (line 128-129): `for result in _parse(...): yield
  ParsedItem.from_raw(result)` — yields a cross-module struct type
  (`ParsedItem`, imported via `from ..info import ParsedItem`), not a
  scalar the coroutine promise machinery can represent.
- `_parse()` (around line 161): `yield result` — the loop var's real
  type is inferred from an untyped upstream param/return and defaults
  to `int64_t`.
- `_iter_source()` (around lines 191/201/204): `yield srcinfo`, where
  `srcinfo` is a `SourceInfo` instance (`from ._info import
  SourceInfo`, also cross-module) built up via mutation of unannotated
  fields (`fileinfo`, `filestack`, `_start`, `_used`, etc.), all of
  which fall back to `int64_t`/`char*` instead of their real
  struct/list types in this codegen path.

This is the exact already-tracked gap: unannotated generator
params/locals/fields default to `int64_t` in the coroutine-promise
lowering (unlike the ordinary-function path's real type inference),
and non-scalar (here cross-module-struct-typed) yield values aren't
representable at all — so downstream member accesses on the wrongly
`int64_t`/`char*`-typed locals fail to compile. Same class as
`bugs/CODEGEN_generator_function_Lib_*.md` /
`bugs/hard/CODEGEN_generator_*.md`. No code change made — out of scope
for this pass per the project's explicit deferral of the
generator/coroutine codegen project.

## Status (updated 2026-08-06)

Re-ran; current errors are all in a generated C++ file
(`__init___gen.cpp`), e.g. `invalid conversion from 'MojoBoundMethod*'
to 'int64_t'`, `'ParsedItem' was not declared in this scope`, `request
for member 'filename' in 'fileinfo', which is of non-class type
'int64_t'`. This module defines generator functions (`yield
ParsedItem.from_raw(result)`, `yield result`, `yield srcinfo`, ...),
compiled via this codegen's separate C++20-coroutine lowering path.
Part of the separate, already-tracked compiled-generator/async-codegen
project (tasks #95-135) — the untyped generator-param/local-type and
sibling-name-resolution categories that project's scope already
covers. Not investigated further here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 |    + (stmt) continue:  at end
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 |    + (decl) param-list:  between params
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 | * ":"
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 |    + (expr) postfix (func call):  around args
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |    + (decl) func:  around body
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function 'parse_a64463':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:157:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  157 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_alloc_anonymous_names_anon_name_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:139:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  139 |         nonlocal counter
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function 'anonymous_names_anon_name':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 | # We use defaults that cover most files.  Files with bigger declarations
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:162:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  162 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:161:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  161 |         yield result
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:160:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  160 |         # XXX Handle blocks here instead of in parse_globals().
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:159:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  159 |     for result in parse_globals(source, anon_name):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:158:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  158 |     source = _iter_source(srclines, **srckwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:157:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  157 | 
... (91 more lines)
```

Exit code: 1
Elapsed: 13.31s
