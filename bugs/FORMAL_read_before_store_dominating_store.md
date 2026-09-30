# FORMAL_read_before_store_dominating_store: a name stored in only some arm of a branch still reads a build-dependent word

**Status: OPEN, and deliberately the remainder of a shipped fix rather than an
unattempted one.** `formal/model.py`'s `read_before_store` refuses the
straight-line case (2026-09-30, the `construct:arm64-silent-wrong-answers`
claim) and is deliberately silent on this one. Closing it needs a reachability
computation rather than a wider walk, and an approximation that misses some
arms is indistinguishable from no check at all — see "Why not approximated"
below.

This is the general case of
`FORMAL_read_before_store_returns_a_register.md`, which was correct about the
mechanism and shipped the statement-order version of the analysis.

---

## What I ran

```mojo
def f(n):
    for i in range(3):
        if i:
            t = 1
    printf("t=%d", t)
    return 0
```

## What I saw

CPython raises `UnboundLocalError: local variable 't' referenced before
assignment` when `i == 0` on the first iteration, and prints `1` otherwise. So
the program is right for two of its three iterations and wrong for the third.

Both formal backends BUILD it and print a value:

| build | result |
|---|---|
| arm64 | `t=1` |
| x86-64 | `t=1` |
| CPython, `i == 0` | `UnboundLocalError` |

`1` is the right answer here **by luck**: the register that held `1` from the
second iteration is still holding it at the read. Change the source to
`printf("t=%d", t + 1)` and the same build-dependence shows up as a wrong
number instead of an invisible one; change `t = 1` to `t = 7` and it returns
`7` regardless of the branch, which is the case where a reader would not
notice anything at all.

The pinned control is `test_formal_run.py`'s `branch_local_still_builds`,
which asserts this program still builds — the deliberate limit, recorded as a
test so it cannot be mistaken for an oversight.

## Why the statement-order walk cannot see it

`read_before_store` walks the body in order with a `stored` set, and adds a
branch arm's stores to `stored` so that a read AFTER the branch is not
reported. `t` is stored inside the `if`, so the store is seen, and the read
after the loop looks fine.

The store is real but not DOMINATING: whether the read is reached at all
depends on which arm ran. Deciding it means asking, for each read, whether
**every path from the function's entry to that read passes a store to the
name** — a question about the CFG, not about the order of the statements.

## The exact next step

Replace the `stored`-set walk's treatment of a branch with a fixpoint over
the CFG. Concretely, the smallest version that closes this shape:

1. Build the function's basic blocks from the statement tree. The emitters
   already know how to do this — both backends have a `_emit_b_to(label)` and
   a per-function label namespace, and `formal/model.py` already has
   `iter_nodes` for the tree. What does not exist is a block list, and it
   should be built ONCE in `formal/model.py` and read by both, for the reason
   every other layout decision in this module is shared.
2. Compute, per block, the set of names DEFINED on entry: the union of the
   predecessors' OUT sets. Iterate to a fixpoint (the CFG has loops, so one
   pass is not enough — `while` and `for` bodies are the reason).
3. A read of `name` in block `B` is this defect when `name` is in neither
   `B`'s IN set nor the statements preceding the read inside `B`.

Two things that version must get right, both of which the statement-order
walk already gets right for the wrong reason and would lose:

- **The `for` target stays bound after its loop.** CPython leaves it unbound
  only for an EMPTY iterable, and a CFG analysis that handles that exactly
  would refuse `test_formal_run.py`'s `for_range_break`
  (`for i in range(0, 100): if i > 3: break` then `return i`, which returns 4
  and is legal). Deciding it needs "did this loop execute at least once",
  which the CFG answers for free — the block after the loop is reachable from
  the loop EXIT edge as well as the entry edge — whereas the walk cannot.
  That is the strongest argument for doing this properly rather than
  widening the walk.
- **A name stored in every arm of an `if`/`elif`/`else` chain IS dominating.**
  `if c: p = 1 else: p = 2` then `print(p)` is legal and returns 3; the
  intersection over arms is exactly the right rule and the CFG gets it for
  free too.

## Why not approximated here

The two shapes above are the ones a "count the arms" heuristic gets right,
and there are others it does not: `try`/`except`/`else`/`finally` with a
`return` in the `finally`, a `break` out of one arm of a loop, a `match` with
a wildcard arm, a `del` of the name on one path. A partial rule that fires on
some of them and not others is worse than none in a specific way — it makes
the corpus look covered. The corpus is 156 files swept here and it does not
contain the shape at all, so a partial rule would look perfect on every
measurement available and still be wrong.

## Checked and NOT the same bug

- Not the straight-line case, which is fixed and pinned by
  `test_formal_run.py`'s `read_before_store_in_a_loop_refused`.
- Not a register-allocator bug: the allocator is right that `t` needs a home,
  and the home is fine. What is missing is a store on one path.
- Not `bound_names_in_order`'s business. That walk is the allocator's
  question — "does this name need a register" — and it answers correctly.
  The question here is "does this read have a value", which is a different
  one, and `formal/build.py` keeps the two apart on purpose.
