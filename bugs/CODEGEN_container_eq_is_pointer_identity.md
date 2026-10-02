# CODEGEN: `==` / `!=` between two containers is POINTER identity, so any convergence test written on one never fires

## Status (2026-09-29 — OPEN, measured; one call site worked around, the lowering itself is untouched)

`a == b` where both operands are the same container type (set, list, dict)
lowers to a raw pointer comparison. Two equal-but-distinct containers therefore
compare unequal, always, with no diagnostic — and a fixed-point loop written as
`while True: ...; if nxt == proven: break` never terminates.

Strings are NOT affected: `str == str` lowers to `mojo_cstr_cmp(a, b) == 0`,
which is a value comparison.

## What was run, and what it showed

Reproduced against the stage2 binary left at `.tmp/stage2-fire-binary`
(a copy of the self-hosted compiler), under an 8 GB ceiling:

```
$ python3 tools/memslot.py --gb 8 --label tiny-build -- \
      .tmp/stage2-fire-binary build .tmp/tiny.py      # def main(): print("tiny ok")
memcap: BREACH  8.2 GB > 8.0 GB ceiling (102%), 1 procs -- killing tiny-build
```

A TWO-LINE program, which `python3 fire.py build` compiles and runs in about a
second. The same binary on `--dump myinterpreter.py` reached 8.5 GB in under
three minutes. A `sample` of the process at the moment of the growth
(`.tmp/sample_big21.txt`) puts 100% of the stack in the wait-descriptor
fixed point, allocating:

```
mojo_middle_coro_lower_815e8f
  mojo_middle_coro__compute_no_wd_forward_815e8f   1706 samples
    mojo_set_new / mojo_set_init / _pr_grow         (a fresh set per round)
    mojo_dict_items                                  (a fresh list per round)
```

`myinterpreter.py` contains no `async def` at all, so the fixed point's work
set is EMPTY there — which is the point: the loop's exit condition is
`nxt == proven`, i.e. `{} == {}`, and that is the comparison that never fires.

The lowering, from a two-set program (`.tmp/seteq.py`, compiled with
`gimple_codegen.compile_to_gimple`, do_imports=False):

```c
  _t2 = mojo_set_new ();
  b = _t2;
  _t3 = a == b;                 /* <-- pointer comparison, for two MojoSet * */
  if (_t3) goto bb_3; else goto bb_5;
```

Same shape for `MojoList *` (`_t8 = a == b;` in `.tmp/lstdict.c`) and for
`MojoDict *`. So every site in the compiler that closes a loop with a container
comparison has this hazard, and `set()`/`list()`/`dict()` literals make the
distinctness certain — each `{}` is its own allocation.

## Why it is silent rather than merely wrong

Because the answer is *plausible*: `a == a` is True (same pointer), and two
containers that genuinely share storage compare equal. Only the "two separate
but equal containers" case is affected, which is exactly the case a
convergence test is written for. Nothing else in the pipeline complains, the
process simply stops making progress — and with no garbage collector in the
runtime, each round's fresh set and list are never reclaimed, so it looks like
a memory leak rather than a non-terminating loop.

## What was done about the one site this branch owns

`mojo/middle/coro.py`'s `_compute_no_wd_forward` no longer contains a
convergence comparison at all: it is a worklist whose loop ends when the
queue drains (and its comment says why, with the measurement). That is a
workaround for a site, not a fix of the lowering. Every other
`while`-until-stable over a container in the tree — this compiler has several,
and `mojo_set_difference`/`mojo_set_intersection` already exist for the set
algebra — carries the same trap.

## Exact next step

In `mojo/backend_gimple`'s comparison lowering (`_lower_compare` /
`_lower_compare_chain` in `emit_exprs.py`): when both operands are the same
container kind, do not fall through to the generic pointer comparison.

* set: add `mojo_set_eq(MojoSet *, MojoSet *)` to `runtime/fire_runtime.c`
  (the slot walk already exists in `mojo_set_intersection`; compare
  `used` then every int-slot against `mojo_set_contains_int` and every str-slot
  against `mojo_set_contains_str`) and call it.
* list: compare `mojo_list_len` then element-wise through the SAME int/str
  accessor the list was built with — note that this one needs the element type,
  which is the harder half (see the `add_int`/`contains_str` note above
  `mojo_set_contains_str` in `fire_runtime.c`).
* dict: `used` plus key/value pairs.

Until then, and as a stopgap worth auditing for: any convergence loop over a
container must terminate on something that is not `==` — a worklist draining, a
counter, a monotone measure.

A test belongs beside this: two separately-built equal sets, one empty and one
not, asserting `==` is True — which no current test covers, which is why this
survived.