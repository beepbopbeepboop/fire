# COMPILE_FAIL: Modules/_decimal/tests/randdec.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py`

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
