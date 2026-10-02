# FORMAL_printf_percent_space_reads_the_vector_count: `printf("50% done")` prints garbage on x86-64 and the right thing on arm64

**Area:** FORMAL (the x86-64 backend's variadic call marshalling).
Found 2026-10-01 on `work/formal3-7` while verifying
`FORMAL_string_literal_escape_is_not_decoded.md`, whose fix I landed in the same
session. **NOT FIXED — it is pre-existing, it is not a consequence of that fix,
and the two architectures disagree.** Filed with the measurement because the
escape work made it visible: a `%` that ARRIVES from an escape reaches a bare
`printf` format, and that is the shape where this bug is observable.

## What was run

```
$ cat .tmp/esc/pf4.mojo
def main(n):
    printf("50% done\n")
    return 0
```

| tree | arm64 | x86-64 |
|---|---|---|
| this one, after the escape fix | `50 done` — **correct** | `50` + `1670113360` + `on e\n` |
| `.tmp/base` (this tree at its parent commit) | `50 done` — correct | `50` + `1670113360` + `on e\n` — **the same digits** |

CPython prints `50% done\n`. The two trees produce byte-identical x86-64
output, so this is not the escape decode; it is simply still there.

The garbage is a DECIMAL INTEGER spliced into the output where the `%` is, so
`50% done` becomes `50` + the number + `on e`. That is `printf` reading a
vararg it was never given: `% ` is a conversion specification in C (a flag
followed by nothing), so printf fetches an argument and prints it as a signed
decimal.

## Why arm64 is right and x86-64 is not

A `%` in a bare `printf`'s format is LIVE — that is the whole point of the
C variadic, and `formal/model.py`'s `VARIADIC_LIBC` records both that a
function is variadic and how many of its arguments are NAMED (`printf` is 1).
arm64 sets AL to the vector-register count before the call; x86-64's System V
ABI has no such register, so there is nothing to set and the disagreement is
not about AL at all.

What differs is what the two backends do about a format string with a
conversion and NO argument for it. Measured shapes:

| source | arm64 | x86-64 |
|---|---|---|
| `printf("plain text\n")` | correct | correct |
| `printf("one %s here\n", "arg")` | correct | correct |
| `printf("[%%]\n")` | `[%]` | `[%]` |
| `printf("50% done\n")` | `50 done` | `50` + garbage + `on e` |
| `printf("\x25\n")` (`%` at end of string) | `\n` | `\n` |

So `%s` with its argument, `%%`, and a `%` as the LAST byte are all fine on
both. The failing shape is a conversion specification with a flag and no
conversion character, mid-string — `% ` is the only one C defines that way
besides `%+`, `%-`, `%#`, `%0`, and `% `.

**The honest reading, and it is a decision rather than a measurement:** the two
architectures disagree about whether a `%` with no argument behind it is a
format error. arm64 printing `50 done` is NOT correct either — CPython's
`printf` is not the oracle here, because this path's `printf` IS libc's, and
libc would consume a vararg for `% `. So arm64 is *lenient* and x86-64 is
*faithful*, and both are defensible. What is NOT defensible is that they
differ, because `bugs/FORMAL_x86_64_parity.md`'s whole subject is that they must
not: "a fix that lands on one machine and not the other is the
two-machines-one-language failure this backend exists to prevent".

So the fix is one of two, and it is a decision:

1. **REFUSE the shape** — a variadic format string with a conversion
   specification and no argument for it. `model.py` already has the place for
   it: a function of the format string and the operand count, asked by BOTH
   backends from the ordinary extern path, so they cannot disagree by
   construction. This is the honest answer in the same shape as
   `string_iteration_refusal`, and it names the construct rather than printing
   a number the source never wrote.
2. **Make x86-64 lenient like arm64** — but "lenient" here means dropping the
   `%` and printing the rest, which is what arm64 appears to be doing and which
   is NOT what libc does. Choosing this makes the two agree by making both
   wrong in the same way, which is worse than option 1 unless there is a reason
   to want it.

**Option 1, and the reason to prefer it:** the whole `printf` surface on this
path is "handed through to libc", so a format string with a conversion and no
argument is a program that reads a register nobody set. That is the
`gimple_runtime_refusal` class of bug — a call that cannot be answered — except
that here the call itself binds fine and only its FORMAT is unusable, so it
wants its own refusal text rather than the library one.

## The exact next step

1. Write the check in `formal/model.py` as a pure function of (format string,
   number of operands), and ask it from both backends on the `printf` /
   `sprintf` / `snprintf` / `fprintf` arm of the variadic path — the same
   discipline `formal/model.py`'s `specialization_call_refusal` states about
   its own table ("asked by both backends precisely so they cannot disagree").
2. Note that `print()` is NOT affected and must not be: `model.print_literal`
   already doubles `%` because a `print` format is BUILT rather than passed
   through, so `print("50% done")` is correct on both architectures today. The
   two spellings are different constructs and a fix that swept them together
   would break the one that works.
3. The escape interaction is the reason to do it now rather than later:
   `FORMAL_string_literal_escape_is_not_decoded.md`'s fix means a `%` can now
   arrive at a bare `printf` format from `\x25`, and the corpus has 468 escaped
   literals in the stdlib. Test with both spellings — `printf("50% done")` and
   `printf("\x25 done")` — so the fix is pinned against the source of the `%`
   as well as its position.
4. Cases belong in `test_formal_run.py` next to the other `printf` shapes, with
   `refuse:` expectations rather than a pinned wrong answer, and on BOTH
   architectures so the agreement is the thing under test.

## What is NOT measured

- Whether arm64's `50 done` is deliberate or an accident of its format-string
  handling. It reads as deliberate — it dropped the `%` rather than consuming a
  vararg — but nothing in `formal/x86_64_codegen.py` or
  `formal/arm64_codegen.py` says so, and I did not read either backend's
  variadic marshalling in full. That is the first thing to establish before
  choosing between options 1 and 2.
- The other flag-only conversions (`%+`, `%-`, `%#`, `%0`). I measured `% `
  because it is the one that appears in prose ("50% done"), not because the
  others behave differently; expect them to be the same shape.
- Any effect on the 468 escaped stdlib literals. A corpus sweep is the
  integrator's, not a light worker's.

## Reproducing

```
python3 tools/memslot.py --gb 8 --label pf4 -- \
    python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/esc/pf4 .tmp/esc/pf4.mojo
./.tmp/esc/pf4 | od -c
# 0000000    5   0       1   6   7   0   1   1   3   3   6   o   n   e   \
```