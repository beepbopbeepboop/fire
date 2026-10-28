# An unannotated parameter receiving disagreeing types still prints wrong for every pair except int/str

## Status 2026-10-02 — the 2 hard GCC errors are GONE and 2 more pairs are
## right; 29 of 36 remain wrong, and they are the three rows below

### Closed: the compile failures, and the `char *` half of the pointer group

A container literal at a call site contributed NO observation to Pass 1.3d's
unanimity contract, so `f(2.5)` + `f([1, 2])` saw `{'double'}` alone and
resolved the slot to `double` — the doc's "sharpest of the three" GCC error.
The same hole on the `char *` side is the pointer group's silent half:
`char * f(char *)` plus a list argument is `mojo_print` strlen'ing the list
HEADER's bytes, which is where this doc's `'\x90\x1a\x93\x04\x01'` row comes
from. `void *` is now recorded for a container literal at a call site
(`mojo/backend_gimple/module_gen.py`, in the walk that already special-cases
an `IntLiteral` there and gives the reason `_arg_scalar_type` must not be
widened), which is the shape that pass's own whitelist
(`len(types) != 1 or not (_has_dbl or _has_cs)`) already rejects — so the slot
drops to the `int64_t` box.

Measured over this doc's whole matrix (36 ORDERED pairs of
`{int, float, str, bytes, list, None}`, `def f(x): print(x)`), through
`driver.compile_program` as the "Suite-bucket note" below requires:

| tree | correct | hard GCC error | wrong value |
|---|---|---|---|
| HEAD | 5 | 2 | 29 |
| after the fix | **7** | **0** | 29 |

Two pairs moved to correct — `str`+`list` and `list`+`str` — and **no pair went
correct-to-wrong**, checked cell by cell over the whole matrix rather than
only on the cells that moved. Note the base is 5/36 here, not this doc's
recorded 7/36: the tree drifted, so 5 is the number a re-measurement on this
branch should be compared against.

**One caution for whoever reads the table.** A pair that prints the raw bytes
of a pointer is a WRONG ANSWER, not a compile failure, and the two are easy to
conflate in a harness: `subprocess.run(..., text=True)` raises
`UnicodeDecodeError` on it. The first version of that matrix counted every
exception as a compile failure and reported "12 GCC errors, 8 remaining" —
all eight of which were `bytes` pairs printing raw bytes. The numbers above
classify `CalledProcessError` (a real gcc failure) separately from everything
else.

### Still open, unchanged: float, None, and the bytes/list tags

Both remaining GCC errors are gone, so the doc's "Start with the 2 GCC errors,
not the 20 silent wrong answers" advice is spent; what is left is the three
rows of "Where", in the order the doc gives them:

1. **float** (7 pairs, largest by user impact). `f(2.5)` + `f(1)` prints `2` —
   the IEEE-754 bits read as an integer. The doc's own analysis stands: what
   is missing is a `mojo_box_new(double)` at the call site that KNOWS the
   argument is a double, so the callee can tell a float from an int that
   shares its bits. `mojo_cstr_or_int_str` cannot do it — it would stringify
   the bit pattern — which is also why the fix above deliberately stops at the
   box.
2. **bytes / list** (the pointer group minus the two pairs just fixed). The
   value survives; what is missing is the runtime tag, and this commit's
   change makes the requirement sharper rather than smaller: the slot is now
   the `int64_t` box for exactly these pairs, so `print` must decide from
   `_tagged_dyn_` / `mojo_is_registered_list` whether the word is a container,
   a boxed string, or a plain int.
3. **None** last, for the reason the doc gives: one bit destroyed at the
   boxing site.

## What I ran

One function, one unannotated parameter, called with every ORDERED PAIR of
`{int, float, str, bytes, list, None}`, printing the parameter, each program
diffed against CPython on the same text. 36 programs; the driver is
`.tmp/` scratch (not committed) — it compiles through
`gimple_codegen._run_pipeline(src, filename=..., do_imports=True)` and runs the
binary.

```
def f(x):
    print(x)

f(2.5)
f([1, 2])
```

## What I see

**7 of 36 correct.** The 7 that pass are exactly the pairs where both
arguments are `int`/`str` — the class the deleted doc's fix covers. The other
29 fall into three groups, and they are three different bugs, not one:

| group | pairs | symptom |
|---|---|---|
| pointer kinds (`bytes` / `list` on either side) | 20 | the value is a pointer in an `int64_t` and is printed as its own address, or as raw bytes |
| scalars (`float` / `None` on either side) | 7 | `2.5` prints `2` (the IEEE-754 bit pattern read as an integer); `None` prints `0` |
| `float` + `list` | 2 | **hard GCC error, no binary at all** |

The GCC error is the sharpest of the three and the cheapest to look at:

```
prog.py: In function '_toplevel':
prog.py:6:3: error: pointer value used where a floating-point was expected
    6 | f([1, 2])
```

