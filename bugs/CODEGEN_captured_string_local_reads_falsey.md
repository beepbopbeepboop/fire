# CODEGEN: a captured `char *` local reads as falsey inside the closure body

## Status (2026-09-30 — OPEN, confirmed at HEAD; NOT fixed, NOT a regression)

A string local captured by a lifted closure is read as a falsey value, so any
truthiness test on it takes the wrong branch:

    d = {"b": 2, "a": 1}
    p = "x"
    print(sorted(d, key=lambda k: d[k] if p else 0))
    # CPython: ['a', 'b']        compiled: ['b', 'a']   (both keys 0, stable order)

**Pre-existing.** Measured identically on `6f227568` (master at the time) and
on the new-modular tree: 6/6 runs `['b', 'a']` in both. Found while bisecting
`CODEGEN_comprehension_target_shadows_struct_local.md`'s neighbour — the
capture-by-pointer regression — and *not* caused by that work. Recorded here so
the next person who trips over it does not re-bisect it from scratch.

## Why the output looks like a stable sort

The key function returns `d[k] if p else 0`. With `p` read as falsey, every key
is `0`, so `mojo_sorted_by_keys` sees all-equal keys and preserves insertion
order — which is `['b', 'a']`, because the dict literal is written that way. So
the visible symptom is "sorted() didn't sort", not "a string became 0", which
is what makes it hard to attribute.

## The distinction from the fixed bug

This is the *complement* of the capture bug fixed on 2026-09-30 in
`_lower_LambdaExpr` (`emit_calls.py`), where a pointer local's ADDRESS was stored
in a same-typed env field:

- that one: `char *`/`MojoDict *` field given `&local` — garbage pointer
- this one: the field appears to get the right *kind* of value but the string
  itself is not usable, so a truthiness test on it fails

A control that separates them, and which is CORRECT on both trees:

    d = {"b": 2, "a": 1}
    p = "y"
    print(sorted(d, key=lambda k: d[k] + (1 if p else 0)))   # -> ['a', 'b'] on both

So the string arrives and its CONTENTS are fine when used as a value; only the
truthiness coercion is wrong. That points at the `char *` -> `_Bool`/`int64_t`
truthiness path for an env-sourced value, not at the capture itself.

## Next step

1. Find the truthiness coercion for a value read out of the env. In
   `fire.ci` the lambda body for the failing case is a `_env->p` read followed
   by whatever the codegen emits for `if p`; compare it against the same
   coercion for a NON-captured local, which works. `mojo_truthy_cstr` is the
   runtime helper a `char *` truthiness test normally lowers to (see its use in
   `mojo/parser`/`_mojo_repr_*` paths), so the first thing to check is whether
   the env-sourced path calls it at all or tests the pointer bits directly —
   a non-null pointer's bits are never 0, which would make it read as TRUTHY,
   not falsey, so the emitted code is worth reading before theorising.
2. This is a compiled-path change, so it owes a full `make gate`. `gimple`,
   `gimplerunner` and `interporacle` are the steps that can see it; `mojoc` is
   not needed to reproduce.
3. A regression test belongs in `test_gimple_runner.py` next to the capture
   cases, and should use `test_gimple_stdout_repeated` — this failure is
   deterministic, but its sibling is not, and the two cases read as a pair.

## Evidence

- The two measurements above, on `6f227568` and on this tree, 6/6 identical.
- Control case correct on both trees.
