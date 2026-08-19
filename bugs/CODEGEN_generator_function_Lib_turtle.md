# CODEGEN_generator_function: Lib/turtle.py

## Status (updated 2026-08-18 — the 2026-08-07 "invalid conversion in return statement" cluster (1618/2331/2372) root-caused and fixed; NOT a `_quick_type` gap)

Followed up on the 2026-08-07 entry's flag ("plausibly more
`_quick_type`-family instances, same shape as the `.keys()`/`.values()`/
`.items()` fix"). Confirmed by isolated `do_imports=False` compile +
`-fgimple` build of turtle.py's own real source (23 errors before this
session) that all 3 lines (1618, 2331, 2372) share ONE real root cause —
but it is **not** the `_quick_type` self-method-call fallback at all
(gimple_codegen.py ~line 7814, "Try as struct instance method call"),
which was already correctly resolving `self._color(...)` to the right
mangled callee. Two separate, narrower bugs, found by tracing the actual
declared-vs-body-produced type mismatch instead of guessing:

1. **Struct field type inference: "first assignment wins" picked the
   weakest candidate.** `RawTurtle.__init__` assigns `self.screen` from
   FOUR different if/elif branches; the first in document order is
   `self.screen = canvas` where `canvas` is an unannotated, defaulted
   (`=None`) parameter — `_collect_self_assigns` (gimple_codegen.py)
   inferred this as the generic `int64_t` fallback and, because it only
   ever recorded the FIRST assignment to a given field name, never let a
   later, far more specific branch in the SAME `__init__`
   (`self.screen = TurtleScreen(canvas)`, which the existing "CallExpr
   whose callee name is a known struct" branch would have correctly
   resolved to `TurtleScreen *`) compete. The wrongly-`int64_t`-typed
   `screen` field made every `self.screen.<method>(...)` call site
   (`RawTurtle._color`/`_colorstr` calling `self.screen._color(args)`)
   unresolvable to a real struct method — silently lowered as an
   "int64_t.<method>() stubbed" no-op — which in turn made `_color`'s own
   inferred return type wrong, cascading into the `invalid conversion in
   return statement` on every caller (`pencolor`/`fillcolor`) whose
   forward-declared return type was inferred from `_color`'s wrong type.
   **Fix**: generalized the EXISTING cross-method `can_override` upgrade
   rule (weak `'int'` → a real pointer type, previously scoped to
   comparing one method's result against an already-established type from
   an EARLIER method) to also apply WITHIN a single method's own multiple
   assignment sites, and to the `'int64_t'` weak default too (the case
   that actually fires for an unannotated/defaulted parameter, not just
   bare `'int'`). Only ever upgrades a generic `int`/`int64_t` guess to a
   more specific type — never fights two already-specific candidates
   against each other.
