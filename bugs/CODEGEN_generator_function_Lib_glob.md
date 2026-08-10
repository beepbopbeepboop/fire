# CODEGEN_generator_function: Lib/glob.py

## Correction (2026-08-09, later same day): the line-175 error's root cause was misattributed

The "updated 2026-08-09" note directly below (from an earlier commit
the same day) claimed `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`'s `_global_to_module` collision was "the real root cause
of the line-175 error" and "still present and unfixed." A careful
re-derivation (not just re-matching the same misleading `glob.py:175`
GCC line number, which this doc's own earlier methodology note already
warns is unreliable for this function) found this was wrong: the
`_global_to_module` read-side misattribution for `contextlib`
(glob.py's own `_listdir`, reading `_subprocess_globals.contextlib`)
was ALREADY fixed as a side effect of `bugs/hard/CODEGEN_module_globals_
cross_contamination_via_imported_stmts.md`'s "Mechanism 3" fix (commit
`21f5f49`, landed before this doc's own "updated 2026-08-09" note was
written — the note re-matched the symptom without re-verifying the
mechanism still applied). Confirmed directly: stripping all `#line`
directives from the generated `.ci` and recompiling shows GCC's real
physical-line error is inside `_glob0_737363` (`_t8 =
_join_abb124(_t5, _t7)` — assigning `_join_abb124`'s `char *` return
into an `int64_t`-declared temp), NOT any `contextlib`/`_global_to_
module` misattribution — a distinct, unrelated return-type-inference
gap in codegen for a path-join-style helper call. Separately confirmed
`_listdir_132aaf`'s own generated code no longer reads `_subprocess_
globals.contextlib` at all (falls through to the safe "unknown
identifier" placeholder, since it correctly recognizes it does not own
that name). `bugs/hard/CODEGEN_cross_module_bare_import_name_collision.
md` has been removed as fixed (see its own former content / this
commit's message for the full evidence). glob.py itself still does not
build — same practical bottom line — but for the `_join_abb124`
return-type bug above (not yet investigated further) and the line-354
`translate()` keyword-arg-arity gap already described below, not this
one.

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (post-merge `7df52a0`). Still fails
identically to the 2026-08-07 diagnosis below — exact same two errors,
same lines:
```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/glob.py:354:9: error: too few arguments to function 'translate_584a43'; expected 4, have 1
```
Confirmed again: `MOJO_DEBUG=1` shows no "not eligible" refusal for any
of glob.py's own generators. (See the correction above — the line-175
root-cause claim in this section is superseded/wrong.)

One addition: pinned down the second error (line 354,
`translate_584a43` arity mismatch) precisely — it is NOT generator-
related either. `translate(pat, *, recursive=False, include_hidden=
False, seps=None)` (glob.py:294) is an ordinary function with 3
keyword-only parameters; its one call site, `_compile_pattern`
(glob.py:354, `translate(pat, recursive=recursive, include_hidden=True,
seps=seps)`), passes all 3 by keyword. `translate` itself contains no
`yield` — this is a plain call-codegen gap in keyword-only-argument
forwarding for an ORDINARY function call, unrelated to the coroutine
generator path this cluster of bug docs is about. Left uninvestigated
further here (out of scope for the generator-codegen cluster; would be
better tracked as its own non-generator `CODEGEN_` doc if it recurs
elsewhere — a quick grep of the other 2 bug docs in this batch,
gettext.py/imaplib.py, found no matching symptom, so not folded into a
shared doc yet).

## Status (updated 2026-08-07, re-diagnosed — previous root cause was WRONG)

**STILL FAILING**, but the 2026-08-06 note's root-cause analysis below
(a generator yield-value forward-reference type-inference bug) has been
**re-investigated and disproven**. Re-confirmed against current master:
`MOJO_DEBUG=1` still shows NO "not eligible" refusal for any of glob.py's
own generators (`_iglob`, `_glob1`/`_glob0`, `_glob2`, `_iterdir`,
`_rlistdir`) — they all still reach real `.cpp` coroutine generation, and
directly inspecting the generated `.cpp` (both in isolation, `do_imports=
False`, and inside the full `do_imports=True` build) confirms
`_mojogen__glob2_value` is correctly typed `char *` in BOTH — i.e.
`_glob2`'s own promise/yield-value type inference is and was already
CORRECT. The forward-reference `_generator_yield_ctype` theory doesn't
hold up: `_yield_from_delegate_ctype` (gimple_codegen.py:2560) already
defaults an unregistered-generator `yield from` target to `'char *'`
(not `int64_t` — that default was fixed by commit `c234efb`, already on
master), so even the forward-reference case was never actually broken
here.

**Real root cause: `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`** (new hard-bug doc, written this session). The failing
line is NOT inside `_glob2` at all — GCC's reported `glob.py:175` is a
red herring (an artifact of un-`#line`-stamped physical-line counting
past the end of the PREVIOUS `#line`-stamped statement; `_glob2`'s own
source-line range never appears in the `.ci` at all, since it compiles
entirely via the `.cpp` coroutine path). The real offending code is
`_listdir` (a plain, non-generator helper a few lines later in the same
`.ci` region):

