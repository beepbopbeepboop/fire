# `suite-self-test` is RED on `master` over a dangling citation the ratchet has
# already sanctioned, because the two dangling-ref mechanisms do not share a
# floor

**Area:** tests (`test_suite.py`'s `dangling refs: ...and outside those controls
the corpus is empty` check) against `tools/dangling_doc_refs.py`'s per-file
baseline. **Status: OPEN, measured, PRE-EXISTING on `master` (`cd61b4a0`), not
caused by the branch that found it.** Found 2026-10-05 on
`work/merge-formal39`, whose tree is byte-identical to master's on every file
this is about (`git diff master --stat` over the five citing documents,
`test_suite.py`'s check and both tools is empty except for that branch's
unrelated `STALE_PER_CHILD_BUDGETS` rows).

The subject is four rows across three documents that cited a document deleted
with its fix, and said why they were not corrected in the same commit — the
files were held by other workers' claims. **This is its other half**: the escape
hatch that document used has a cost, and the cost is a red gate job nobody wrote
down.

**Update 2026-10-06 (`work/formal40-2`): the red is GONE and the document this
one is about is deleted with its fix**, so the citation is written out rather
than pointed at. `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md:40` now
carries the fact, the baseline entry for that file is withdrawn
(`tools/dangling_refs_baseline.py` is back at the floor of zero it started
from), and `test_suite.py` is 342/0 — the strict check and the ratchet agree
again. The two branches of the argument below are otherwise unchanged, and the
last one is still the open half: `--write-baseline` can still raise a ceiling
the strict check has no floor for, and nothing decides that except a decision.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/suite.py formal-sweep-truth formal-admitted \
      formal-host-import-wall suite-self-test doc-refs --no-cache
  FAIL     suite-self-test  (56s)  exit 1
suite: 5 passed, 1 failed, 0 skipped  (6 tests, 6 jobs, 0 replayed from cache,
       59.8s wall, peak 1.5 GB)
```

`doc-refs` — the same walk, the same corpus — is **green in the same run**. The
one failure:

```
  - dangling refs: ...and outside those controls the corpus is empty, which is
    what a sweep buys: 1 dangling citation(s) outside test_suite.py
    (['FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md']);
    a new one is a ratchet failure
```

**And it is red on `master`, measured rather than asserted.** `master`'s tree was
extracted with `git archive master | tar -x -C .tmp/master-tree` and the same walk
run over it:

```python
import sys, os
sys.path.insert(0, ".tmp/master-tree/tools")
import dangling_doc_refs as D
os.chdir(".tmp/master-tree")
have, by_doc, by_file = D.find()
```

```
MASTER tree — dangling outside test_suite.py:
  ['FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md']
  cited by [('bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md', 40)]
```

One citation, one citing file, identical on `master` and here. (The document's
own name is spelled without its `bugs/` prefix throughout this file for the
reason the document it is about explains: a `bugs/`-prefixed name in prose IS a
citation, and writing one here would reproduce the failure being filed.)

## Why the two mechanisms disagree, and it is structural

| | mechanism | floor |
|---|---|---|
| `doc-refs` | `tools/dangling_doc_refs.py --ratchet` | a per-file ceiling in `tools/dangling_refs_baseline.py`, raised only by `--write-baseline` |
| `suite-self-test` | `test_suite.py::test_the_dangling_ref_corpus_can_only_shrink` | **zero**, unconditionally, outside this file's five deliberate fixtures |

The ratchet is the sanctioned one: `CLAUDE.md` says `--ratchet` "fails only when
a file GAINS a citation, against the per-file ceilings", and
`--write-baseline` is how a sweep is banked. `formal28-6-r2`'s fix used it
exactly that way — `--ratchet --write-baseline` raised
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md: 0 → 1`, which is why `doc-refs`
is green.

`test_suite.py`'s check has no such floor and no way to express one: it computes
`outside = {n: v for n, v in by_doc.items() if n not in fixtures}` and asserts
`not outside`. So a baseline raise that `CLAUDE.md` calls the sanctioned escape
makes one gate job green and the other red, and the red one says "a new one is a
ratchet failure" about a citation that is not new, was raised on purpose, and has
a document explaining it.

**The two checks are not redundant, which is why this is worth fixing rather than
deleting either.** The strict one is a property of the SWEEP ("the corpus outside
the controls is empty", proved with a guaranteed corpus so it cannot pass
vacuously); the ratchet is a property of the WALK ("no file's ceiling rises
without `--write-baseline`"). Collapsing them loses one. What is missing is the
join: the strict check should exempt exactly what the baseline has sanctioned,
so a raise is visible as a raise rather than as a contradiction between two jobs.

## The exact next step

Two moves, and the first is DONE (2026-10-06, `work/formal40-2`):

1. ~~**Delete or re-point the one citation**, in
   `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md:40`, and drop that
   file's baseline entry (`--ratchet --write-baseline`, which will then report it
   going 1 → 0).~~ **DONE**: the row there now carries the symptom and its
   current verdict instead of a citation of the deleted document, and
   `tools/dangling_refs_baseline.py` no longer lists that file — the ratchet went
   **7 → 6** and the `bugs/`-prefixed corpus is back at the floor of zero. The
   claims that held the three files are all released (`python3 tools/control.py
   claims` lists no worker for any of them now), which is the only reason this was
   applyable at all.
2. **Then decide whether `test_suite.py`'s strict check should read the baseline.**
   If the answer is yes, the honest form is `outside` minus the names the
   baseline records a non-zero ceiling for — which makes a raise a single visible
   fact in `tools/dangling_refs_baseline.py` rather than two jobs disagreeing. If
   the answer is no, say so in `test_suite.py`'s check text, because a reader who
   finds that check red after a sanctioned `--write-baseline` has no way to tell
   a real regression from a deliberate one. **This is the whole of what is left
   here**, and it is a decision rather than a patch: nothing in the tree says which
   of the two checks is allowed to be the strict one, and both are load-bearing
   for different reasons.

**What is deliberately NOT proposed**: widening the strict check to "ignore
`bugs/`-prefixed names" or adding the document to its `fixtures` set. Both would
make the corpus empty by naming the exception rather than by recording it, which
is the difference between a floor and a hole.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/dangling_doc_refs.py --ratchet        # green — the sanctioned raise
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py \
      2>&1 | grep -A2 'outside those controls'         # red — the same corpus
$ grep -rn FORMAL_arm64_a_narrow_typed_parameter bugs/ --include='*.md'
```
