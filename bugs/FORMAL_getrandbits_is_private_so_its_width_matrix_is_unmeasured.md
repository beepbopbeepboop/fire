# `random.getrandbits` is deliberately private, and the consequence is that its width matrix is not measured

**Area:** FORMAL / host modules. Filed 2026-10-05 on `work/merge-formal45`
while merging `work/formal31-5`, which implemented the same module and reached
the opposite conclusion about one name.

## What the two sides did

`formal/hostmods/random.mojo` is an MT19937 transcription whose published
surface is `seed` and `randrange`, and there were two of them — `master`'s and
`work/formal31-5`'s — written independently against the same oracle.

**`master`'s keeps `_getrandbits` private.** The rule is `formal/imports.py`'s
own: a name with no caller in the tree is a comment rather than a capability.
Nothing in the 768-file corpus calls `random.getrandbits`, so it is not
published, and `test_formal_random.py`'s `absent` group asserts the consequence
rather than leaving it implicit:

```python
("getrandbits", "def main() -> Int32:\n"
                "    printf(\"%lld\\n\", random.getrandbits(8))\n"
                "    return 0\n"),
```

which must be refused with a message naming `getrandbits`.

**`work/formal31-5`'s publishes `getrandbits`** and tests it directly against
CPython over its `SEEDS = (0, 1, 23, 17, 20260930, 1 << 32, -7)` and
`WIDTHS = tuple(range(1, 65))` — 7 x 64 = **448 answers per backend**, one
image per backend:

```python
for seed in SEEDS:
    for k in WIDTHS:
        lines.append(f"random.seed({seed})")
        lines.append(f'printf("%ld\\n", random.getrandbits({k}))')
```

## What that costs, concretely

`master`'s `widths` group reaches `_getrandbits` only *through*
`randrange(0, 2**k)`, for `k` in `1, 32, 33, 40, 62, 63`, from ONE seed. Three
things follow that the direct matrix would have covered:

1. **Widths 2..31 and 34..61 are unmeasured.** They are the one-word path
   (`k <= 32`: one draw shifted down) and the middle of the two-word path, so
   the risk is a shift applied to the wrong word; only the two ends of each
   range are pinned.
2. **`k = 64` is unmeasured.** `randrange` cannot express it — `2**64` does not
   fit a signed 64-bit `Int` — and formal31-5's own docstring says the `k = 64`
   answer is compared modulo `2**64`, which is the one row where this path's
   answer and CPython's differ in REPRESENTATION rather than in value.
3. **Only one seed.** `getrandbits` reads the state's index, so a defect that
   only shows after a twist is in `twist`'s group rather than in the width
   matrix; but a defect in the *word order* across seeds is not.

The merge keeps `master`'s module and suite (deleting either of `master`'s
`absent` rows or `formal31-5`'s implementation would have been choosing a
behaviour, not resolving a merge), so the 448-answer matrix is what is lost.

## The next step, exactly

One of:

* **Publish `getrandbits`** and drop the `absent` row that pins its refusal.
  That is a one-line change to the module (rename `_getrandbits` to
  `getrandbits`) plus one line in `formal/imports.py`'s published-surface
  comment, and it buys the whole matrix. The cost is a published name no
  corpus file calls, which is the thing `formal/imports.py`'s rule objects to.
* **Or keep it private and say so in the module docstring**, so the next reader
  knows the width matrix was a deliberate omission rather than an oversight.
  `formal/hostmods/random.mojo`'s docstring does not currently mention
  `getrandbits` at all, which is the gap.

Reproducing the matrix without publishing the name is not possible: it is a
differential on the module's own output, and the module's output is reached
only through a published name.

`test_formal_random.py` on this tree: 8 groups, `resolve`, `callers`,
`widths`, `twist`, `seeds`, `rejection`, `statuses`, `absent`.