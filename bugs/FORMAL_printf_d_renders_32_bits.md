# `printf("%d", x)` renders 32 bits, so every integer above 2^31 prints wrong

**Status: open. Not mine — found while measuring integer semantics
(`project33:int-semantics`), filed because the measurement that found it is
reproducible in one command and the answer is a silent wrong number.**

## What I ran

`fire.py build --formal` of one program and executing the image, arm64:

    def main(n):
        a = 4611686018427387904            # 2**62
        printf("A=%d|", a)
        printf("B=%lld|", a)
        printf("C=%ld|", a)
        printf("D=%u|", a)
        print(a)
        printf("E=%d %d|", 3000000000, 0 - 3000000000)
        printf("F=%d|", 5000000000)
        return 0

`python3 .tmp/intsem/pfmt.py` in `work/formal33-int-semantics` builds and runs
it. Output:

    A=0|B=4611686018427387904|C=4611686018427387904|D=0|4611686018427387904
    E=-1294967296 1294967296|F=705032704|

## What I expected

`A` through `F` all the 64-bit value. `%d`, `%u`, `%lld` and `%ld` are all
spellings a program writes to print an `Int`, and `Int` is `int64_t`
(`doc/ABI.md`, "Scalar types"). CPython's `print(2**62)` is
`4611686018427387904`.

## What I saw

`%lld`, `%ld` and `print` are **right**. `%d` and `%u` are wrong by exactly the
low 32 bits:

| printed | wanted | low 32 bits, read as `int` |
|---|---|---|
| `A=0` | `4611686018427387904` | 0 |
| `E=-1294967296` | `3000000000` | -1294967296 |
| `F=705032704` | `5000000000` | 705032704 |
| `D=0` (`%u`) | `4611686018427387904` | 0 |

This is C's own rule, not a bug in the lowering of the *argument*: the emitter
passes the whole 64-bit register and libc's `%d` reads an `int`. `asm` on the
image confirms the value reaches the call intact:

    0x100000428  mov  w0, #0x0
    0x10000042c  movk x0, #0x0, lsl #16
    0x100000430  movk x0, #0x0, lsl #32
    0x100000434  movk x0, #0x4000, lsl #48      ; X0 = 2**62
    0x100000440  add  x1, x0, #0x0              ; X1 = the argument
    0x100000450  bl   printf

So the fix is not "pass a wider value" — it is that **`%d` is the wrong format
for a 64-bit `Int` on this target and the model has to say so.** Two directions,
and the second is the one this codebase prefers elsewhere:

1. **Rewrite the conversion.** The model already READS the format string
   (`printf_text_conversion_refusal`, `printf_kind_conversion_refusal`,
   `printf_missing_operand_refusal` all take `fmt_text`), so
   `printf("%d", x)` could be lowered with a synthesised `%lld` and the
   interned label rewritten to match. That makes `%d` print what CPython prints
   and keeps every existing program byte-identical in its OUTPUT.
2. **Refuse it by name.** `%d` on an `Int` is a C-UB spelling on a 64-bit
   target, and this path refuses what it cannot answer
   (`int_parse_base_refusal`, `float_binary_refusal`, the `%s`-of-a-number case
   below). This is smaller and it cannot be wrong, but it turns working
   programs into build failures, and `%d` is what a large amount of ordinary
   Mojo spells.

Whichever is chosen, `formal/model.py`'s claim has to change with it. As
written it is false, and it is false in a sentence that reads as a survey of
the whole conversion set:

> Every other conversion reads the word it is handed and renders it: `%d`,
> `%lld`, `%llu`, `%u`, `%c`, `%f`, and `%p` on Darwin

(the `%s` section, immediately above `formal/model.py:7885`).

## Why it matters more than a formatting nit

It is invisible to every differential test that compares **exit status** and
invisible to any program whose integers happen to fit in 32 bits — which is
most of them, because loop counters and lengths are small. So a corpus that
grows one large integer (`1 << 40`, a nanosecond timestamp, `2**31`) starts
reporting wrong numbers with exit 0 on both architectures, and the two
architectures agree on the wrong number, which is what makes it survive.

**This is also why `test_formal_int_semantics.py` prints with `print` and not
`printf("%d", …)`**: reading a 64-bit answer through `%d` would have measured
this bug instead of the arithmetic.

## Next step

1. Decide direction 1 or 2 above, in `formal/model.py`, next to the `%s`
   section — one function both backends ask, for the reason the rest of this
   module exists.
2. A test that prints `2**62`, `2**31`, `2**31 - 1`, `-2**31`, `5000000000`
   and `2**40` through `%d`, `%u`, `%lld` and `print`, on both backends, with
   CPython's own `print(x)` as the oracle.