```python
def _listdir(dirname, dir_fd, dironly):
    with contextlib.closing(_iterdir(dirname, dir_fd, dironly)) as it:
        return list(it)
```

`glob.py` does `import contextlib` at module scope, but the compiled
`.ci` resolves that bare name to `_subprocess_globals.contextlib` —
`Lib/subprocess.py` (transitively reachable from glob.py's own import
graph) ALSO does `import contextlib`, and `self._global_to_module`
(gimple_codegen.py:3907), the name-only "which module owns this bare
global name" map, is SHARED across every module compiled in the same
`do_imports=True` build with first-registration-wins semantics —
subprocess's registration happens first (its own recursive sub-compile
runs before glob.py's own root-level preamble scan), so glob.py's own
`contextlib` reads get silently redirected to subprocess's globals
struct instead of its own. The resulting type mismatch (subprocess's
`contextlib` field's C type vs. what `_listdir`'s locals expect) is what
actually produces the `-Wint-conversion` "assignment to int64_t from
char*" error. See the hard-bug doc for the full trace, breadth (at
least 9 `Lib/*.py` files `import contextlib` alone — this is not
glob.py/contextlib-specific), and why it's deliberately NOT fixed here
(same architectural shape/blast radius as the already-deferred task
#141, `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md` — a shared, name-only, first-writer-wins cross-module map
used at 4+ separate read sites project-wide, not a narrow generator-
codegen bug at all).

**Classification: NOT a generator-codegen-cluster failure.** Both of
glob.py's own generators compile correctly; the failure is entirely in
plain (`.ci`) code that happens to consume one, via a totally unrelated
cross-module global-resolution bug.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated further —
still look unrelated to the generator-codegen cluster (arity/import-
resolution issues in non-generator code; the `_subprocess_toplev`
naming is likely itself another symptom of the same cross-module
collision class, given the pattern above) and are left for a separate
pass.

## Status (updated 2026-08-06, SUPERSEDED — root cause below was wrong, kept for history)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'os' was not declared` .cpp error no longer reproduces
(dyld.py's documented "module attribute access not threaded into
generator scope" gap — see `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`
— appears fixed for glob.py's shape at least). `MOJO_DEBUG=1` shows NO
"not eligible" refusal for any of glob.py's own generators (`_iglob`,
`_glob1`/`_glob0`, `_glob2`, `_iterdir`, `_rlistdir`) — all pass the
eligibility pre-filter and reach real `.cpp` generation.

Current failure, still inside the generator-codegen cluster but a
DIFFERENT, narrower bug than the old one:

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```

**Root cause (read from `_glob2`'s source) — WRONG, see 2026-08-07 above:**
```python
def _glob2(dirname, pattern, dir_fd, dironly, include_hidden=False):
    assert _isrecursive(pattern)
    if not dirname or _isdir(dirname, dir_fd):
        yield pattern[:0]                                    # char* (empty string slice)
    yield from _rlistdir(dirname, dir_fd, dironly,            # forward reference!
                         include_hidden=include_hidden)
```
`_glob2` has TWO yield sites of apparently different shapes: a direct
`yield pattern[:0]` (a string slice, `char *`) and a `yield from
_rlistdir(...)` — but `_rlistdir` is DEFINED LATER in the file (line
218, vs. `_glob2` at line 170). This is the same forward-reference
caveat already surfaced in this session's `MOJO_DEBUG` output for a
different function in this same file (`tokenize`-style note: *"the
delegated-to generator must be defined earlier"*) — when the overall
generator's yielded-VALUE type is computed (`_generator_yield_ctype`),
the `yield from` to a not-yet-registered generator apparently doesn't
contribute its real element type to the join, so the combined value type
collapses to the `int64_t` default instead of joining to `char *` (the
correct common type, since `_rlistdir` itself ultimately yields strings
too). The result: the coroutine promise's `yield_value` is generated
expecting `int64_t`, but the `yield pattern[:0]` call site still
produces a real `char *` — hence "assignment to int64_t from char*".

This is a variant of the already-documented "generator yielded-value
type inference" gap (`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1, and the untyped-generator-param cousin in
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`'s sibling
docs) — specifically the FORWARD-REFERENCE angle of it: a generator with
a `yield from` to a same-file sibling generator defined LATER, combined
with an earlier plain `yield` of a different concrete type, produces a
wrong combined promise type. Not folded into a new hard-bug doc here
(only one clean instance traced end-to-end so far) — flagged for whoever
next hits this shape to fold into a broader "generator yield-value type
inference" hard doc once 2-3 more instances are confirmed.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated — they look
unrelated to the generator-codegen cluster (arity/import-resolution
issues in non-generator code) and are left for a separate pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/glob.py
