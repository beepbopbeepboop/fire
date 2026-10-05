# A float program divides by zero and gets an infinity; CPython raises `ZeroDivisionError`

**Area:** FORMAL (a semantic divergence between the two engines that no amount of
`double` support can remove without exception machinery). Claim
`project26:float`, found 2026-10-04 on `work/formal26-float` while writing the
`IEEE754` semantics. **NOT FIXED, and not fixable in the float lowering** — it is
recorded because it is a property of the backend's value model that every float
program inherits, and a reader who finds it by running one deserves the
explanation rather than the symptom.

**Measured 2026-10-04 (`work/formal29-3`), because the document's item 2 below is
about the two backends AGREEING and that had never been measured over more than
one divisor: it is.** Ten divisions in one program — `1.0/0.0`, `-1.0/0.0`,
`0.0/0.0`, `1.0/-0.0`, `1.0/1.0e-320` (a denormal), `1.0/1.0e300`,
`1.0e300/1.0`, `1.0e-320/1.0e-320`, `0.0/1.0`, `-0.0/1.0` — build and run on both
architectures and **every answer is byte-identical between them** (`inf`, `-inf`,
`nan`, `-inf`, `inf`, `0.000000`, the 309-digit expansion of 1e300, `1.000000`,
`0.000000`, `-0.000000`), and every one is the IEEE answer CPython's model agrees
with where CPython has an answer at all.

Three things that measurement settles, and none of them is a fix:

* **The divergence is with CPython and ONLY with CPython**, on the four
  zero-divisor cases — so item 2's worry ("a model-level predicate should own
  `bits & 0x7FFFFFFFFFFFFFFF == 0` so the two backends cannot answer differently
  about it") is satisfied by the absence of the test rather than by a predicate:
  there is no zero test in either backend for there to disagree about, and adding
  a shared predicate nobody calls would be dead code with a reassuring name on it.
* **`-0.0` is not a separate case here.** `1.0 / -0.0` answers `-inf` on both
  machines, so the "the divisor's PATTERN is a zero" test item 2 describes has no
  other spelling to keep consistent with on this path.
* **`1.0 // 0.0` and `1.0 % 0.0`** raise in CPython too and are the same class;
  nothing in this backend inspects a divisor for either operator, so the two are
  one row in `FORMAL.md` §6 phase 5's queue rather than two.

## What was run

```
$ python3 -c "print(1.0 / 0.0)"
ZeroDivisionError: float division by zero

$ cat divzero.mojo
def main() -> Int:
    var one = 1.0
    var zero = 0.0
    printf("%f", one / zero)
    return 0

$ ./divzero.arm64 && ./divzero.x86_64
inf
inf
```

Both backends, both machines, and the same answer from each: `+inf`. IEEE-754
says that is the correct result of the OPERATION, and it is what `lib/IEEE754.lean`
proves (`one_over_zero_is_an_infinity`), so the model and the codegen agree with
each other and disagree with CPython.

## Why it is not fixable here

CPython's `float.__truediv__` is a wrapper that inspects the divisor for zero and
raises; there is no division instruction anywhere near it. Matching CPython would
mean a zero test before every float divide and an exit path carrying a message,
and this backend has no exception machinery for a conversion or an arithmetic
operator to raise through — the same absence
`formal/model.py::float_int_conversion_note` names for `int(nan)`.

The three cases, and what each does:

| program | CPython | this backend | which is right |
|---|---|---|---|
| `1.0 / 0.0` | `ZeroDivisionError` | `+inf` | IEEE |
| `-1.0 / 0.0` | `ZeroDivisionError` | `-inf` | IEEE |
| `0.0 / 0.0` | `ZeroDivisionError` | NaN | IEEE |

## What a caller can rely on

- The divisor is not inspected, so a zero divisor reached through a VARIABLE
  behaves the same as a literal one. There is no "folded" case to be surprised
  by, which is a real property: the answer does not depend on whether the
  compiler saw the zero.
- The one place this is observable in the test suite is
  `IEEE754`'s `zero_over_zero_is_a_nan` and `one_over_zero_is_an_infinity`, which
  assert the IEEE answer rather than CPython's, and the `float_compare_matrix`
  case in `test_formal_run.py` — which is a CPython-pair case and therefore has
  to reach `inf` and NaN through `1.0 / 0.0` inside the MOJO text while its
  PYTHON text spells the same values as `float('inf')` and `float('nan')`.
  That asymmetry is the divergence stated in a test rather than hidden in a
  comment, and it is the reason the case's Python half is not a transliteration of
  its Mojo half.

## The exact next step

Not in the float lowering. It is `FORMAL.md` §6 phase 5's "the Mojo runtime, in
Mojo" — an exception path a runtime function can raise through — plus whatever the
bytecode/interpreter tier needs. Two things have to be decided there and neither is
about IEEE:

1. Whether a `ZeroDivisionError` is an exit-with-a-message or a real unwinding.
   Every bounded-container stop on this path is the former
   (`formal/model.py::list_append_overflow_message` and its siblings), and a
   float divide is the same shape of failure.
2. Whether the check is on the DIVISOR only. CPython raises only for a zero
   divisor; `float('inf') / 0.0` is `inf` in CPython too? No — CPython raises for
   any zero float divisor, including `-0.0`. So the test is "the divisor's
   PATTERN is a zero", which on this path is `bits & 0x7FFFFFFFFFFFFFFF == 0`,
   and that expression is the one a `model`-level predicate should own so the two
   backends cannot answer differently about it.