# zip_longest: a padded `double` slot fills with `0.0` where CPython fills with `None`

**Area:** CODEGEN (`mojo/backend_gimple/emit_loops.py`,
`_gen_for_zip_longest`). Found 2026-10-04 while fixing
`bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md` (fixed and
deleted), whose regression program for this family has to leave this out.

**Status 2026-10-05 (`work/formal35-6`): direction 2 of the "exact next step"
below has LANDED — the padded `double` slot and every cross-type `fillvalue`
are REFUSALS that reach the build, both adjacent narrowings are decided, and
the `fillvalue` is evaluated once instead of once per slot. What remains is
the value-model work direction 1 asks for, and it is named exactly.**

## What landed, and what it changed

The doc's own program, on `master` and on this branch:

```
$ python3 tools/memslot.py --gb 8 --label zl -- python3 fire.py build -o .tmp/zl .tmp/zl.mojo
```

| program | master | this branch | CPython |
|---|---|---|---|
| `zip_longest([1.5], ["q", "r"])` — a padded `double` slot | `1.5 q` / **`0.0 r`** | **refused**, naming the domain | `1.5 q` / `None r` |
| `zip_longest([1], ["p", "q"], fillvalue="-")` — a `char *` fill in an `int64_t` slot | `1 p` / **`4364407504 q`** (the pointer's own decimal) | **refused**, naming both types | `1 p` / `- q` |
| `zip_longest([1, 2], [3], fillvalue=0.0)` — a `double` fill in an `int64_t` slot | `1 3` / **`2 0`** | **refused**, naming both types | `1 3` / `2 0.0` |
| `zip_longest([1.5, 2.5], ["q", "r"], fillvalue="-")` | **did not build** (`cannot convert to a pointer type`) | builds, CPython's answer | `1.5 q` / `2.5 r` |
| `zip_longest([1.5], ["q", "r"], fillvalue=9.0)` | **did not build** (`mojo_unsupported_iter`, loop ran zero times) | `1.5 q` / `9.0 r` | same |
| `zip_longest([1, 2], ["p"], fillvalue="-")` — the fill cannot reach the int slot | `1 p` / `2 -` | `1 p` / `2 -` | same |
| `zip_longest([1, 2], [3, 4], fillvalue=f())`, `f` counting its calls | `fill calls = 2` | `fill calls = 1` | `fill calls = 1` |

Four of those seven were wrong answers or hard build failures on `master` and
are CPython's answers or a diagnosed refusal here; the last two are the rows
that keep the refusal from costing correct code.

**The three pieces.**

1. **A padded `double` slot is refused** (`ZipLongestFillRefusal`,
   `mojo/middle/loops_shared.py`, because two modules have to agree about it).
   This is direction 2 of the original "exact next step" — *"refuse the shape,
   with a message naming the domain"* — and the direction is chosen for the
   reason the doc itself gives: direction 1 is a value-model change, not a
   tweak, and a half-model is worse than none.
2. **A `fillvalue` is admitted only into a slot whose own read type it
   matches**, in all three directions. The `str`-into-`float` direction was
   already a refusal and is now the same class of decision as the other two,
   with one shared message builder. The doc's "per-slot fill coercion is a
   one-line change" is superseded by this: the coercion was never the bug, the
   missing `kind` was, and admitting a float into an `int64_t` slot is the
   same wrong answer as admitting a pointer.
3. **A fill the loop can never select is not the question.**
   `_zip_longest_reaches` compares the two lengths when both sequences are
   list literals (`max(len) > len(slot)` is the padding condition) and answers
   "may be padded" when either length is a run-time value — including for a
   `*seq` element, whose length `len([1, *xs])` this cannot count and whose
   under-count would decide a refusal NOT to fire, which is the silent
   direction. Without it the doc's own first program, which is correct today,
   would be refused for a fill it never uses. This is also what makes the
   `char *` slot in `zip_longest([1.5], ["q", "r"], fillvalue=9.0)` stop
   naming the fillvalue: an unreachable slot's expression still has to
   COMPILE, and `(int64_t)(char *)(9.0)` is `cannot convert to a pointer type`
   rather than dead code.

**And the doc's "the cross-domain refusal's silent fallback is worth checking
against the generic path before it is called a refusal": checked, and it was
not one.** `_gen_stmt_ForStmt` caught every exception out of
`_gen_for_zip_longest`, rolled back and fell through to `_gen_for_iter`, which
drops the loop and emits `mojo_unsupported_iter` — the program prints nothing
and exits 0. So the pre-existing `fillvalue must be float-typed to fill a
float sequence` refusal was, as the doc suspected, not a refusal at all. The
`zip_longest` arm now re-raises `ZipLongestFillRefusal` and still falls back
for every other exception, because this one class is a decision and the rest
are gaps in the narrowing.

**Bonus, and it is the doc's "per-slot" paragraph from the other side:** the
`fillvalue` was lowered inside the per-slot loop, so `gen.lower_expr(fill_node)`
ran once per slot. A fillvalue with a side effect therefore ran twice. It is
lowered once now, before the loop — which is also where a loop-invariant value
belongs.

**Pinned by seven rows in `test_gimple_runner.py`** (four builds-and-runs
against CPython, three generation refusals), through a new
`test_gimple_build_refusal` helper: this file had no way to assert that the
EMITTER refuses rather than gcc, and every helper in it compiled first.
Measured on the pre-change tree, six of the seven fail there and the seventh —
the row that must keep building — passes on both.

## What is NOT fixed, and it is one thing

**A `double` that can be absent.** The refusal above is correct and it is not
the fix the doc originally wanted; it converts a silent wrong answer into a
diagnosed one at the cost of refusing correct code
(`zip_longest([1.5], ["q", "r"])` is correct CPython). Landing it means:

1. a way for a loop target to carry "absent" — the per-slot kind byte is the
   precedent (`mojo_list_set_kinds`' `MOJO_KIND_NONE`, which
   `TypeLattice.slot_kind_byte` already names, and which `_DictSlot.kind`
   already uses on the dict side), and a `double` local would have to carry
   that kind beside its value;
2. `mojo_repr_float` and every per-slot reader and sorter on the float arm
   taught the kind, so a padded row prints `None` and a real `0.0` does not.

That is the value-model project several queue docs already name, not this
function's.

**And a divergence this doc records but does not claim to fix:** a padded
INTEGER slot still reads `0` where CPython reads `None`
(`zip_longest([1], ["p", "q"])` → `1 p` / `0 q`). It is the same class as the
float arm and it is wrong for the same reason — an `int64_t` has no absent
word — but it is this model's long-documented 0-is-None convention, and the
docstring above now says so in the place a reader of the lowering will find it.
Changing it is item 1 and 2 above with `int64_t` substituted, so it belongs to
the same piece of work rather than to a second decision here.

## The doc's own program still differs from CPython, for a reason that is not
## in this file

```
CPython    1 p / 2 -        1.5 q / 2.5 None
master     1 p / 2 -        1 q   / 2   None
this tree  1 p / 2 -        1 q   / 2   None      (unchanged, and now diagnosed)
```

The second loop's `1` is **not** this doc's defect and the sentence below it
was measured on a branch that had a fix `master` does not have:
`_declare_var` is first-decl-wins, so the FIRST loop's `a: int64_t` and
`b: char *` survive into the second, whose own slots are a `double` and a
`char *`, and the `double` read is stored into the `int64_t` declaration. That
is `bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md`, whose fix was
landed and WITHDRAWN the same day because it breaks the self-host closure
(`gen_module_impl`'s `sd` is the target of two loops and the declaration a
rebind makes is load-bearing for a later read of the same name). So this doc's
stated acceptance test cannot pass until that one lands, and this branch leaves
that row exactly as it found it.

## What I ran

```
def main():
    import itertools
    for a, b in itertools.zip_longest([1, 2], ["p"], fillvalue="-"):
        print(a, b)
    for a, b in itertools.zip_longest([1.5, 2.5], ["q"]):
        print(a, b)
main()
```

    CPython   1 p / 2 -        1.5 q / 2.5 None
    compiled  1 p / 2 -        1 q   / 2   None

The first loop is right, and it is right for the reason the design intends: the
slot is declared `char *` and the `str` fill lands in it. The second loop's
first row is NOT right, and the paragraph above says which doc owns it. Only
the PADDED row was this doc's, and the program does not reach it: `zip_longest`
iterates `max(len)` times and slot `b` is the short one, so the padding lands
on a `char *` — which is why the `double` row above needed a program of its
own, `zip_longest([1.5], ["q", "r"])`.

## Mechanism

`_gen_for_zip_longest` builds the fill as a C expression per slot:

```python
if suf == 'double':
    ...
    fills.append(fv)            # or "(double)0" when no fillvalue
```

so the default fill for a float sequence was `(double)0`, and the select is
`in_range ? raw : fill` on a `double`. There is no NULL to test against in a
`double`, so the model's 0-is-None scalar printed as `0.0`. The `str` and `int`
arms both have a NULL/0-shaped sentinel that prints as nothing or as `0`, which
is why only the float arm showed it.

## Two adjacent narrowings, decided

* A `fillvalue` is coerced PER SLOT here, where CPython hands every slot the
  value as given: `zip_longest([1.5, 2.5], [7], fillvalue=0.0)` printed `2.5 0`
  here and `2.5 0.0` in CPython, because slot `b` is an `int64_t`. **DECIDED:
  it is a refusal**, with the pointer-decimal case and the message above, and
  the coercion survives only where the fill cannot reach the slot.
* A CROSS-DOMAIN fill is refused rather than emitted: a `str` fillvalue into a
  `float` sequence used to raise `fillvalue must be float-typed to fill a float
  sequence` and the loop fell back to the generic path, so such a program
  printed nothing — a silent wrong answer, not an error. **DECIDED: the refusal
  reaches the build** (`ZipLongestFillRefusal` is re-raised), and it is now one
  class with the other five.

## Original next step, kept for the record

Give a padded slot a way to be absent that a `double` can carry. Two shapes,
both real work:

1. a per-slot `_Bool` "was this index in range" flag the lowering already
   computes (`in_t = idx_t < len_ts[si]`) and then throws away, combined with a
   boxed-value convention for the float arm only — the `kind` tag machinery
   `mojo_dict_set_bool`/`_DictSlot.kind` uses is the precedent, and the emitted
   `<loop body is only entered when in range>` structure is already there;
2. or refuse the shape: make a `double` sequence with a default (absent) fill a
   documented refusal with a message naming the domain, which converts a silent
   wrong answer into a correct one at the cost of refusing correct code — the
   trade `bugs/CODEGEN_imported_callable_default_answers_zero.md` argues about
   for the same reason.

**Shape 2 is what landed; shape 1 is what is left**, and the Status section
above says what shape 1 costs in the two places it has to be done.
