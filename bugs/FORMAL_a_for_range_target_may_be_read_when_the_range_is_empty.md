# FORMAL_a_for_range_target_may_be_read_when_the_range_is_empty

**Class:** a silent wrong answer, and the narrow remainder of the fixed
`for`-range rule. **Area:** `formal/model.py`'s `read_before_store` /
`_cfg_block_defs` (the loop-target definition), with the emitter half already
landed.

**Status: the STATICALLY decidable half is FIXED (2026-10-03,
`0340e4fc`); what is left is a range whose emptiness is a RUN-TIME fact.**

Found 2026-10-03 while fixing
`bugs/FORMAL_for_range_over_an_empty_range_overwrites_a_preassigned_counter.md`,
whose fix moved the loop's store so that an empty range does not bind its
target. That fix opened this: the analysis still counts the target as defined
when it cannot prove the range is non-empty, so a name nothing else stores is
read out of a register nothing wrote.

## What is wrong

```mojo
def main(n):
    for q in range(0, n):
        x = 1
    printf("q=%d", q)
    return 0
```

| | `n = 0` | `n = 3` |
|---|---|---|
| CPython 3.14 | `UnboundLocalError` | `0` / `2` |
| arm64 | **`9`** | **`9`** |
| x86-64 | **`9`** | **`9`** |

`9` is whatever the caller left in the register the allocator handed `q`, so the
answer changes with the build and is not a number the source wrote — which is
the exact failure the "Read before store" section of `formal/model.py` exists
to refuse, and it is the answer this path gave before the fix too (it printed
`0`, the stored `start`, which is wrong in the other direction: CPython raises
rather than answering).

**The fix narrowed the case that is decidable and left this one**, which is the
honest direction: keeping a definition can only let through a program whose
range happened to be non-empty, where dropping it would refuse a program
CPython runs. `_for_target_never_binds` therefore asks only about a `range` of
literals, using `_range_is_nonempty`.

## What is ruled out, measured

* It is not the emitter. With the count-declaring form (`b[0] = 3` before the
  reads) the same shapes build, run and answer CPython's numbers; the store
  simply is not reached.
* It is not the `read_before_store` fixpoint's dominance reasoning. It handles
  this shape correctly for a `while` (`i = 0; while i < 3: t = 1; …` then
  `return t` is allowed, and `test_formal_read_before_store.py`'s
  `while_body_store_*` rows pin both directions) and for a `for` whose range is
  statically non-empty (`for_target_stays_bound`,
  `nonempty_literal_range_target_is_still_a_definition`).
* It is not arch-specific. Both backends print the same wrong word here, which is
  a small comfort: they at least agree.

## Why it is not a patch, and what one would take

Answering it soundly needs a fact this analysis does not have: **the target is
definitely bound after the loop iff the range yields at least one value OR the
name was definitely stored before it.** The first disjunct is a run-time
property of `n`; the second is already computable. The CFG cannot express it —
the join is an intersection over predecessors and the header's exit edge is one
of them — so it is not a rule to add to `_cfg_block_defs` but a new question
for it, and the question is about values rather than about paths.

Two shapes of an answer, and the second is the one that costs:

1. **Refuse the read whenever the range's emptiness is undecidable.** One line,
   and it refuses `for i in range(0, k): … ; return i`, which CPython runs and
   which this tree's own `both_arch_for_range_restores_a_spilled_counter_too`
   row is. That is a false refusal of ordinary code, so it is not free.
2. **Carry the emptiness as a predicate.** `_preheader_literals` already carries
   a "definitely this integer" table along every edge, which is how
   `_loop_body_always_runs` decides a `while`. The same machinery answers
   `n >= 1` for a parameter only if some path states `n`, so the honest scope is
   the shape `for i in range(0, k)` where `k` was bound to a literal earlier —
   and the rest stays a divergence.

Either way the residual is the same class as the recorded one: a program CPython
rejects, answered with a word from a register. The difference from
`empty_range_target_stays_bound` (deleted with its fix) is only that emptiness
here is not decidable at build time.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/x .tmp/prog.mojo && .tmp/x 0
q=9
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=x86_64 -o .tmp/y .tmp/prog.mojo && .tmp/y 3
q=9
$ python3 -c 'exec(open(".tmp/prog.mojo").read()); main(0)'
UnboundLocalError: cannot access local variable 'q' where it is not associated with a value
```
