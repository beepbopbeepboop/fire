# COMPILE_FAIL: Modules/_decimal/tests/randdec.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py`

## Status (re-verified 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb`): identical 17-generator refusal, unchanged

Fresh safety-wrapped `python3 mojo.py build .../randdec.py` against
this worktree (includes this session's dict-keyed %-formatting landing,
commit `e1e12bb` — unrelated to any of the four causes below):
byte-identical refusal list to the same-day entries below — all 17
generators (`all_binary` ... `un_random_mixed_op`), same per-generator
causes (8 × unresolved `from random import randrange, sample` callees,
6 × function-valued loop-variable calls, `un_incr_digits_tuple`'s mixed
scalar/tuple shape, 3 × consumption-ordering-derived). Note the
campaign's broader finding that CPython Lib modules are invisible to
every import resolver for entry files OUTSIDE Lib/ (`.mojo`-only
resolvers; walk-up from Modules/_decimal/tests never reaches Lib/) —
the unresolved-`random` group is an instance of that shared mechanism,
not randdec-specific. No tractable angle found; not attempted; no code
change.

## Status (re-verified 2026-08-26, wtRest19b — second independent re-check same day)

Independent fresh repro (own safety-wrapped build, this worktree)
confirms byte-identical output to the same-day entry immediately
below: same 17-generator refusal list, same per-generator causes
(`sample`/`func`/`func1` unresolved-callee refusals for the random-
import and callable-value-loop-variable groups, consumption-ordering
derivation for `all_binary`/`all_ternary`/`all_unary`). No new
tractable angle found. Not attempted; no code change.

## Status (re-verified 2026-08-26)

Fresh repro against this session's tree (`fix/rest-remainder18`)
reproduces the identical 17-generator refusal set named in the
2026-08-25 entry below, byte-for-byte the same function list
(`all_binary`, `all_ternary`, `all_unary`, `bin_close_numbers`,
`bin_close_to_pow10`, `bin_incr_digits`, `bin_random_mixed_op`,
`logical_bin_incr_digits`, `logical_un_incr_digits`,
`tern_close_numbers`, `tern_incr_digits`, `tern_random_mixed_op`,
`un_close_numbers`, `un_close_to_pow10`, `un_incr_digits`,
`un_incr_digits_tuple`, `un_random_mixed_op`). Given the 2026-08-25
session's own detailed per-generator classification (8 unresolvable
`random`-module imports, 6 function-valued loop-variable calls, 1
mixed-scalar/tuple structural case, 3 consumption-ordering-derived) was
produced from a fresh, skeptical re-diagnosis that session and matches
what this session independently observes, no further reclassification
was needed — the categories hold. The one shared-mechanism fix that
session landed (commit `3dcd224`, the char*/MojoList* cross-unification
honesty fix) is present in this tree (verified via `git log --oneline
-- gimple_exprtypes.py` showing it in history) and unaffected by
anything since. No code change this pass; doc re-verified only.

## Status (updated 2026-08-25, wtOpencode_randdec — doc's headline blocker is OBSOLETE (varying-arity tuple yields already fixed by later work); true remaining causes re-diagnosed per-generator; one real latent honesty bug found on this file's exact mixed-yield shape FIXED (commit 3dcd224); whole file still does not build)

Fresh repro on this branch tip (`python3 mojo.py build .../randdec.py`,
under the mandated RAM/wall-clock watcher). The doc's previous framing is
substantially stale; current ground truth:

**1. The doc's named blocker — varying-arity tuple yields — no longer
exists.** `unary_optarg` (2-tuple + 3-tuple), `binary_optarg` (3+4),
`ternary_optarg` (4+5) are NOT in the refusal list at all anymore:
`_generator_tuple_yield_slot_ctypes` now unifies differing arities to the
LONGEST site's shape with zero-padding (landed for pickletools.py's
`_genops`, which has the same 3-vs-4 shape) and `unary_optarg` et al.
compile past the eligibility gate. The task prompt's skeptical question
("are they really variable-arity?") is answered: they genuinely were
(2/3, 3/4, 4/5 pairs in one body), but the padding mechanism made that
harmless — consumer unpacking reads only the common prefix.

**2. Today's actual refusal list is 17 generators, all reducible to four
real causes:**

