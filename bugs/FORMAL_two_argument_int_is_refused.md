# FORMAL: `int(s, base)` is refused as a conversion with two operands, and it is answerable

**Area:** FORMAL (`formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, and
the `formal/model.py` table both of them should be reading). **Status: OPEN —
a refusal where the answer exists, found by the `sweep:repo-b` slice of the
formal sweep on `mlir.py`. NOT FIXED HERE, and the reason it is filed rather
than fixed is measured, not a matter of taste: see §5.**

## What I ran

The slice sweep classified `mlir.py` as the slice's only in-file `codegen`
finding, and the terminal construct is `member.strip()` — so I patched a COPY of
the file one construct at a time to find what is behind it. That is what turned
this up, at `mlir.py:282` and `mlir.py:289`:

```
$ python3 .tmp/probe.py .tmp/mlir_probe.py     # strip + slice already patched out
RAISED: FormalBuildError int(...) takes exactly one value to convert on this
        path (got 2 argument(s))
```

and, on its own, as a two-line reproducer (`mlir.py`'s own call sites are
`int(inner, 0)` and `int(head, 0)`):

```mojo
def f(s: String) -> Int:
    return int(s, 0)
def main(n: Int) -> Int:
    printf("%d", f("41"))
    return 0
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64  -o out .tmp/p_int2.mojo
build: int(...) takes exactly one value to convert on this path (got 2 argument(s))
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o out .tmp/p_int2.mojo
build: int(...) takes exactly one value to convert on this path (got 2 argument(s))
```

— the same refusal on both architectures, which is what a shared `model.py`
decision would make structural rather than coincidental (see the next step).

## What I expect

`41`. CPython's `int("41", 0)` is 41; so is `int("41")`. Base 0 means *detect
the base from the prefix* — `0x`/`0X`, `0o`/`0O`, `0b`/`0B`, otherwise decimal
— and `int(s, 16)` / `int(s, 2)` mean the base is stated.

## What it does instead

Both backends refuse it, identically, from the arity arm of the conversion
emitter:

`formal/arm64_codegen.py:5533` (and the same shape at
`formal/x86_64_codegen.py:6265`):

```python
operands = list(e.args) + [v for _n, v in e.kwargs]
...
if len(operands) != 1:
    raise CodegenError(
        f"{name}(...) takes exactly one value to convert on this path "
        f"(got {len(operands)} argument(s))")
```

That arm is **correct about what it was written for** — a conversion takes one
operand, and its own comment says so ("a conversion has one operand, and two of
them (positioned or named) is not a conversion"). What it does not distinguish is
a conversion from a **parse**, and `int(s, base)` is a parse: the second operand
is not a second value to convert, it is a parameter of the same operation. The
refusal is therefore a *category* error rather than a wrong answer, which is why
it is worth filing at all: nothing about it is unsound, it just refuses a
construct the language has and the target can express.

## Why this is not a representation problem

Unlike `strip` (a shorter string needs a write over bytes in a read+execute
segment) and `split` (a sequence of strings is a frame blob with a
compile-time capacity bound), `int(s, base)` needs **no new storage and no new
value**: the answer is a machine word, which is what a formal value already is.
The whole of the lowering is `strtoll(s, NULL, base)` for a stated base and
`strtoll(s, NULL, 0)` for base 0 — libc, already on the link line, already used
by both backends for `strlen` and `strncmp` (`bugs/FORMAL_string_value_model.md`
measures that position). The validation is the part that must not be skipped:
`strtoll` returns 0 and sets `errno = EINVAL` on a non-numeric string where
CPython raises `ValueError`, so the refusal is not "raise instead of answer" but
"**refuse** the strings `strtoll` would silently accept as 0, and say so by
name" — the same shape `formal/model.py`'s other conversion refusals take.

## The next step

1. **Put the decision in `formal/model.py` first, not in the two backends.** Both
   backends carry this refusal as two copies of the same arm, and the reason is
   visible in the surrounding code: the emitter that owns it is per-backend, but
   the question "is `int(s, b)` a parse or a conversion" is arch-free, and every
   arch-free string decision on this path already has one home
   (`model.string_comparison_lowering`, `model.truthy_lowering`). A
   `model.int_parse_lowering(call)` returning `("refuse", reason)` /
   `("lower", base)` is the shape, and it is what makes the two architectures
   unable to come apart on it.
2. **Two arms, not one.** `int(s)` is already lowered (it is the one-operand
   case) and must stay exactly as it is — it is covered by existing cases. The
   new arm is `len(operands) == 2` with an integer-or-zero second operand, and
   anything else (`int(s, x)` where `x` is not a compile-time constant) is a
   refusal that says so, because a base computed at run time is a different
   question from a stated one.
3. **A test beside the other conversion refusals**, in `test_formal_run.py`'s
   `refuse:` idiom, with **both** directions: `int("41", 0)` and `int("0x29",
   0)` answering, and `int("4x1", 0)` refused by name rather than answered 0.

## Why it was not fixed here — the marginal effect is measured, and it is 0

The honest reason, and it is the same reasoning `FORMAL_sweep_work_map_2026-10-01_b3.md`
applied to its 93-file row: **a file's terminal cause is the first refusal the
walk reaches, so the value of lifting one construct is the number of files that
reach it.**

`mlir.py` is **four constructs deep**, measured by patching a copy one at a time
and re-running the compile:

| # | construct | state |
|---|---|---|
| 1 | `s.strip()` (`mlir.py:38`) | refused; `FORMAL_string_value_model.md`, claimed |
| 2 | `m[1:-1]` (`mlir.py:43`) | refused; same doc, wave 6 §3 |
| 3 | `int(head, 0)` (`mlir.py:282,289`) | **this doc** |
| 4 | `text.split(':', 1)` (`mlir.py:287`) | refused; a sequence of strings |

Lifting row 3 alone leaves rows 1, 2 and 4, so **`mlir.py` still does not
build** and this slice's coverage does not move. It is also the only one of the
four with no doc, which is precisely why "it has no doc" is not a reason to pick
it up: within this slice its undocumentedness buys 0 files.

It is filed because it is real, it is unowned, and it is a construct other
slices will meet — `mlir.py` is just the first repo file that spells it. A
worker with a slice whose files are only one construct deep would find it worth
landing immediately.