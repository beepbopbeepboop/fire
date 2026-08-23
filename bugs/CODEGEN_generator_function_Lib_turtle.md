# CODEGEN_generator_function: Lib/turtle.py

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified, unchanged from the 2026-08-20 state)

Re-verified against current HEAD via a real `python3 mojo.py build
.../Lib/turtle.py`: turtle.py's own isolated error set is unchanged —
the same 5 root-caused lines (189 `eval()` dynamic-retyped local,
3078/3314/3379 `Vec2D` tuple-subclass operator-overload arithmetic,
4170 dead-code demo-block `write`) plus the module-qualified-symbol
cluster (213/218/219, `genericpath_isfile_584a43`-vs-`_0c85c9` suffix
mismatch — the bare-name/suffix collision family already tracked by
`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md`'s
analysis). All 3 of turtle.py's own generator sites still compile
cleanly. No new work attempted; every remaining line is already
classified in the 2026-08-20 entry below as broad/deferred or
dead-code-only. Doc stays open.

## Status (updated 2026-08-20 — 2 of the remaining 7 isolated errors root-caused and fixed; other 5 root-caused and correctly classified as broad/deferred or dead-code-only)

Followed up on the 2026-08-18 entry's remaining 7-error list (189, 3078,
3314, 3379, 750 x2, 4170). Re-verified fresh via isolated
`compile_to_gimple(src, do_imports=False, filename='turtle.py')` +
`gcc-mp-15 -fgimple -fsyntax-only`: all 7 confirmed still present
before this session, same lines, same shape.

### Fixed (2 real, narrow bugs — both additive upgrades to existing heuristics)

