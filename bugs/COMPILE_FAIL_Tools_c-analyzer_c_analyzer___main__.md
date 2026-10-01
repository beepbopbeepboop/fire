# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26 — loop-as-expression codegen landed; ADVANCED: `fmt_summary`'s `list(...)` blocker is FULLY GONE, refused-generator count 2 -> 1)

Implemented real loop-as-expression codegen in the coroutine-body C++
emitter this session (`gimple_cpp_core.py`'s new
`_cpp_build_container_from_iterable`/`_cpp_rename_ident`; see
`bugs/CODEGEN_generator_function_Lib_codecs.md`'s entry of the same date
for the implementation writeup, and `bugs/COMPILE_FAIL_Tools_c-analyzer_
c_analyzer___init__.md`'s entry for the sibling repro this exact gap was
root-caused against).

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` (strict)
repro, A/B'd via `git stash`: the refused-generator list shrank from
`fmt_full, fmt_summary` to **just `fmt_full`** — `fmt_summary`'s
`list(...)` refusal (this doc's 2026-08-25 entry: "the coroutine-body
expression emitter's `Comprehension` case is a hard-coded empty-list
stub ... `list(x)`/`set(x)` ... have no equivalent lowering") is
completely gone.

Relaxed-mode `.cpp` (A/B'd the same way): `fmt_summary` now compiles
much further into its own body — reaches the nested-generator-delegation
shape (`def section(name): ...; yield from render()`) this doc's
2026-08-25-pm entry already predicted would be the NEXT blocker if
`list()` were fixed ("closure compilation + cross-generator
consumption"). New errors: `_mojogen_section_start("types")` etc. —
4 call sites passing a STRING LITERAL where the generated `section(...)`
coroutine-start symbol's inferred parameter type is `int64_t` (the
nested `def`'s own parameter type inference doesn't see the string
literal call-site evidence) — a real, different, separately-structural
gap (nested-closure-as-generator parameter typing), not attempted here.
`fmt_full` is unaffected — its own blocker (`sorted(analysis, key=...)`
where `analysis` is dict-shaped, not proven list-typed) is a pre-existing,
separately-documented `sorted(key=)` limitation, not a `list()`/`set()`/
comprehension shape.

**Net effect**: `fmt_summary`'s specific blocker this doc tracked is
fully resolved; the file as a whole still does not build (`fmt_full`
unaffected, and `fmt_summary` now blocked by the separate nested-closure
gap this doc's own analysis already anticipated). Quality gate:
`test_gimple.py` 264/264, `test_module_cache.py` 76/76, `make
check-selfhost` clean, from-scratch stdlib dylib rebuild 0 skip lines.
Doc stays open.

## Status (re-verified 2026-08-26)

Fresh repro against this session's tree (`fix/rest-remainder18`) reproduces
the identical two-function refusal, byte-for-byte the same as the
2026-08-25 pm entry below (`fmt_full`: `sorted(..., key=...)` list-typed-
iterable-only limitation; `fmt_summary`: unresolved `list(...)` — same
loop-as-expression coroutine-emitter gap tracked in the `c_analyzer/
__init__.py` doc). Same shared root cause as doc #1 in this pass; same
conclusion — large speculative feature work, not attempted. No code
change; doc re-verified only.

Re-verified again 2026-08-26, wtOpencode_canalyzer2 (fresh-cut worktree):
identical two-shape refusal set verbatim via isolated
compile_to_gimple_with_cpp(do_imports=False); unchanged conclusions.

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro: identical refusal set to the entry below — `fmt_full`:
`sorted(..., key=...) is only supported for a list-typed iterable`;
`fmt_summary`: unresolved `list(...)` — byte-for-byte the same reasons.
Re-examined this round: even a `list()`/`sorted(key=)` widening of the
coroutine emitter would not flip this file, because BOTH functions'
bodies continue into shapes that are separately structural —
`fmt_summary` defines a nested generator `def section(name)` capturing
`items` and does `yield from render()` (closure compilation +
cross-generator consumption), and `fmt_raw`/`fmt_brief` iterate
`analysis` yielding `item.render(...)` delegations on untyped elements
(the original generator-as-FORMS-dict-value gap below then still waits
behind those). No code change; doc re-verified. Still open.

## Status (re-verified 2026-08-25)

Re-ran fresh against `fix/rest-remainder9` (off master `3d2c6c2`, includes
all fixes through the generator-consumption-ordering round). Blocker has
shifted again — no longer `fmt_full` alone:

```
Error building: cannot compile module: function(s) fmt_full, fmt_summary
(generator function(s), contain a `yield`/`yield from`) ...
Unsupported shape(s): fmt_full: sorted(..., key=...) is only supported for
a list-typed iterable in a compiled generator/coroutine body; fmt_summary:
a call to unresolved callee 'list(...)' is not supported in a compiled
generator/coroutine body (...).
```

`fmt_summary`'s `list(...)` call is THE SAME root-level structural gap
root-caused for `bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md`
today: the coroutine-body expression emitter's `Comprehension` case is a
hard-coded empty-list stub with no real loop-as-expression codegen, so
`list(x)`/`set(x)` (which the ordinary call path desugars into a
comprehension) have no equivalent lowering inside a generator/coroutine
body. `fmt_full`'s `sorted(analysis, key=lambda v: v.key)` is a
pre-existing, separately-documented limitation (list-typed-iterable-only
`sorted(..., key=...)` support) — `analysis` here is dict-shaped at the
real call site, not proven list-typed, so it correctly refuses rather than
mis-lowering.

Both are genuine instances of the already-tracked structural gaps (loop-
as-expression codegen missing from the coroutine emitter; `sorted(key=)`
needing static list-shape proof) — not attempted, per this round's
instructions on large speculative feature work. The underlying
"generator function referenced as a bare value in FORMATS dict" gap this
doc originally centered on is STILL not reached (eligibility refusal fires
first, same as the 2026-08-23 note below observed) — its status is
unchanged and unconfirmed either way. No code change; doc re-triaged.

## Status (updated 2026-08-23 — the generator-as-value blocker is no longer FIRST; a new, different refusal surfaces)

Re-ran against current master tip (`626f3f0`). The build no longer fails
on the four `'fmt_*' undeclared here` GCC errors documented below — the
compile now aborts EARLIER, in the generator-eligibility pre-pass, on a
different function entirely:

```
[gimple_codegen] generator 'fmt_full' not eligible for C++ coroutine
path, falling back to honest refusal: sorted(..., key=...) is only
supported for a list-typed iterable in a compiled generator/coroutine
body
Error building: cannot compile module: function(s) fmt_full (generator
function(s), contain a `yield`/`yield from`) — ...
```

`fmt_full` (line ~245 of the real file) does `items = sorted(analysis,
key=lambda v: v.key)` where `analysis` is an unannotated parameter the
coroutine-body model can't prove is a list (it's dict-shaped at the real
call sites), and the body emitter's `sorted()` support only fires for a
list-typed iterable. The file also has `sorted(items, key=sortkey)`
(line 110) and bare `sorted(analysis)` (line 204) in sibling generators.

IMPORTANT caveat, since eligibility runs before any C emission: this
does NOT prove the old "generator function referenced as a bare value"
gap below is fixed — only that it is no longer the first failure
reached. It may well resurface once `fmt_full` gets past its own gate.
Either way the file still doesn't build; both candidate blockers live in
the separately-maintained coroutine-body lowering (tracked project,
tasks #95-135). Not attempted; doc re-triaged with fresh evidence.

## Status (updated 2026-08-09)

Re-verified against current master (fast-forwarded to `bf1ead2`, after
several sibling `Tools/c-analyzer/` bugs and the related
`_write_atomic.__code__` bug (see
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md`) got fixed this
session). `python3 fire.py build` on this file still fails with the
EXACT SAME four errors as the 2026-08-07 note below, character for
character (`'fmt_brief_0c85c9' undeclared here (not in a function)`,
etc.) — none of the intervening fixes touched this "generator function
referenced as a bare value" gap. That `importlib/_bootstrap_external.py`
doc's own 2026-08-09 update independently confirms the same conclusion:
its superficially-similar `_write_atomic.__code__` case had an
unrelated root cause (a `_lower_MemberExpr` heuristic misfiring on a
dunder attribute) and has now been fixed there, while explicitly
reaffirming this file's case is the separate, still out-of-scope
generator-as-value gap. Confirmed still structural (part of the
already-tracked compiled-generator/async-codegen project, tasks
#95-135); not attempted. No code change — doc re-verified only.

## Original status (updated 2026-08-07)

Investigated further: `fmt_raw`/`fmt_brief`/`fmt_summary`/`fmt_full`
(referenced below as VALUES in the `FORMATS` dict) are all GENERATOR
functions (`yield`/`yield from` in their bodies) — this is almost
certainly an instance of the already-tracked, explicitly out-of-scope
compiled-generator/async-codegen project (tasks #95-135)'s "a generator
function used as a bare value" gap, NOT the same root cause as the
`_write_atomic`-shaped case it was originally paired with in
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (confirmed via a
direct repro: an ordinary, non-generator top-level function used as a
module-level dict value compiles clean through this codegen's existing
`_lower_IdentExpr` "function name used as a value" mechanism — no bug
there). See that doc's 2026-08-07 follow-up for the full correction.
Not fixed here; out of scope per this session's generator/async-codegen
boundary.

## Original status (2026-08-06)

Re-ran; current error:

```
error: 'fmt_brief_0c85c9' undeclared here (not in a function); did you mean '_funcptr_fmt_brief_0c85c9'?
error: 'fmt_full_0c85c9' undeclared here (not in a function)
error: 'fmt_raw_79c856' undeclared here (not in a function)
error: 'fmt_summary_0c85c9' undeclared here (not in a function); did you mean 'fmt_summary_section'?
```

Root-caused: `def fmt_raw/fmt_brief/fmt_summary/fmt_full(analysis):`
are ordinary top-level functions, then referenced as VALUES (not
called) in a module-level dispatch dict: `FORMATS = {'raw': fmt_raw,
'brief': fmt_brief, 'summary': fmt_summary, 'full': fmt_full}`. This is
a confirmed SECOND, independent real-world instance of the already-
documented "`_write_atomic.__code__` at module scope" gap in
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (added there) —
GCC's own suggested fix (`did you mean '_funcptr_fmt_brief_0c85c9'`)
names the exact already-generated-but-unreferenced static function
pointer this call site should use instead of the bare unmangled name.
Not fixed here — see that doc.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     return items, render
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:127:11: warning: unused variable '_tag' [-Wunused-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 |                                 action='append_const', const=check)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:151:13: warning: unused variable '_tag' [-Wunused-variable]
  151 |         pass
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_render_table_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:392:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  392 |     if track_progress:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:388:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  388 |         raise ValueError(f'unsupported fmt {fmt!r}')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:387:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  387 |     except KeyError:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:384:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  384 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:383:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  383 |     verbosity = verbosity if verbosity is not None else 3
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:382:10: warning: variable 'div' set but not used [-Wunused-but-set-variable]
  382 |                 ):
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:380:10: warning: variable 'header' set but not used [-Wunused-but-set-variable]
  380 |                 formats=FORMATS,
      |          ^     
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_alloc_build_section_render_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |         info = TABLE_SECTIONS[info]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function 'build_section_render':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:129:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  129 |     default = False
... (841 more lines)
```

Exit code: 1
Elapsed: 14.16s