- **8 × unresolved IMPORT callees in generator bodies**
  (`un_close_to_pow10`, `bin_close_to_pow10`, `un_incr_digits`,
  `bin_incr_digits`, `un_incr_digits_tuple`, `logical_un_incr_digits`,
  `logical_bin_incr_digits`, `tern_incr_digits`; refusal text: "a call to
  unresolved callee 'sample(...)'..."). `from random import randrange,
  sample` cannot resolve: module_loader only resolves Mojo stdlib/test
  modules (.mojo files); CPython's Lib/random.py is invisible to every
  resolver (`_parsed_import` → imports.resolve_source MOJO_PATH search +
  `_resolve_test_relative_module` .mojo-only walk-up). In compiled mode
  these names bind to the weak auto-stubs that PRINT "unavailable in
  compiled mode" and return 0 (verified end-to-end with a standalone
  repro: ordinary-path `sample(range(10), 3)` in a compiled binary prints
  the stub message and yields nothing usable). Per fd909e9 and
  CODEGEN_generator_function_Lib_weakref.md's 2026-08-25 finding 3, the
  coroutine emitter DELIBERATELY refuses here: compiling these bodies
  against stubs would convert today's working whole-module interpreter
  fallback into compiled code whose every random value is 0 / whose
  sample() returns a null list — strictly worse. Genuinely fixing it
  means teaching module_loader to inline-compile arbitrary CPython Lib
  modules (the campaign's broader goal, not narrow).

- **6 × function-valued loop variables CALLED inside generator bodies**
  (`un_close_numbers`, `bin_close_numbers`, `tern_close_numbers`,
  `un_random_mixed_op`, `bin_random_mixed_op`,
  `tern_random_mixed_op`; refusal: "a call to unresolved callee
  'func(...)'/'func1(...)'"). Shape: `for func in close_funcs: yield
  func(prec, emax, emin)` over the module-global `close_funcs` /
  `number_funcs` lists of same-module function references. Same
  structural callable-value gap documented across the weakref/
  pickletools/operator docs: a value read out of a runtime container has
  no callable representation in this scalar coroutine-body model (the
  existing `_CPP_CALLABLE_CTYPE` local path requires a statically-known
  lambda/method-RHS assignment, not an iteration binding). Not
  attempted; feature-sized.

- **1 × mixed scalar/tuple yields, masked**: `un_incr_digits_tuple`'s
  LISTED reason today is `sample(...)`, but underneath that sit TWO more
  independent layers: (a) scalar `yield from_triple(...)` sites infer
  char* while its tuple sites contribute 'MojoList *', and the old
  char*-preference merge silently unified the promise to `char *` —
  so the tuple sites would have reached g++ as
  `cannot convert 'MojoList*' to 'char*'` (hard .cpp compile failure,
  verified pre-fix via a minimal repro) — see item 3; (b) even with
  honest refusal at (a), the tuple site's own middle element
  `tuple(map(int, str(ndigits(m))))` is a runtime-constructed nested
  tuple (`map` has no coroutine-body lowering), still unsupported.

- **3 × derived consumption-ordering refusals** (`all_binary`,
  `all_ternary`, `all_unary`): purely downstream of the earlier groups —
  each consumes generators this compile could not translate ("consumed
  generator must be defined earlier AND supported" rule).

**3. FIXED this session (commit 3dcd224): the honesty layer under (a)
above, plus two sibling holes proven by repro.** `_generator_yield_ctype`
(gimple_exprtypes.py) now:
- refuses the 'MojoList *'×'char *' cross-unification in BOTH merge
  branches (YieldExpr and YieldFromExpr) instead of letting the
  char*-preference pick a promise type one of the sites provably cannot
  co_yield into;
- refuses DIRECT collection-literal yield values (`yield [1, 2]`,
  `yield {...}`): `_cpp_expr` lowers these to raw braced-init-lists,
  valid as a co_yield operand for NO promise type (previously reached
  g++ as `co_yield {1, 2};` → hard failure).
The glob.py load-bearing char*-preference for inference-fallback sites
(int-inferred-but-really-stringy) is untouched; int×str and
int×MojoList* disagreements keep their existing behavior. Cannot regress
any currently-compiling module: a body emitting both genuine char* and
genuine MojoList* values into one promise never linked. Quality gate:
test_gimple.py 256/256 (3 new regression tests), test_module_cache.py
76/76, make check-selfhost clean, stdlib dylib rebuild 0 skips. NOTE:
this fix does not change randdec.py's visible refusal list (the
emission-time `sample`/`func` refusals fire before yield-type
unification ever runs for these bodies) — it removes the guaranteed g++
failure waiting one layer beneath `un_incr_digits_tuple`.

**Residual, documented-not-fixed (adjacent finding, not exercised by any
currently-compiling file):** a BARE `yield` appearing AFTER another
yield site contributes no type opinion (`if ctype is None` guard,
gimple_exprtypes.py ~line 1151) while emitting `co_yield (int64_t)0;` —
so a generator like `yield 'abc'` followed by bare `yield` would unify
to char* and hit the same invalid-conversion g++ failure. Same class as
item 3; left alone this pass to keep the change minimal.

**Verdict:** the file as a whole still does not build, and per the
conventions above none of the remaining causes is narrowly tractable:
two require campaign-sized import/callable machinery, and the third
(un_incr_digits_tuple's deeper layers) is structural even after the
honesty fix. Doc stays open as DOCUMENTED-NOT-FIXED, now with accurate
per-generator reasons.

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — same 5-generator remainder, one now DERIVED)

Re-ran the repro fresh. The refusal list is exactly 5 generators:
`un_incr_digits_tuple`, `all_unary`, `unary_optarg`, `binary_optarg`,
`ternary_optarg`. This matches the 2026-08-10 analysis below with one
clarification: `all_unary`'s refusal is DERIVED, not independent —
MOJO_DEBUG shows it is refused because its `for ... in
un_incr_digits_tuple(...)` consumes a generator this compile could not
itself translate (the "consumed generator must be defined earlier AND
supported" rule), so the true remaining causes are the SAME four as
documented below: varying-arity tuple yields (`unary_optarg`,
`binary_optarg`, `ternary_optarg`) and the scalar/tuple mixed-yield
generator (`un_incr_digits_tuple`). Both remain squarely outside the
landed fixed-arity fix's documented scope boundary: padding shorter
yield tuples to a common arity would change observable tuple lengths at
the consumer (unsound), and a scalar yield and a tuple yield can never
share one promise value representation under the current design.
Still DOCUMENTED-NOT-FIXED; no code changes this pass.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED for fixed-arity tuples; 10 of the 14 refused generators now compile; 4 remain refused for well-understood, in-scope reasons)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`/`_generator_yield_ctype`'s widened `TupleExpr` handling — a
tuple's elements are boxed into a real `MojoList *` at the yield site,
unboxed on the consumer side). Deliberately scoped to a FIXED element
count per generator (every `yield`/`yield from` site in one generator
must agree on both arity and — with a char*-preference merge rule —
each slot's type; see this fix's own commit for the full design), not a
general variadic/heterogeneous-shape promise.

