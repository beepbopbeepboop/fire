# An unannotated parameter receiving disagreeing types still prints wrong for every pair except int/str

**State: OPEN, measured, not fixed.** This is the remainder of
`bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md` (deleted by
its fix), which covered the vacuous-unanimity SIGSEGV. That defect is fixed and
this is not a regression from it — see "Not a regression" below, which is the
first thing to establish before working on this.

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
