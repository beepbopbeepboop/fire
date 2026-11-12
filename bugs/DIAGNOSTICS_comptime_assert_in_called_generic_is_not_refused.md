# DIAGNOSTICS: a provably false `comptime assert` in a called generic function compiles

Status: RESOLVED FOR THE BUILD, OPEN FOR THE IN-PROCESS API. Filed 2026-11-11 on master.

Corrected diagnosis (2026-11-11, after the fix): the real build (`fire.py build`) ALREADY refuses a called generic with a provably false assert or constrained: `comptime assertion failed: nope` and `constraint failed: nope`, both matching the tests. The gap was in the in-process `compile_to_gimple` path, which does not instantiate a generic. The two tests now check the diagnostic through the real build (`diagnostic_build.py`), and the suite markers are removed.

Still open, and WORSE than a missing diagnostic: `compile_to_gimple` (do_imports True or False) does not instantiate a generic function, so a call `f[1]()` lowers to a zero stub, `_t1 = (int64_t)0; /* indirect call via SubscriptExpr */` (`mojo/backend_gimple/emit_calls.py`, the catch-all at the end of `_lower_call`). Measured: `def f[x: Int]() -> Int: return x + 1` with `print(f[1]())` prints `0` in-process, and `fire.py build` on the same program prints `2`. So the in-process API gives a silently wrong answer for a called generic.

Why it is not fixed by a one-line refusal: the stub is deliberate. The comment at the catch-all says rejecting these cases "left six modules red", and the stdlib compile depends on the stub for generic-struct and imported bases. A refusal has to be narrowed to a generic FUNCTION defined in the same module, which needs the set of such functions plumbed into the generator (it is not there today: `func_return_types` holds only elaborated signatures). The next step is that plumbing, the narrow refusal, and then `compile_stdlib.py` to confirm no stdlib module depended on the stub.
 Measured with the real compiler (`tools/mojo build`) and ours (`compile_to_gimple`).

## Symptom

A generic function whose body has a provably false `comptime assert` compiles with no error on our compiler, even when
the function is called, so the assertion is never enforced:

    def f[x: Int]():
        comptime assert False and x > 0, "nope"

    def main():
        f[1]()

Real Mojo refuses it. Ours compiles it. The same assert in a NON-generic function is refused by ours with
`comptime assertion failed: nope`.

## What the real compiler says (measured)

Uncalled, `def f[x: Int](): comptime assert False, "nope"` with a `main` that does not call it: ACCEPTED (rc=0). Real Mojo
does not check the body of a generic it never instantiates. Our compiler agrees with that.

Called, `f[1]()` from `main`: REFUSED. Full output:

    g.mojo:4:5: error: function instantiation failed          (at main's name)
    g.mojo:5:9: note: call expansion failed                   (at the call's f)
    g.mojo:1:5: note: function instantiation failed           (at f's name)
    g.mojo:2:5: note: constraint failed: nope                 (at the comptime assert)

The primary error is at `main`. The reason is a `constraint failed: nope` note at the assert. Real Mojo's wording for a
`comptime assert` is "constraint failed", not "comptime assertion failed".

## What ours does (measured)

| case | ours |
|---|---|
| uncalled generic, `comptime assert False` | compiles (matches real) |
| called generic, `comptime assert False` | compiles: GAP |
| called generic, `comptime assert False and x > 0` | compiles: GAP |
| non-generic `comptime assert False and 1 > 0` | refused: `comptime assertion failed: nope` |

So `False and <unknown>` is NOT the defect. The comptime evaluator already folds `False and x` to `False`
(`mojo/middle/comptime.py`, the `and` arm of `eval_const`). The defect is that a generic body is not checked when it is
instantiated through a call.

## Why it matters

The test files `test_comptime_assert_diagnostic.py` and `test_constrained_diagnostic.py` each had one failing case,
`short_circuit_and_false`, written against an uncalled generic. Real Mojo accepts that shape, so the test was wrong about
the uncalled case. Once the generic is called, the test is a true statement of the bug, and it fails here.

## Design (decided)

- An uncalled generic is not checked. Keep it that way; it matches real Mojo.
- A called generic must be checked at instantiation: a provably false `comptime assert` or `constrained` in its body is
  refused, at the same location as the real compiler's note, with the message the real compiler gives.
- The primary-error wording (`function instantiation failed` at the caller) is a separate question. Decide it when the
  fix lands, against the measured output above, not from memory.
- The wording of OUR refusal ("comptime assertion failed") differs from real Mojo's ("constraint failed"). That is a
  separate decision; the tests keep pinning our wording until it is made.

## Fix order

1. Find where a generic body is elaborated for a call on the compiled path (`mojo/backend_gimple/` monomorphisation) and
   confirm the comptime-assert check is skipped there. Measure with a `print` of the instantiation, not from reading.
2. Run the assert check on the instantiated body, with the type parameter bound.
3. Pin the real refusal location in the two test files. Remove their `expectedFailure`/`expect=` markers in the same
   commit.