2. **Bare `return` (Python `return None`) inside a non-`int`/non-pointer
   -returning function emitted an uncast `return 0;`.** `_gen_stmt_
   ReturnStmt` (gimple_codegen.py) unconditionally emitted the literal
   `return 0;` for a value-less `return` in a non-void function,
   regardless of the function's actual declared C return type. A bare
   integer literal's own C type is `int`, so this only actually
   type-checked under `-fgimple` when the function's inferred return type
   was plain `'int'` (rare in this codegen) or a pointer type (`0` is
   also a valid null-pointer constant there, confirmed separately with a
   minimal repro). Any OTHER type — most commonly `int64_t`, this
   codegen's default "boxed scalar" representation, used far more often
   than plain `int` — left a bare `int`-typed `0` returned from a
   differently-typed function: GIMPLE (unlike ordinary C) does not
   implicitly convert an untyped integer literal across scalar C types on
   `return`, so GCC honestly rejects it. Real: `TPen.pencolor`/
   `.fillcolor`, each with an early bare `return` (`if color ==
   self._pencolor: return`) alongside another branch returning
   `self._color(...)`'s real (int64_t, once fix 1 above resolved
   `_color`'s own type) value — the whole function's inferred return type
   is int64_t, so the bare-return path's naked `return 0;` mismatched.
   Confirmed the same bare-`return`-vs-int64_t shape also explains the
   1618 (`TNavigator`/`RawTurtle`/`Turtle`'s `_setmode`) occurrences.
   **Fix**: for a bare `return` in a non-void, non-`int`, non-pointer
   -typed function, synthesize a properly-typed zero via a temp + explicit
   cast (`(ret_type)0`, or `0.0` for `double`) instead of the bare
   literal.

Together these two fixes eliminate ALL THREE originally-flagged
"invalid conversion in return statement" sites (1618, 2331, 2372) with
zero new errors introduced — turtle.py's own isolated `-fgimple` error
count dropped 23 → 16, remainder unrelated (see below). Verified NOT a
broader/riskier change: both fixes are narrow, additive upgrades to
existing, already-established heuristics in their respective functions
(mirroring the exact "weak type → specific type, never specific vs.
specific" and "cast the synthesized literal to the declared return type"
patterns this codebase already uses elsewhere), and the mandatory
quality gate (`test_gimple.py` 248/248, `test_module_cache.py` 76/76,
`make check-selfhost` 1/1, and a from-scratch stdlib dylib rebuild —
0 skips before AND after, byte-identical dylib size) all passed with no
regression. Two standalone isolated repros (one per fix) compiled AND
ran via `mojo.py`, confirming correct runtime behavior, not just
"compiles clean".

turtle.py's remaining 16 isolated-compile errors are UNRELATED to this
fix and to generators (unchanged classification): `mojo_open_file`
2-arg, the `genericpath_isfile`/`ntpath_split`/`ntpath_join`
module-qualified-symbol gap, `cannot convert to a pointer type` (189,
`eval()`-into-dict-value; 3078, `Vec2D` tuple-subclass operator overload
arithmetic — checked, both are clearly different families, not
force-fit into this fix), `invalid types in conversion to integer`
(3314/3379), `non-trivial conversion`/`type mismatch in binary
expression` (750), and `implicit declaration of write` (4170). turtle.py
still does not build end-to-end. Commit: see this file's own git log
for the commit landing this fix.

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included (the 2026-08-06 entry below —
already noted fixed as of 2026-08-07, `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`'s mechanism-1/mechanism-2
fixes). Confirmed via fresh rebuild: zero occurrences now, unaffected
either way. While tracing the mechanism, found+fixed a closely related
residual bug (`_gen_struct_method`/`_gen_lifted_closure` never setting
`self._current_module_ctx`, misrouting a `global`-statement write
inside a class method to the wrong module's struct — see that hard-bug
doc's history and this session's commit) plus a related `_safe_coerce_
emit` `.`-access gap. Effect on this file: total build error count
dropped 536 -> 534 via a fresh rebuild. turtle.py's own 3 generator
sites and the `mojo_open_file`/`genericpath_isfile`/`ntpath_split`/
`ntpath_join`/etc. cluster below are unaffected and remain this file's
real blockers.

## Status (re-verified 2026-08-09, unchanged from 2026-08-07)

Fresh from-scratch `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/turtle.py` on current master. Classification unchanged: **NOT a
generator-codegen-cluster failure**. turtle.py's 3 bare-`yield` sites
(lines 1312, 3442, 3586) still show zero signal of a problem — no
"not eligible" refusal under `MOJO_DEBUG=1`, and none of the current
build's `error:` lines land on those lines. The transitive build now
pulls in `Lib/tkinter/simpledialog.py` (315 of the run's errors, an
unrelated file/bug not investigated here) which pushes the raw total
error count much higher than the ~21 seen 2026-08-07, but turtle.py's
own distinct error set is essentially the same 14 lines as before:
`mojo_open_file` 2-arg (171, 4001), the `genericpath_isfile`/
`ntpath_split`/`ntpath_join` module-qualified-symbol gap (213/218/219),
`invalid conversion in return statement` (1618/2331/2372), `cannot
convert to a pointer type` (189/3078), `invalid types in conversion to
integer` (3314/3379), `non-trivial conversion`/`type mismatch in binary
expression` (750), plus one new one: implicit declaration of `write`
(4170, likely a builtin/method-dispatch gap unrelated to generators).
None of this implicates turtle.py's own generators. Still out of scope
for this generator-codegen cluster; no code change made here.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** — all 3 of
turtle.py's own generator sites still show zero signal of a problem.
The `struct _selectors_toplev` error is GONE (fixed by `bugs/hard/
COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s "mechanism
2" landing, same fix confirmed across several files this session), but
with that no longer masking downstream compilation, MANY more of
turtle.py's own non-generator errors are now visible (21 total, up
from ~5): the `mojo_open_file`/`genericpath_isfile`/`ntpath_split`/
`ntpath_join` issues noted below are still present in the same shape,
plus several NEW ones — repeated `invalid conversion in return
statement` (lines 1618/2331/2372 — plausibly more `_quick_type`-family
instances, same shape as the `.keys()`/`.values()`/`.items()` fix made
elsewhere this session, though not confirmed for these specific call
sites), `invalid types in conversion to integer` (2243/3314/3379/3397),
and `non-trivial conversion`/`cannot convert to a pointer type` at
several more lines. None implicate turtle.py's own generators. Not
investigated further here — out of scope for this generator-codegen
cluster; worth a dedicated non-generator pass, and the `invalid
conversion in return statement` sites specifically would be a
reasonable next place to check for more `_quick_type` gaps.

## Status (updated 2026-08-06, superseded above — module_toplev error since independently fixed, many more turtle.py-own errors now visible)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'Vec2D' does not name a type` .cpp error no longer
reproduces. `turtle.py` has 3 bare `yield` sites (no value, lines 1312,
3442, 3586) — none appear in the current error list, and `MOJO_DEBUG=1`
shows no "not eligible" refusal for any of them: turtle.py's own
generators now appear to compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are all unrelated:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (6th confirmed occurrence, here for `selectors`):
  `turtle.py:264:27: error: invalid use of undefined type 'struct _selectors_toplev'`
- Several other apparently-unrelated non-generator bugs: `mojo_open_file`
  called with 2 args but declared to take 1
  (`turtle.py:171`), implicit declarations of
  `genericpath_isfile_584a43`/`ntpath_split_0c85c9`/`ntpath_join`
  (`turtle.py:213/218/219` — looks like a module-qualified-symbol
  resolution gap distinct from the toplev-struct issue, since these are
  function CALLS not member-struct accesses), and a `MojoList *` field
  assigned from a raw `int` at `turtle.py:218`.

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/turtle.py
