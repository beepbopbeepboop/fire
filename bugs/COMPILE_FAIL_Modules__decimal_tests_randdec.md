# COMPILE_FAIL: Modules/_decimal/tests/randdec.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py`

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
