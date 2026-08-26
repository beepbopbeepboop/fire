# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26, wtOpencode_canalyzer2 — BOTH prior error groups
## resolved; the `log_match` mangled-suffix mismatch FIXED in shared source;
## remaining errors are the documented `_iter_source` struct-state-machine family)

Fresh bounded build first reproduced the 2026-08-26 entry's two error
groups, MINUS the four `_fix_filename` errors (gone as a side effect of
this session's global-homonym fix in c_analyzer/info.py's doc — same
shared-dict instability family). That left exactly ONE error:
`_global.py:72: implicit declaration of function
'__common_log_match_c52cbf'; did you mean '__common_log_match_7a6366'?`.

Root-caused and FIXED this session (commit `b00c157`, shared source):
a cross-module free-function OVERLOAD-SUFFIX split. Hash-confirmed both
sides: the definition (`c_parser/parser/_common.py`'s `log_match(group,
m, depth_before=None, depth_after=None)`, all params unannotated) was
emitted as `(int64_t, int64_t, int64_t, int64_t)` → `_7a6366`, while the
three importers (`_global.py`, `_func_body.py`, `_compound_decl_body.py`)
hashed `(char *, int64_t, int64_t, int64_t)` → `_c52cbf`. Mechanism: each
gen's `_inferred_param_types` is PER-INSTANCE, so the importers' own
call-site literal evidence (every `_global.py` site passes a string
literal as `group`) froze `group` to `char *` in THEIR inference state,
while the definer — which has no call sites of its own — froze int64_t.
The BUG-2026-024 snapshot faithfully recorded what the IMPORTER's own
resolver said at import time, which is exactly why it could disagree with
the definer's committed signature. Fix: `_local_def_pts` now records each
defining unit's resolved signature into a whole-program-shared
`_home_def_param_types` store (shared into temp_gens like the other
cross-module dicts), and `_imported_def_pts` consults that
definition-side truth FIRST for the resolved home qualifier (prior tiers
remain as fallback). Both halves of one mangled symbol now always agree.

Full mandatory gate after the change: `test_gimple.py` 256/256,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with **0 skip lines**; zipfile/_path's
end-to-end build re-verified still exit 0.

With the suffix mismatch fixed, the build ADVANCES into the coroutine
unit and now fails on the NEXT layer — exactly the `_iter_source`
struct-state-machine family this doc's 2026-08-09 entry already root-
caused (unannotated generator params/locals/fields defaulting to
int64_t; cross-module struct-typed yield values; MojoList* field method
calls emitted with `.` instead of `->`; SourceInfo ctor arity):

```
__init___gen.cpp:160: ISO C++ forbids comparison between pointer and integer
__init___gen.cpp:161: request for member 'pop' in 'filestack', which is of
                      pointer type 'MojoList*' (maybe you meant '->' ?)
__init___gen.cpp:168: too few arguments to function
                      'void __info_SourceInfo___init__(SourceInfo*, int64_t, int64_t)'