Re-verified this file's whole-program refusal list (`python3 mojo.py
build .../randdec.py`, do_imports=True, Python-level eligibility check
only): it now names only 4 of the original 14 refused generators —
**`all_binary`, `all_ternary`, `all_unary`, `bin_close_numbers`,
`bin_close_to_pow10`, `bin_incr_digits`, `bin_random_mixed_op`,
`logical_bin_incr_digits`, `tern_close_numbers`, `tern_incr_digits`,
and `tern_random_mixed_op` (10 of the 14) now compile past the
eligibility gate** — each `yield a, b`/`yield a, b, c` in those turned
out to be a real, FIXED-arity tuple, exactly this fix's target shape.

**4 generators remain refused, correctly, for reasons this fix's own
documented scope boundary explicitly excludes:**
- `unary_optarg`: `yield randdec(...), None` (2-tuple) AND `yield
  randdec(...), None, None` (3-tuple) — genuinely VARYING arity across
  yield sites in the same function (a deliberate test-code idiom:
  exercising an optional-trailing-arg call shape). This fix requires one
  fixed arity per generator; refused via `_generator_tuple_yield_slot_
  ctypes`'s explicit arity-mismatch check.
- `binary_optarg` (3-tuple then 4-tuple) / `ternary_optarg` (4-tuple
  then 5-tuple): the same varying-arity pattern, one slot wider.
- `un_incr_digits_tuple`: mixes SCALAR yields (`yield from_triple(1,
  ndigits(m), 0)`, a plain function-call result) with literal TUPLE
  yields (`yield (0, tuple(map(int, str(ndigits(m)))), 0)`) at
  DIFFERENT sites in the SAME function — these can never share one
  promise value type regardless of arity support (`_generator_yield_
  ctype`'s outer unification correctly disagrees: int64_t vs.
  MojoList*). Also note: this specific tuple's own middle element
  (`tuple(map(...))`) is itself a runtime-constructed nested tuple, a
  second, independent reason this exact yield site couldn't be boxed
  even in isolation.

Since the file still has 4 refused generators, `gen_module` still
raises and the whole-program build still fails as a unit — but this is
now a MUCH smaller, precisely-scoped, and correctly-diagnosed remainder
(4 of 14, both documented reasons squarely inside this fix's own stated
scope boundary — see the task guidance's "yield tuples with a FIXED,
small element count" allowance) rather than the general structural gap
this doc previously described. Doc kept open (not deleted) — updated
rather than superseded, since 10/14 is real, verified progress but the
file as a whole still doesn't build.

## Status (updated 2026-08-09 — re-verified, root cause corrected: this is now
## purely the known tuple-valued-yield structural gap, not the `nan`/
## `randfloat.py` issues the previous status section described)

Re-ran `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py` fresh
against current master. The previously-reported `nan()`-vs-C99-`nan()`
name-collision and the separate `randfloat.py` pointer/int mismatch are
BOTH gone/moot — neither is reachable any more, because compilation now
fails much earlier, at `gen_module`'s generator-eligibility pre-pass,
before any individual function body (or the `randfloat` sibling import)
is ever lowered to C. Current, single, real error:

```
Error building: cannot compile module: function(s) all_binary, all_ternary,
all_unary, bin_close_numbers, bin_close_to_pow10, bin_incr_digits,
bin_random_mixed_op, binary_optarg, logical_bin_incr_digits,
tern_close_numbers, tern_incr_digits, tern_random_mixed_op,
ternary_optarg, un_incr_digits_tuple, unary_optarg (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

(That message's generic "no suspend/resume transform at all" wording is
stale boilerplate — this codegen DOES have a real C++20-coroutine
generator path now, see `gimple_codegen.py`'s
`_gen_cpp_generator_unit`/`_generator_quick_eligible`. The 14 functions
named above are simply the ones that fail that path's real eligibility
check, not proof no path exists.)

## Root cause

`randdec.py` defines ~30 top-level generator functions. All 14 that
fail share one trait none of the ~16 that succeed do: they `yield` a
**multi-element tuple** (`yield coeff, 1`, `yield func(prec, emax,
emin), func(prec, emax, emin)`, `yield (a,)`, etc.) instead of a single
scalar value. Confirmed directly: the ones that compile clean
(`un_close_to_pow10`, `un_close_numbers`, `un_incr_digits`,
`logical_un_incr_digits`, `un_random_mixed_op`, ...) all `yield` a
single scalar (int/decimal-string handle); every one of the 14 refused
functions has at least one `yield a, b` / `yield a, b, c` site.

This is the SAME structural gap already root-caused and documented in
`bugs/CODEGEN_generator_function_Lib_test_libregrtest_save_env.md` and
`bugs/CODEGEN_generator_function_Lib_test_test_exception_group.md`:
`gimple_codegen.py`'s compiled-generator ABI (`_gen_cpp_generator_unit`)
represents a generator's suspended state as a `std::coroutine_handle`
plus a promise whose `yield_value` accepts exactly ONE scalar
(`int64_t`/`double`/`_Bool`/`char *`) — there is no promise/ABI shape
for "yields a tuple of N values" at all. `_generator_yield_ctype`
(the single source of truth for a generator's unified value type,
`gimple_codegen.py` ~line 2647) already has an explicit, deliberate
`if isinstance(n.value, TupleExpr): return None` early-out in its
`YieldExpr` case specifically to refuse this shape honestly (propagating
"unsupported" up to `_gen_cpp_generator_unit`'s `if value_ctype is None:
raise _UnsupportedGeneratorShape(...)`) rather than let the previously-
buggy "unknown type defaults to int64_t" fallback silently swallow it
and produce mismatched/invalid C++ (`co_yield {a, b};` against a
scalar-only promise) — that swallowing bug was the ACTUAL fix landed
for the `save_env.py`/`test_exception_group.py` docs; it is not a
distinct bug here, `randdec.py` is just another real-world file hitting
the same, still-open, structural gap those docs already describe.

## Why this is not being fixed here

Per the `save_env.py` doc's own "Not fixed" section: making tuple-
valued yields actually compile would require a real multi-value
carrying mechanism through the coroutine promise/ABI boundary — e.g.
promoting `value_ctype` to a heap-boxed tuple representation (mirroring
how ordinary compiled tuples are already boxed elsewhere in this
codegen) and threading that through `<base>_value`'s C-side accessor,
plus every yield/yield-from-delegation site's type-unification logic.
That is a new value-representation category for the generator codegen
subsystem, not a local stub/case fix — exactly the kind of "structural/
systemic gap" this project's bug-triage convention says should be
documented, not force-fixed by a subagent in isolation (see CLAUDE.md's
quality-gate section and this file's own two sibling docs for the
established pattern: same root cause, independently re-confirmed twice
already, still open both times).

Left open. No code changes made for this bug.
