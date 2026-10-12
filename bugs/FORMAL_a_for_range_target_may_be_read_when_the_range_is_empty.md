# FORMAL_a_for_range_target_may_be_read_when_the_range_is_empty

**Class:** a silent wrong answer, and the narrow remainder of the fixed
`for`-range rule. **Area:** `formal/model.py`'s `read_before_store` /
`_build_cfg` (the loop-target definition), with the emitter half already
landed.

**Status: PARTIAL — the emptiness as a PREDICATE is FIXED (2026-10-04,
`formal/model.py`: `_for_emptiness` is the one reader, `_range_is_nonempty`
reads the preheader's literals, and `_build_cfg` seeds the body's first block
with the target). What is left is the case whose emptiness is a RUN-TIME fact
and cannot be one by any build-time decision — a range bound a PARAMETER, which
is §"What is left" and which now carries the measurement that closes option 1
below.**

Found 2026-10-03 while fixing the empty-range counter bug (that doc is deleted
with its fix, `0340e4fc`), whose fix moved the loop's store so that an empty
range does not bind its target. That fix opened this: the analysis still counts
the target as defined when it cannot prove the range is non-empty, so a name
nothing else stores is read out of a register nothing wrote.

## 0. What landed, and it is the whole of what a build-time decision can reach

Three pieces in `formal/model.py`, and the third is the one that was not
obvious:

1. **`_for_emptiness(stmt, consts)` is the ONE reader of "does this loop's
   iterable yield a value"** — `'always'` / `'never'` / `'maybe'`. It replaces
   the iterable half of `_loop_body_always_runs` and all of
   `_for_target_never_binds`, which were the same question asked twice (and the
   second time without the preheader). It also widens the decidable set to a
   literal SEQUENCE: `for i in []` and `for c in ""` bind no target, which they
   did not before, because only a `range` call was ever read.