...
```

16 g++ errors, all in `_mojogen__iter_source_impl`/`_mojogen_parse_impl`.
This is feature-sized generator-body type-inference work on shared
machinery (adjacent to the explicitly out-of-scope unannotated-init-param
family), not attempted. Doc stays open on that layer.

## Status (re-verified 2026-08-26 — blocker has SHIFTED past the 2026-08-25 pm eligibility refusals; new failure mode)

Fresh repro against this session's tree (`fix/rest-remainder18`): the
build no longer aborts at the `_parse`/`parse` coroutine-eligibility
refusals the 2026-08-25 pm entry documents — it now gets past that gate
entirely and reaches the ordinary compiled-C/g++ stage, where it fails
with two independent error groups:

1. The SAME `c_parser/info.py` `_fix_filename` caller/callee
   signature-race family already root-caused in
   `bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md` (identical
   `:179:38/:179:43/:247:38/:247:43` "passing argument N ... makes
   pointer from integer" errors against `__info__fix_filename_5c8044`)
   — same shared root cause, same out-of-scope conclusion (would need a
   forward-declaration-only signature-resolution prepass).
2. A NEW, distinct error not previously seen on this file:
   ```
   c_parser/parser/_global.py:72:3: error: implicit declaration of
   function '__common_log_match_c52cbf'; did you mean
   '__common_log_match_7a6366'? [-Wimplicit-function-declaration]
   ```
   `log_match` (`c_parser/parser/_common.py`, `def log_match(group, m,
   depth_before=None, depth_after=None)`) is called from several sibling
   modules (`_global.py`, `_func_body.py`, `_compound_decl_body.py`) with
   varying argument counts (2, 3, or 4 positional args, including at
   least one call passing `m=None` literally) — different call sites
   plausibly infer/commit different candidate signatures for the same
   cross-module free function, and only ONE mangled-suffix definition
   ends up actually emitted, leaving other call sites referencing a
   suffix that was never defined. This has the same shape as the
   info.py signature-race family above (a caller committing to a
   signature that doesn't match what the callee's OWN later inference
   settles on) but for the mangled SYMBOL NAME itself rather than just
   argument coercion — plausibly the same underlying two-pass-model gap,
   not independently root-caused further given the scope/time budget of
   this pass. Not attempted — same class of "forward-declaration-
   ordering" fix the info.py doc already assessed as out of scope for a
   narrow per-doc pass. Doc kept open; blocker documented as shifted.

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro: identical three-function refusal set with identical
per-function reasons to the 2026-08-25 entry below — `_iter_source`
(unresolved `SourceInfo(...)` cross-module struct constructor in a
coroutine body), `_parse` (`**srckwargs` spread forwarded to a known
GENERATOR callee), `parse` (moot-ordering consumption of `_parse`).
None of this round's newly-landed shared fixes (opaque-handle write
mirror, cpp string escaping, WithStmt generator driving,
zip_longest lowering) touch these shapes; kwargs-forward-to-generator
remains the same documented gap (generator construction needs the
_start API, and per-gap-slot runtime dict resolution against a
generator's start signature plus holding the handle is feature-sized).
No code change; doc re-verified. Still open.

## Status (updated 2026-08-25, branch fix/opencode-pkgutil — shared consumption-ordering fix landed; this file's blockers are all separate and unchanged)

The shared "generator-consumption ordering" machinery (this doc's
`parse` refusal below is an instance of it) is now FIXED in shared
source (commit `9ea2749` on fix/opencode-pkgutil): gen_module's
generator retry loop runs to a fixed point instead of a hard-coded 3
passes, coroutine-body consumption paths pad omitted trailing args from
the consumed generator's registered param defaults, the direct
generator-call path's silent non-zero-offset default mispad is fixed,
and refusal reasons are latest-wins (the stale pass-1 "defined LATER"
text no longer masks a function's real final blocker). Forward
consumption of an ELIGIBLE later-defined generator now works at any
chain depth — verified end-to-end with compiled-path runtime output
(new tests in test_gimple.py + test_gimple_generator_runner.py; gates
253/253, 76/76, selfhost clean, stdlib dylib 0 skips).

Re-ran post-fix: same three-function refusal set, each blocked on its
own separately-classified gap, NOT ordering:

- `_iter_source`: `SourceInfo(...)` — a cross-module struct constructor
  call has no coroutine-body lowering (unresolved callee; same
  struct-typed state-machine family the 2026-08-23 entry describes).
- `_parse`: `source = _iter_source(srclines, **srckwargs)` — `**`-
  spread to a known GENERATOR callee (separate documented gap), hit
  before its consumption of the never-eligible `_iter_source`.
- `parse`: refuses consuming `_parse(...)` — now MOOT-ordering: an
  eligible later-defined callee resolves automatically post-fix;
  `_parse` never becomes eligible. Additionally the 2026-08-09 analysis
  still applies once these gates pass: `parse` itself yields a
  cross-module struct (`ParsedItem.from_raw(result)`).

All shapes remain within tracked coroutine-codegen project scope; doc
kept open.

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