A `double` parameter and a `list` argument in the same program, so the
unanimity contract resolved the slot to `double` and the list's pointer was
passed to a `double` formal. Where the int64_t default survives, the same
mismatch is silent instead of fatal: `f(2.5)` prints `2`.

### Examples

| pair | compiled | CPython |
|---|---|---|
| `2.5`, `[1, 2]` | GCC error, no binary | `2.5` / `[1, 2]` |
| `2.5`, `1` | `2` / `1` | `2.5` / `1` |
| `1`, `None` | `1` / `0` | `1` / `None` |
| `1`, `[1, 2]` | `1` / `4310604192` | `1` / `[1, 2]` |
| `"s"`, `b"b"` | `s` / `\x90\x1a\x93\x04\x01` | `s` / `b'b'` |
| `[1, 2]`, `[1, 2]` | `4349122880` / `4349122944` | `[1, 2]` / `[1, 2]` |

## Not a regression

The fix for the deleted doc took the same 36-program sweep from **5/36 to
7/36**: the two gained pairs are `int|str` and `str|int`, and **zero pairs
went from correct to incorrect**. Both runs are reproducible by reverting that
commit's diff and re-running; the comparison is over the whole matrix, not just
the two that moved.

That matters because this doc's obvious first move — "widen the runtime
discriminator" — is exactly what would turn a correct case into a wrong one.
See "The precision requirement" below.

## Where

The mechanism is unchanged from the deleted doc: a parameter with no
annotation gets ONE C type for the whole program, decided by Pass 1.3d's
unanimity contract over observed call sites
(`mojo/backend_gimple/module_gen.py`), and an `int64_t` when that contract has
nothing to say. The fix added exactly one thing on top —
`mojo_cstr_or_int_str`, applied only to a slot that provably may hold a string
(`gen._int64_may_hold_str` / `gen._ret_may_hold_str`, consumed by
`emit_infra._is_may_hold_str_param`).

So the three groups above are three different missing pieces of the same idea,
and only the first is str-related:

1. **float.** Needs boxing. The doc that preceded this one already named the
   machinery: `mojo_is_boxed` / `mojo_box_double` / `mojo_repr_boxed` exist
   for "an int64_t that may be a float", and what is missing is a
   `mojo_box_new(double)` at the call site that KNOWS the argument is a
   `double`, so the callee can tell a float from an int that happens to share
   its bits. `mojo_cstr_or_int_str` cannot do this — it would stringify the
   bit pattern.
2. **None.** `None` is boxed as the integer `0`, and `0` is also a legitimate
   `int`, so this is genuinely ambiguous at the `int64_t` level and needs the
   same boxing treatment as float, in the other direction.
3. **bytes / list.** These ARE pointers, so the value survives; what is
   missing is the runtime tag that says which kind. This is the `_tagged_dyn_`
   machinery `_gen_print` already consults for a dynamically-tagged
   container element — the same shape, applied to a parameter instead of a
   heterogeneous list slot.

## The precision requirement — why this is not one discriminator

`mojo_cstr_or_int_str` decides with `mojo_boxed_is_str`, which is
range-shaped. It is exact for a small integer and for a real pointer, and
wrong for a bare integer in `[2^31, 2^47)`. That is tolerable today only
because the set it is applied to is narrow by construction: a slot is in it
only if a `char *` was really observed at one of its call sites.

Generalizing it to "any polymorphic parameter" would make it apply to slots
with no such evidence, and `print(2**40)` — a perfectly ordinary program with
no polymorphism at all — would hand a bare integer to `strlen`. So each of the
three groups needs its own discriminator with its own evidence rule, not a
wider version of this one. A single "is this int64_t one of several things?"
predicate is the tempting design here and it is the wrong one: it has to be
sound for a value the codegen knows nothing about, and the codegen knows
nothing about most of them.

## Next step

1. Start with the 2 GCC errors, not the 20 silent wrong answers: a compile
   failure is a much smaller blast radius and the same shape of work. The
   question is whether Pass 1.3d's `double` resolution should be reachable at
   all when any observed argument is a pointer — `_arg_struct_ptr_type`
   already collects those observations and they currently meet only in the
   separate struct-pointer contract.
2. Then float, which is the largest group by user impact (arithmetic through a
   helper is far more common than `print`ing a bytes value) and has the
   machinery already written.
3. `None` last: it is one bit of information that is currently destroyed at
   the boxing site, so find where `None` becomes `0` and whether a distinct
   sentinel is available.

## Suite-bucket note

`test_link_mode.py` is registered as `linkmode` in both `check` and `gate`
(confirmed with `python3 tools/suite.py --list`). Its
`test_unannotated_param_with_disagreeing_call_sites` is the harness the deleted
doc's fix added; extending THAT case's matrix to all 36 pairs is the natural
home for this doc's regression test, and it would go green one pair at a time.

Note for whoever does that: the sweep must go through `driver.compile_program`,
not `test_gimple_runner.py`'s `compile_to_gimple`. The latter is the
single-translation-unit path, where the whole-program call-site walk never
runs and none of these pairs fail — a test written there passes before and
after and measures nothing.