2. **`_range_is_nonempty(args, consts)` reads `_preheader_literals`' table**, so
   `k = 0` then `range(0, k)` is an emptiness this build decides. That is the
   doc's option 2, and the table was already there — `_loop_body_always_runs`
   was reading `while i < 3:` with it and ignoring its own `consts` for the
   `for` arm. Both directions now fall out of the same predicate:
   `k = 0` is `'never'` (the header's definition is dropped and a read after the
   loop is the refusal CPython's `UnboundLocalError` already is) and `k = 3` is
   `'always'` (the header's zero-iteration edge is dropped, so a store in the
   body dominates the read after it).
3. **`_build_cfg` seeds the loop TARGET into the body's first block**
   (`_Block.seed`), instead of leaving it to the header's `defs`. Reaching the
   body means the head test passed, which means the loop bound the target — a
   fact about the body's ENTRY. Without it, dropping the header's definition
   for a loop decided `'never'` also refused the reads INSIDE the body
   (`for i in range(0, 0): sink(i)`), which is a refusal of a program CPython
   runs, because the body never executes. This is the same mechanism a `match`
   capture uses, and for the same reason: a binding that happens on the edge
   INTO a subtree rather than in a block the predecessors can see.

Measured, both architectures, `fire.py build --formal --no-prove`:

| | CPython 3.14 | arm64 | x86-64 |
|---|---|---|---|
| `k = 0` then `for q in range(0, k)` then `printf("q=%d", q)` | `UnboundLocalError` | **refused** (was `q=9`) | **refused** (was `q=9`) |
| `k = 3` then the same | `2` | `2` | `2` |
| `last(k)` with `for i in range(0, k): s = s + i` then `return i` | `3` | `3` | `3` |
| `for q in range(0, n)`, `n` a parameter | `UnboundLocalError` | `q=9` | `q=9` — **the residual** |

**And the corpus does not move, which is why this survived four rounds**: over
every `*.mojo` under this worktree and `../new-modular/Mojo/stdlib/std` —
378 files, 5269 functions, compared against `HEAD`'s `formal/model.py` loaded
side by side — `read_before_store`'s answer changes for **0** of them. So the
class this fixes does not occur in the code the compiler is pointed at; what
that means for a gate is the good direction (no `stdlib-dylib` skip count can
move), and what it means for the bug is that the only witnesses are new code.

`test_formal_read_before_store.py` pins all of it: nine new rows, each with the
CPython oracle in both directions — `preheader_zero_range_target_is_not_a_definition`,
`preheader_nonzero_range_target_is_still_a_definition`,
`preheader_nonzero_range_body_store_ok`, `preheader_zero_range_body_store_refused`,
`preassigned_target_survives_a_preheader_zero_range`,
`empty_literal_range_body_reads_its_target_ok`,
`nonempty_range_body_reads_its_target_ok`,
`empty_literal_list_target_is_not_a_definition`,
`empty_string_target_is_not_a_definition` — plus
`preheader_range_bound_from_a_parameter_keeps_the_target`, which pins the
residual as a case so it cannot rot.

## What is wrong

THE RESIDUAL, in its own words, and it is the shape §0 did not reach:

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

**§0 closed the same program with `k` in place of `n`**, so what is left of
this defect is exactly the question of whether a PARAMETER's value can be a
build-time fact. It cannot: nothing in the program states it, and the honest
answer is that the loop's emptiness is a property of the call.

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

## What is left, and why the two options of the old §"Why it is not a patch"
are now settled rather than open

Answering it soundly needs a fact this analysis does not have: **the target is
definitely bound after the loop iff the range yields at least one value OR the
name was definitely stored before it.** The second disjunct is computable and is
in the fixpoint; the first is a property of the bound.

1. **Refuse the read whenever the range's emptiness is undecidable.** Refuted by
   measurement, not by argument, and the measurement is this tree's own test
   row: `test_formal_run.py`'s `both_arch_for_range_restores_a_spilled_counter_too`
   is `def last(k): s = 0; for i in range(0, k): s = s + i; return i` — a `for`
   over a range with a PARAMETER bound whose target is read after the loop —
   and `main` calls it with `last(4)`. The rule refuses it on both
   architectures and CPython answers `3`. The row is also the reason the
   `'maybe'` answer keeps the header's definition: it is ordinary code, not a
   corner.
2. **Carry the emptiness as a predicate.** **DONE** (§0): `_preheader_literals`
   decides `range(0, k)` for a `k` a path states, which is the scope this option
   named, and the rest stays a divergence — now measured and pinned rather than
   described.

**So what remains is not an analysis question.** It is a question about the
EMITTED IMAGE: the only sound way to answer "was this loop target ever bound"
where the answer is a run-time fact is to ASK at run time, and neither emitter
has anywhere to put the answer. `formal/model.py`'s "What a value is" section
says a value is one 64-bit word with no tag, so "unbound" is not a value this
path can carry; the emitter would have to allocate a flag per loop target and
branch on it at the read, which is a new instruction sequence in both backends,
a new case in both proof generators' CFGs, and a new step lemma per branch — a
project, and `bugs/FORMAL_a_for_range_target_may_be_read_when_the_range_is_empty.md`
is where its measurements belong.

The alternative to asking is refusing, and option 1 is what that costs. Until
one of them is done, this doc is a recorded divergence in the direction the
analysis already chose everywhere else it cannot tell what a word holds.

## Reproducing

The RESIDUAL, unchanged:

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

and the shape §0 closed, which is the same program with `k = 0` on the line
before the loop — refused on both architectures:

```console
$ cat .tmp/prog.mojo
def main(n):
    k = 0
    for q in range(0, k):
        x = 1
    printf("q=%d", q)
    return 0
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/x .tmp/prog.mojo
build: main: 'q' is read at line 5 before anything in this function stores it, and
CPython raises UnboundLocalError for that program (NameError at module level). …
```

The tests, both files, no builds in the first:

```sh
python3 test_formal_read_before_store.py
python3 test_formal_run.py both_arch_for_range_restores_a_spilled_counter_too \
  for_range_break for_range_continue for_range_else
```
