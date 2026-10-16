# `Int(<a double too large for Int64>)` saturates in OPPOSITE directions on the two backends, and CPython raises

**Area:** FORMAL, both backends — `formal/model.py`'s
`float_conversion_lowering` `FLOAT_TO_INT` arm and the two emitters' float→int
instruction choice. **Status: NOT FIXED.** Found 2026-10-05 on `work/formal42-3`
while landing the `Pointer[Float64]` load (`model.pointee_kind`), which made a
`Float64` reachable from an expression where the model can classify it. **It is
pre-existing and reachable today with no pointer at all**, and the measurement
below is one line of source.

## What I ran, what I saw, what I expected

```console
$ cat .tmp/fp8.mojo
def main(n: Int) -> Int:
    var x = 1e300
    printf("i=%d\n", Int(x))
    var y = -1e300
    printf("j=%d\n", Int(y))
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o fp8.arm64 fp8.mojo
Built: fp8.arm64  [arm64/macho]
$ ./fp8.arm64
i=9223372036854775807
j=-9223372036854775808
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o fp8.x86_64 fp8.mojo
$ ./fp8.x86_64
i=-9223372036854775808
j=-9223372036854775808
```

CPython, on the same values:

```console
$ python3 -c "print(int(1e300))"
OverflowError: int too large to convert to integer
```

**The two machines disagree with EACH OTHER, which is the part this repository
treats as unforgivable.** For `Int(1e300)` arm64 answers `9223372036854775807`
and x86-64 answers `-9223372036854775808` — the two saturation values, one each.
That is not one wrong answer reached two ways; it is a program whose two
architectures are two different programs, and `test_formal_run.py`'s two-sided
assertions exist because both directions of this have happened before.

Both are SATURATION rather than a wrong arithmetic result: each machine's
conversion instruction clamps an out-of-range value to the largest representable
integer of the target type, and the two ABIs' clamping endpoints are
`INT64_MAX` and `INT64_MIN` respectively. `arm64` uses `FCVTZS Xd, Xn`
(`formal/arm64.py::encode_fcvtzs_xn_dn`) and x86-64 uses `CVTTSD2SI r64, xmm`
(`formal/x86_64_codegen.py`'s float→int arm), and the clamp is the hardware's,
not this path's.

The reachable set is wider than an explicit literal. `Int(x)` where `x` is a
`Float64` **parameter**, a field, a subscript, or now a `Pointer[Float64]` load
(`p.value()` — measured: `Int(p.value())` over a `Float64` whose eight bytes are
`"ABCDEFGH"` prints `9223372036854775807` on arm64 and `-9223372036854775808` on
x86-64, where CPython's `int()` of that double raises `OverflowError` too). So
every program this path accepts with a float in it has a boundary where the two
architectures part company, and a program that compares the result against
anything takes a different branch on each.

## Why it is a refusal rather than a clamp to fix

Three answers are possible and only one of them is a decision this repository
should make silently:

1. **MATCH CPython — raise.** `int(1e300)` is an `OverflowError`, so the
   program's own next line is not reached. This is the same shape as
   `int_parse_trap_message`, which already exists for a C-library conversion
   that cannot signal (`model.py`'s "A `strtoll` returns 0 for a string with no
   digits in it where CPython raises `ValueError` — so the emitters pass an
   `endptr` and stop the program when it is not at the end"). **A trap is the
   honest answer** and it is the one the doc's own argument points at: the
   hardware's saturation is not an answer, it is the absence of one.
2. **PIN ONE SATURATION.** Emit a compare-and-saturate sequence of this path's
   own on both backends so the answer is at least the same everywhere. This makes
   the two machines agree on a number CPython does not produce, which is a
   smaller sin than a divergence but still a wrong answer, and it invents an ABI
   decision nobody asked for.
3. **LEAVE IT.** What the tree does today, with the divergence as the price.

## The exact next step

**One refusal in `formal/model.py`, asked where the conversion is decided, and
one status already in the file.** `SHIFT_TRAP_STATUS` exists for exactly this
shape — `model.INT_OVERFLOW_TRAP_STATUS` IS `SHIFT_TRAP_STATUS`, "this program
could not be answered on this target" is one answer on this path, not one per
check — and `int_parse_trap_message` is the established wording for a
conversion the target cannot signal. So the work is:

  * a predicate over the VALUE being converted, asked at
    `float_conversion_lowering`'s `FLOAT_TO_INT` arm, whose answer is "this
    double does not fit in an `Int64`" — and it is decidable, because the
    operand is very often a literal and the general case is a range test the
    emitters already have the registers for (`FCMP` against 2^63, or
    `2^63 - 1.5` for the truncation-toward-zero boundary, which is the subtle
    half: `Int(2^63 - 0.5)` is in range and `Int(2^63 - 0.4)` is not);
  * the trap sequence on both backends, `raw_syscall` `write` + `exit` as
    `formal/arm64_codegen.py`'s `_emit_overflow_diagnostic` already spells it —
    **and the `fflush` before the `svc` is load-bearing**, because
    `arm64_step` models `svc` as a NO-OP (`work_step_svc`) and a trap without the
    flush would let the universal theorem go on to assert a terminal property
    about a program that has already stopped, which is a false theorem rather
    than a missing one. `bugs/FORMAL_integer_overflow_at_run_time_is_still_
    untrapped.md` §"What NOT to do" states this and it applies here unchanged;
  * rows in `test_formal_run.py`'s `FLOAT_CASES`, one per direction, on both
    backends — a `refuse:` row is the assertion for the trap, and a
    `refuse_without:` row is what stops the two saturation values from coming
    back as an answer.

**The boundary is `|x| >= 2^63` after truncation, and the arithmetic is worth
getting right before any of it lands**: `int()` truncates toward zero, so
`2^63 - 1.5` converts and `2^63 - 1.4` does not, and an implementation that
tests the double against `2^63` without the half-step refuses programs CPython
accepts. `IEEE754.ToIntBits` in `lib/IEEE754.lean` is the specification this
library already states for exactly this question, and `bugs/FORMAL_float_step_
functions.md` §2 is what would arm it in the machine model.

## Tests that will catch a regression in the meantime

`test_formal_run.py`'s `FLOAT_CASES` has no out-of-range row, which is why this
has been invisible: every float in that table is in range. The reproducer above
is two lines and both architectures, and it is worth a row whatever the verdict
is — a divergence measured on both is exactly what that suite is for.