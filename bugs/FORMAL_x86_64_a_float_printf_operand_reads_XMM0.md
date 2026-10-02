# FORMAL_x86_64_a_float_printf_operand_reads_XMM0: `printf("%f", word)` prints a denormal on x86-64

**Status: OPEN. NOT fixed. Found while writing
`formal/hostmods/math.mojo` and its test, 2026-10-02. Not anybody else's
claim: the area is the formal x86-64 backend's register assignment, and the
`sweep5:hostmods-more` claim covers the host modules, not this.**

## What I ran and what I saw

`formal/hostmods/math.mojo` returns the IEEE-754 **bit pattern** of a double
(`pi_bits()` and four others), because a value on this path is one 64-bit word
and `formal/arm64_codegen.py`'s `FloatLiteral` arm truncates `0.5` to the
integer 0. Printing such a word as a double is what a caller does with it, so
`test_formal_math.py` prints each one with `%.17g` and compares the text against
CPython. It agrees on arm64 and it is wrong on x86-64.

```python
$ cat .tmp/w/f1.mojo
def main() -> int:
    var bits = 4614256656552045848          # math.pi as a double
    printf("f=%f\n", bits)
    printf("g=%.17g\n", bits)
    printf("d=%f\n", 9223372036854775807)
    printf("i=%lld\n", 4614256656552045848)
    return 0
```

arm64 — every line right, and `%.17g` is `repr(math.pi)`:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o f1 f1.mojo
$ ./f1
f=3.141593
g=3.1415926535897931
d=nan
i=4614256656552045848
```

x86-64 — the same image, the same word, `%.17g` prints a denormal, and **the
number changes between runs of the same binary**:

```
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o f1x f1.mojo
$ arch -x86_64 ./f1x
f=0.000000
g=6.4810864235206578e-314
d=0.000000
i=4614256656552045848
$ arch -x86_64 ./f1x          # same binary, second run
g=6.4024130938526187e-314
```

`%lld` is right on both, so this is specific to the **floating** conversions.

## Why it happens

The SysV x86-64 ABI passes a `double` in `XMM0` and an integer in `RDI`. arm64
passes both in register number 0 (`d0` and `x0`), which is why arm64 needs
nothing at all here. Nothing on this path moves a word from an integer register
into an SSE register before a variadic call, so on x86-64 `printf` reads whatever
`XMM0` happened to contain — which is why the answer is not stable rather than
merely wrong.

**Annotating the local does not help**, and that is the measurement that says
this is an emitter gap and not a spelling:

```python
var x: Float64 = 4614256656552045848
printf("a=%f\n", x)
```

arm64 prints `a=3.141593`; x86-64 prints `a=0.000000`. So there is no way to
spell around it from Mojo source today.

## What it costs, and who it touches

  * `formal/hostmods/math.mojo`'s five constants. Its docstring says the WORD is
    the portable answer and that printing it is arm64 only, and
    `test_formal_math.py`'s `consts` group compares the printed form on arm64
    only with the reason printed — this is that filing.

  * **`formal/hostmods/time.mojo`, and this one is worse because nothing says
    so.** `time_seconds_bits()`'s docstring asserts that
    `printf("%.6f", bits)` "prints it exactly — measured, and pinned in
    `test_formal_time.py`". It was measured on arm64. `test_formal_time.py` has
    no `--backend` and its `main()` returns 0 early unless
    `platform.machine()` is arm64, so **the x86-64 half of that claim has never
    been run** — which is the same class of hole
    `bugs/FORMAL_x86_64_parity.md` and
    `bugs/FORMAL_x86_64_formal_backend_gaps.md` are about. The claim should be
    read as arm64-only until this is fixed, and `time.mojo` says so at
    `time_seconds_bits`.

  * any future module that represents a double as a word. `math` is the second
    one in the tree and the pattern is now established, so the count will grow.

## The next step, exactly

In `formal/x86_64_codegen.py`, when a call's format string contains a floating
conversion (`%f`, `%e`, `%g`, `%a` and their `l`/`L` length modifiers), emit the
argument as `movq %rax, %xmm0` (and `%xmm1`, … for the second and later floating
operands) before the `call`, instead of leaving it in the integer argument
register. arm64 needs no change, and `%lld`/`%d` must not gain it — the change
belongs in the format-string classification that already exists to decide
whether an operand is a string or a number
(`formal/model.py`'s `comptime_val_kind` is the precedent), not in the argument
loop.

**The test that would close it** is `test_formal_math.py`'s `consts` group with
the arm64-only exclusion deleted — one line in that group — plus the same
addition to `test_formal_time.py` and a `--backend` flag for it. Until the
emitter moves the register, those two deletions are the wrong move: a green
x86-64 run of `test_formal_time.py` on today's tree would be a test that had
never been able to fail.
