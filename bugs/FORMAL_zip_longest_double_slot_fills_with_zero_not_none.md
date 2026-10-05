# zip_longest: a padded `double` slot fills with `0.0` where CPython fills with `None`

**Area:** CODEGEN (`mojo/backend_gimple/emit_loops.py`,
`_gen_for_zip_longest`). Found 2026-10-04 while fixing
`bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md` (fixed and
deleted), whose regression program for this family has to leave this out.

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
    compiled  1 p / 2 -        1.5 q / 2.5 0.0

The first loop is right, and it is right for the reason the design intends: the
slot is declared `char *` and the `str` fill lands in it. The second loop's
first row is right too (`1.5`, not `1`) — that is the loop-target-type fix this
was found beside. Only the PADDED row is wrong, and only for a `double` slot.

## Mechanism

`_gen_for_zip_longest` builds the fill as a C expression per slot:

```python
if suf == 'double':
    ...
    fills.append(fv)            # or "(double)0" when no fillvalue
```

so the default fill for a float sequence is `(double)0`, and the select is
`in_range ? raw : fill` on a `double`. There is no NULL to test against in a
`double`, so the model's 0-is-None scalar prints as `0.0`. The `str` and `int`
arms both have a NULL/0-shaped sentinel that prints as nothing or as `0`, which
is why only the float arm shows it.

This is the documented consequence of the same decision the function's own
docstring records — "The default fill is 0 — this scalar C model's
representation of None — so the common `if x is None:` guards after a padded
iteration test a genuine 0/NULL" — applied to the one domain where 0 is a
value rather than an absence. It is a narrower and much smaller thing than the
loop-target-type bug it was found beside, and it is left alone here because the
honest fix is a real one and not a tweak: a padded slot has to be able to hold
"absent" as distinct from `0.0`.

## Two adjacent narrowings, measured in the same session, so nobody
rediscovers them as if they were this bug

* A `fillvalue` is coerced PER SLOT here, where CPython hands every slot the
  value as given: `zip_longest([1.5, 2.5], [7], fillvalue=0.0)` prints
  `2.5 0` here and `2.5 0.0` in CPython, because slot `b` is an `int64_t`.
* A CROSS-DOMAIN fill is refused rather than emitted: a `str` fillvalue into a
  `float` sequence raises `fillvalue must be float-typed to fill a float
  sequence` and the loop falls back to the generic path. The fallback is the
  pre-existing one and drops the loop, so such a program prints nothing (a
  silent wrong answer, not an error) — measured with
  `zip_longest([1.5, 2.5], ["q"], fillvalue="-")`, which printed only the first
  loop's two lines.

## Exact next step

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

Either way the acceptance test is that program above, compared against CPython,
and the two adjacent narrowings should be decided in the same pass: per-slot
fill coercion is a one-line change (`fills` already carries the slot's own
read expression's type), while the cross-domain refusal's silent fallback is
worth checking against the generic path before it is called a refusal.