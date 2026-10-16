# `TestNestedConditionFactSharing`'s growth bound is x2.2 and the counts now carry a fixed offset, so k=3 fails

**Area:** `test_formal_call_proof_gen.py::TestNestedConditionFactSharing`
· **Status: not fixed; the failure is a stale BOUND, not a re-derivation
regression, and the measurement that says so is below.** · found 2026-10-12 on
`work/formal301-docs` while running `test_formal_call_proof_gen.py` for an
unrelated FORMAL change · **pre-existing on master, not caused by that work**

`python3 tools/memslot.py --gb 8 --label cpg -- python3
test_formal_call_proof_gen.py` reports **9 failures**, and this is one of them;
`tools/suite.py`'s memory-measurement comment already records the job as
"formal-call-proofgen 2.5 GB (RED on 9 of 175)" (2026-10-09), so the red is
known — but this particular failure's cause is written down nowhere, and it is
not the certificate/blowup subject either of the two docs that mention
`hprior_*`.

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label hp -- python3 - <<'PY'
import os, sys; sys.path.insert(0, os.getcwd())
import test_formal_call_proof_gen as T
CONDS = T.TestNestedConditionFactSharing.CONDS
for k in (2, 3, 4):
    src = "def f(n):\n    x = 0\n" + "".join(CONDS[:k]) + "    return x\n"
    p, err = T._generate(os.path.join(os.getcwd(), ".tmp"), src, f"nested{k}")
    print(k, open(p).read().count("have hprior_"))
PY
```

## What I saw

The test asserts `counts[k] / counts[k-1] <= 2.2` for `k in (3, 4)`. Measured:

| k | `have hprior_` | ratio | the test's model |
|---:|---:|---:|---|
| 2 | **9** | — | — |
| 3 | **21** | **2.333** | x2.0 |
| 4 | **45** | 2.143 | x2.0 |

So k=3 fails (`2.333 not less than or equal to 2.2`). The counts are
`3·2^k − 3` exactly (9, 21, 45), and the **increments are 12 → 24, an exact
x2.0** — the memo is doing its job; what changed is that the counts are now
~2.5x smaller than the 24 / 48 / 96 / 192 the class docstring records, and the
smaller they are the more a FIXED `−3` offset pushes the ratio above 2. A
purely multiplicative bound (`<= 2.2`) is therefore the wrong shape for a
count with an additive constant, and the offset only shows at the smallest k.

## What I expected

The class docstring's own reading: "the per-path memo makes this x2 (the number
of paths) and anything above 2.2 is the exponential back". x2.33 is below the
pre-memo growth (x3.0 / x2.67 / x2.5 measured in the memo commit `cfd550b5`), so
this is NOT the exponential back returning — it is the offset.

## The exact next step

**Identify the 3 fixed facts before touching the bound**, because they are the
whole cause and they may be removable. They are emitted once per theorem and do
not scale with the paths: in the k=2 proof the `hprior_0_n` at the entry block of
each walk (two walks in the file) plus one `hprior_1_n` appear at indentation 0,
outside the `by_cases` bullets, while every other fact is inside a path scope.
If they are the entry-block facts a walk needs unconditionally (`s_0` is the
function's own start state, not a path's), the honest fix is either to hoist
them out of the count the test measures (count only the facts inside a
`by_cases` path scope, which is what the memo is about) or to assert the
INCREMENT ratio `(counts[k] - counts[2])` — measured 12 → 24, exactly x2.0 — and
say in the comment that the count carries a fixed per-walk offset.

Do NOT simply raise 2.2: the bound exists to catch the exponential back, and
raising it to cover an offset would also cover a real regression up to the new
number.
