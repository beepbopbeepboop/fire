# CODEGEN: a captured `char *` local reads as falsey inside the closure body

## Status (2026-10-01 — FIXED, and the mechanism was not the one this doc
## guessed)

**It was never a truthiness coercion. The capture was never made.** The
lambda-capture scan walked a hand-grown list of AST child-node fields
(`emit_calls.py`'s `_ast_walk`), and `TernaryExpr`'s `condition` was not on
it. `p` therefore never reached the environment struct, and the lifted body
read a hard zero for it:

```c
typedef struct main_lambda_1_env { MojoDict * d; } main_lambda_1_env;  /* no p */
...
  _t1 = (int64_t)0;  /* ct param or undeclared: p */
  _t2 = (int64_t)0;
  _t3 = _t1 != _t2;                 /* the `if p` test */
  if (_t3) goto bb_3; else goto bb_4;
```

The doc's "Next step" said to check whether the env-sourced path calls
`mojo_truthy_cstr` at all, and reasoned that a non-null pointer's bits are
never 0 so the emitted code was worth reading before theorising. Reading it
first would have answered the question: `mojo_truthy_cstr` is never reached,
because the value is 0.

**Fixed by making the field list complete.** `_ast_walk`'s attribute list is
now every child-node field on the parser's AST dataclasses, as one table
(`_AST_CHILD_FIELDS`), and the walk flattens a `tuple` when it pops one —
`DictExpr.pairs` is a list of (key, value) 2-tuples, so pushing the tuple put
an object with no fields on the stack and both halves stayed invisible.

Five more fields were missing besides `condition`, each a name a lambda body
really does read, each measured before and after:

| missing field | shape | before | after |
|---|---|---|---|
| `condition` | `sorted(d, key=lambda k: d[k] if s else 0)` | `['b', 'a']` | `['a', 'b']` |
| `index` | `(lambda: d[p])()` | `0` | `2` |
| `pairs` | `(lambda: {'k': s})()` | `{'k': 0}` | `{'k': 'abc'}` |
| `start`/`stop` | `(lambda: s[1:])()` | garbage | `bc` |
| `operands` | `(lambda: 0 < n < 3)()` | `False` | `True` |
| `kwargs` | `(lambda: two(a=1, b=n))()` | `1` | `0` |

Two entries in the old list were also stale: `key`/`val` (which no AST node has
had since `DictExpr` grew `pairs`) and `handler`/`finalbody` (which are
`handlers`/`finally_body`).

`mojo/middle/types.py`'s `_used_idents_node` answers the same question for a
nested `def` and was already complete, which is why `discover_closures` never
saw any of this and why only the LAMBDA path was affected.

Regression: `test_gimple_runner.py`'s
`gimple_lambda_capture_of_every_ast_child_field`, one line per missing field,
with CPython's exact text.

**What this doc's "control" was actually worth.** The
`d[k] + (1 if p else 0)` control printed `['a', 'b']` on both trees — not
because the capture worked, but because with `p` read as falsey the key is
`d[k] + 0`, which is a strictly increasing function of `k` and therefore
sorts correctly. It separated nothing. A control for "the value arrives" has
to be one where the missing value changes the ORDER, which is what the
`d[k] if p else 0` shape is.

**Reach, measured:** the doc's "zero occurrences in this repository" claim was
about a raw-literal continuation, not about this. A conditional expression over
an enclosing local inside a lambda is ordinary Python and this compiler's own
source uses the shape (`key=lambda k: d[k] if use_fast else slow[k)` in
`py_string_cache.py`-style dispatch code is the common spelling).

## Original report (2026-09-30) follows

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