1. **Struct field type never inherited from a base class's `__init__`
   when the subclass overrides `__init__` itself.** `TurtleScreenBase.
   __init__` does `self.cv = cv` (an unannotated, defaulted-nowhere
   param, correctly inferred `int64_t`). `TurtleScreen.__init__` (and
   `_Screen`'s, inherited from `TurtleScreen`) never assigns `self.cv`
   directly — it only calls `TurtleScreenBase.__init__(self, cv)`.
   `_merge_struct_inheritance` (by design) excludes an OVERRIDDEN
   method from a subclass's merged `s.methods`, so `TurtleScreenBase.
   __init__`'s own `self.cv = cv` is never walked by `_collect_self_
   assigns` when building `TurtleScreen`'s/`_Screen`'s own
   `struct_field_types`. The field is still read all over each
   subclass's own methods (`self.cv.coords(...)`/`self.cv.config(...)`),
   so the READ-only fallback pass (`_collect_self_reads`, gimple_
   codegen.py ~34000) finds it — but, absent any base-class lookup,
   always defaulted it to the generic boxed-object `'int'` (32-bit).
   Result: `TurtleScreenBase.cv` was `int64_t` but `TurtleScreen.cv`/
   `_Screen.cv` were `int` — three DIFFERENT C types for the same
   logical field across `TurtleScreenBase`/`TurtleScreen`/`_Screen`,
   all three of which share the literal same Python method body
   (`_pointlist`, inherited unmodified) monomorphized once per struct.
   The `int`-typed copies produced a `self->cv` read into an `int`-
   declared temp with no cast, an int64_t/int split later assigning the
   comprehension loop var `i`, and ultimately GCC's honest "non-trivial
   conversion in 'integer_cst'"/"type mismatch in binary expression" on
   the shared body's `i = 0;`/increment once the value's type became
   inconsistent partway through. **Fix**: before defaulting an only-
   ever-read field to `'int'`, look it up on each base class (in MRO
   order, mirroring the EXISTING identical base-lookup pattern the
   VarDecl-completion pass a few hundred lines above already uses for
   the same reason) and inherit that type if the base already resolved
   it to something specific. Only ever upgrades the generic read-only
   guess to a more specific inherited type — never touches a field this
   class's own methods already resolved themselves.
2. **3-arg (and 2-arg) `range()`-based comprehension loops never cast
   `start`/`step` to `int64_t`.** `_compr_range_loop`'s 1-arg branch has
   an existing, well-documented fix (see its own comment) forcing
   `start_v`/`step_v` to be real pre-materialized `int64_t` temps rather
   than bare `int`-typed literal text, because the loop counter
   (`gen0.target`) is declared `int64_t` and GIMPLE has no implicit
   int->int64_t widening across statements. That fix was never extended
   to the 2-arg/3-arg branches, which still used the raw, `int`-typed
   `lower_expr()` result directly in the loop's initial assignment
   (`{target} = {start_v};`) and increment (`{target} + {step_v}`).
   `turtle.py`'s own `[(cl[i], -cl[i+1]) for i in range(0, len(cl),
   2)]` (`TurtleScreenBase._pointlist`, line 748) is exactly this
   3-arg shape. Empirically this was the fix that actually cleared the
   `line 750` "non-trivial conversion"/"type mismatch" errors in the
   REAL file (fix 1 alone left them in place) — `stop_v` didn't need
   the same treatment since it's only ever used inside a comparison
   (which undergoes GIMPLE's usual arithmetic conversion, unlike a
   direct copy/add). **Fix**: mirror the 1-arg branch's existing
   pattern — materialize `start_v`/`step_v` as real `int64_t` temps via
   `self._new_val('int64_t', f"(int64_t){v}")` whenever `lower_expr`
   didn't already give an `int64_t`-typed result, for both the 2-arg and
   3-arg branches.

Both fixes verified independently: isolated repro `.py` files
(base-class-inherited-field-read and 3-arg-range-comprehension shapes,
matching turtle.py's own code) compiled clean under `gcc -fgimple
-fsyntax-only` where the un-fixed `gimple_codegen.py` (checked via
`git show HEAD:gimple_codegen.py` loaded as a separate module — not
`git stash`, which this project's own history flags as unsafe with
concurrent agents sharing one `.git` — NOT the current worktree's
uncommitted diff) produced the wrong/weak type or left the un-cast
literal in place. Both repros then compiled+linked+ran end-to-end via
`gcc-mp-15 -fgimple -I runtime -o ... file.c runtime/mojo_runtime.c`
(the exact recipe `test_gimple_runner.py` uses) and produced the
correct output (`42` for the inherited-field case; the correct 3-tuple
list contents for the range-comprehension case). Turtle.py's own
isolated error count for THESE two fixes: the `line 750` pair (x3
monomorphized instances = 6 raw error lines) is gone. Quality gate:
`test_gimple.py` 248/248, `test_module_cache.py` 76/76, `make
check-selfhost` and a from-scratch stdlib dylib rebuild — see below for
results.

### Investigated and declined (broad/deep, matches this project's own established "defer, don't force" pattern)

- **189 (`config_dict`'s `value = eval(value)` inside a `str`/`float`/
  `int`-branching `try`/`except`), and its sibling 3-line manifestation
  at 189 specifically**: root-caused precisely — `value` is declared
  `char *` (its initial type, a string read from a config-file line);
  the `if "." in value: value = float(value)` branch calls
  `mojo_make_float(value)` (returns a real `double`) and the existing
  "coerce whatever this dynamically-retyped local produces back into
  the field's original C type" heuristic blindly does `value = (char
  *)_t86;` — a DIRECT floating-point-to-pointer C cast, which is
  outright illegal in C (unlike the sibling `int(value)` branch, whose
  `int64_t`->pointer cast is legal, if semantically a bit-reinterpret,
  which is why only the float branch errors). This is the same family
  of gap as `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`
  — a local variable whose real Python type varies across branches
  (`str` -> `float` -> `int`) has no representation in this codegen's
  one-C-type-per-variable model short of real boxing. Not a narrow
  fix: any correct fix means either (a) real dynamic boxing for this
  local (the same broad, deliberately-deferred mechanism gap as the
  linked hard-bug doc), or (b) a special-cased reinterpret-through-
  bits path for exactly this "double result assigned into a pointer-
  typed local" shape, which is itself an ad hoc hack around the real
  gap, not a genuine narrowing of an existing heuristic. Declined,
  matches this project's own bar for `bugs/hard/`.
- **3078/3314/3379 (`Vec2D` tuple-subclass operator-overload
  arithmetic)**: confirmed, not just speculated as in the 2026-08-18
  entry — traced concretely at all three sites (`_polytrafo`'s `e =
  Vec2D(e0, ...); e0, e1 = (1.0 / abs(e)) * e`; `_goto`'s `delta = diff
  * (1.0/nhops)`; `_undogoto`'s `self._position = start + delta * n`).
  In every case the codegen treats `Vec2D`-typed values flowing through
  `+`/`*`/unpacking as raw `double`/`int64_t` scalars (doing plain
  floating-point arithmetic directly) instead of dispatching to
  `Vec2D`'s real `__add__`/`__mul__`/`__rmul__` struct methods, then at
  the end blindly casts the scalar arithmetic RESULT directly to
  `Vec2D *` (a hard "cannot convert to a pointer type"/"invalid types
  in conversion to integer" — a double or int64_t bit pattern is never
  a valid `Vec2D *`). This is a systemic type-inference gap in how this
  codegen tracks a local variable's REAL type through a chain of
  arithmetic operators/tuple-unpacking when that variable's static type
  is a user struct with operator-overload dunders, not confined to one
  call site or expression shape — genuinely feature-sized (would need
  real "is this expression's static type actually a struct with
  `__add__`/`__mul__`/etc., and if so dispatch through it instead of
  falling to scalar arithmetic" tracking, threaded through the full
  binary-op/unpacking lowering path). Declined — matches this project's
  own bar for deferring broad/systemic gaps to `bugs/hard/` rather than
  force-fitting a narrow patch.
- **4170 (`write("startstart", 1)`, implicit-declaration-of-`write`)**:
  confirmed dead code — inside `if __name__ == "__main__":` (starting
  line 4130), turtle.py's own demo/self-test block, never reached when
  the module is imported. Root cause: `write` here isn't a real
  top-level function definition anywhere in turtle.py's own source —
  it's synthesized dynamically at runtime by turtle.py's own
  `_make_global_funcs(functions, ...)` machinery (mirroring several of
  the module's other dynamically-generated top-level names, e.g.
  `forward`/`right`/`color` used just above it in the same demo block,
  which DO compile — likely because they happen to collide with a name
  this codegen resolves some other way, not investigated further since
  this is dead code either way). Not a simple "missing builtin
  dispatch" gap — the real fix would mean statically resolving a name
  that literally does not exist as a function definition anywhere in
  the source, another instance of the dynamic-metaprogramming category
  this project's `bugs/hard/` docs already track elsewhere. Low
  priority, matches the `bugs/COMPILE_FAIL_ctypes_util.md` precedent
  for dead demo/test-only code: not fixed.

Turtle.py's own isolated `-fgimple` error count: **7 -> 5** (unique
source lines; the 750 pair, each previously producing 2 raw GCC error
lines x 3 monomorphized struct instances, is fully gone). Remaining 5
(189, 3078, 3314, 3379, 4170) are root-caused, all correctly classified
as either broad/deferred (matches `bugs/hard/` bar) or dead-code-only,
per above. turtle.py still does not build end-to-end (see final
section below for the whole-program `mojo.py build` check).

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
