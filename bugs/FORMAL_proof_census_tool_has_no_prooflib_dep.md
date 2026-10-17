# `formal-proof-census-tool` reads `lib/*.olean` but does not depend on `prooflib`, so it is red on a clean worktree

**Area:** FORMAL — `tools/suite.py` registration. **Status: OPEN, NOT fixed here
(fixing it is a `tools/suite.py` registry change, which this branch's task puts
off limits deliberately).** Found 2026-10-12 on `work/formal307-docs`, while
re-banking the `fact` row of `tools/formal_proof_census_baseline.json` (a
DIFFERENT, now-fixed bug — the committed baseline's `fact` row was stale for
`fact.mojo`, and BOTH documents that recorded it are deleted with the fix, so
neither path resolves any more; this note is the part of that row's story that is
not them).

## What I ran, and what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
-  'Specs'] : lib/ is missing ['IEEE754', 'ProofLib', 'X86', 'work', 'Refine',
   'Contracts', 'Peephole', 'Specs']; every key would miss and the report would
   be reporting the wrong thing
Ran 61 tests in 0.248s
FAILED (failures=1)
```

`test_formal_proof_census.py::TestCommittedBaseline::
test_library_state_agrees_with_the_question_it_asks` reads
`os.path.join(HERE, "lib")` (the repository-root `lib/`, `formal/lean.py`'s
`LIBRARY_MODULES`) and requires every module's `.olean` to be there. On a clean
worktree `lib/` does not exist, so all eight are "missing" and the test is red
until a Lean library build has run in that tree. **Measured: the same command is
green after the census tool built `lib/` (the `--only fact` re-bank populates it
through `formal/lean.py::ensure_library`, which is why the re-bank both fixed
the stale row and made this pass), and red before it.**

## Why it is a real hole and not a bookkeeping nit

The job that runs this file is registered with `deps=['preflight']` ONLY:

```
tools/suite.py:3780  test('formal-proof-census-tool', [PY, 'test_formal_proof_census.py'],
                          mem='tiny', deps=['preflight'], …)
```

`prooflib` is the registered shared-library build (`tools/suite.py:2744`), and
every other Lean-reading job in the same bucket declares it
(`deps=['preflight', 'prooflib']`). Without an edge, the runner may schedule this
job before `prooflib` has produced `lib/`, so on a machine that has not built the
library the job fails for a reason that has nothing to do with the baseline it is
supposed to be ratcheting. It does not fail on a warm tree (or on one where
another job populated `lib/` first), which is exactly why it survives.

## The exact next step

One word in the registry, in `tools/suite.py:3780`:

```
deps=['preflight', 'prooflib'],
```

`prooflib` is already the right dep for this file's other Lean-reading
neighbours, is deliberately in no bucket (it is a dependency, not a test), and
`test_suite.py`'s bucket checks accept a `deps`-only registration, so the edge
does not add a job to any bucket. Then re-run the job on a tree with `lib/`
removed to confirm it goes green.

## Not this doc: the `--arch x86_64` half has no baseline at all

`tools/formal_proof_census_baseline_x86_64.json` does not exist, so
`--arch x86_64` has nothing to ratchet against. That is a separate, larger item
(a whole 93-example x86-64 census and its committed baseline), noted here so it
is not lost with the deleted doc, and it is not what this file is about.
