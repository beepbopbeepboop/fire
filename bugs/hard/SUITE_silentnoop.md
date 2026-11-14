# SUITE_silentnoop: make check failure

SPLIT: SUITE_silentnoop-part2

**Status:** OPEN — surfaced by `make check` run on 2026-11-08 (suite: 35 passed, 23 failed).

Not a timeout: the job runs ~8.5 min against its registered `timeout=1500` and
still fails.

- Part 1 (investigation) is closed; its doc is deleted. It found exactly two
  failing cases sharing one build-time refusal.
- That refusal — a parameter whose call sites disagree across literal kinds —
  is FIXED (`e4a2cc2ed`, "specialize literal-kind mixed params including
  None/comprehensions"). Both of part 1's cases now pass
  (`parameter_rebound_to_one_container_kind_is_not_multi_kind` re-run green).

**The job is still red, on one different case:**

```
FAIL  zip_nested_tuple_target  compiled 'done\n' != reference '1 2 9\ndone\n'
```

```python
def f(pairs, others):
    for (a, b), g in zip(pairs, others):
        print(a, b, g)

def main():
    f([(1, 2)], [9])
    print("done")
```

The loop body never runs, so `1 2 9` is missing. This is a regression guard on
a lowering that already worked (the case's own comment says so). It is **not**
from `e4a2cc2ed`: the case passes at `1a7b1f413` (where it was added, 2026-09-28)
and at the 2026-11-11 tip `aca94072a`, and fails at `7f9788007~1`, so the
regression is in the 2026-11-11..11-14 window. Re-run:
`python3 test_silent_noop_iter.py zip_nested_tuple_target`.

The kept artifact
(`.tmp/silentnoop-failures/zip_nested_tuple_target/program.ci`) shows what the
lowering did, and it is not a wrong answer but a REFUSAL:

```
_t11 = (void *)pairs;
_t12 = (void *)others;
_t10 = mojo_zip (_t11, _t12);
_t13 = _slit_10000;          /* "program.py:2: void *" */
mojo_unsupported_iter (_t13);
```

so the whole `for` was replaced by `mojo_unsupported_iter`, and both
arguments reached `mojo_zip` through a `void *` cast. A plain `ValueError` out
of the zip lowering is what makes `_gen_stmt_ForStmt` fall back to that
zero-iteration generic path (see `ZipLongestFillRefusal`'s own docstring), so
the question is which narrowing now raises for a nested-tuple target.

The fix doc is `bugs/SUITE_silentnoop-part2.md`.
