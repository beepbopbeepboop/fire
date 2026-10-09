# `tools/formal_proof_census_baseline.json` has 52 rows against a 93-file corpus, so `formal-proof-census-tool` is RED on master and the census's ratchet is over 44 % of its own corpus

**Status re-measured 2026-10-08 (`work/formal251-docs`): the 52-of-93 half is
FIXED and the red that remains is a different one.** `07cc3260` (2026-10-05,
"the proof ratchet described 52 examples; the corpus is 93 …") banked the rows,
so the baseline is now **93 of 93** and
`test_every_example_has_a_row_and_every_row_a_status` **passes** — the ratchet
now watches its whole corpus. What is still red is one row whose
`source_sha256` is stale: `ffe27e1a` (2026-10-05 17:50) rewrote
`formal/examples/fact.mojo`'s contract, the merge-banking of `07cc3260` added
the 41 new rows from the machine's CAS history and did **not** refresh a row it
already had, so `test_each_row_is_tied_to_the_example_it_measured` fails with

    66e21e6a…('baseline') != b2bbaf51…('on disk')  fact.mojo has changed since
    the baseline was written; re-seed with --write-baseline

and `formal-proof-census-tool` is still non-zero on a tree whose `lib/*.olean`
are built. (`test_library_state_agrees_with_the_question_it_asks` also fails in
a FRESH worktree, where `lib/*.olean` do not exist yet; that one is an
environment fact and not this doc's.) **The exact next step is the doc's own
recommendation, one row:** `python3 tools/memslot.py --gb 8 --label census-arm
-- python3 tools/formal_proof_census.py --only fact --write-baseline`, which
elaborates `fact` (~222 s Lean) and, if `lib/*.olean` are absent, builds the
library first. That is a Lean run, so this light worker did not take it — it is
the integrator's, and `fact`'s row is `lean-rejected` so the re-seed may change
the stored verdict. **The x86-64 half is unchanged and still never run**:
`formal_proof_census_baseline_x86_64.json` does not exist.

**Claim** `project:loop-invariants` on `work/formal66-loop-invariants`.  **Not
mine**: this is the census's file and its tool, and nothing on this branch
touches either.  **Measured** on `master` @ `cd2a1678` on 2026-10-06, and it is
the state of the tree, not of this branch — `git diff master -- tools/
formal_proof_census_baseline.json formal/examples/` is empty.

## What is broken

`test_formal_proof_census.py` is a REGISTERED gate job (`formal-proof-census-
tool`, `mem='tiny'`, 55 assertions, no Lean, no build) and it is **red**:

    $ python3 test_formal_proof_census.py
    ...
    FAIL: test_every_example_has_a_row_and_every_row_a_status
    self.assertEqual(sorted(self.records), C.corpus(),
                     "an example with no baseline row is one the ratchet "
    ======================================================================
    Ran 55 tests in 0.444s
    FAILED (failures=1)

    $ python3 -c 'import sys; sys.path[:0]=["." ,"tools"];
                  import formal_proof_census as C;
                  b = C.load_baseline(C.baseline_path("arm64")); …'
    baseline rows: 52   corpus: 93   missing: 41

`tools/formal_proof_census_baseline.json` says `"examples": 52`, `"written":
"2026-10-05T19:14:00Z"`, and holds 52 records; `formal/examples/` holds **93**
`.mojo` files.  So **41 of the corpus has no baseline row at all**, and the
ratchet — whose stated job in the module docstring is *"fails when a program gets
worse"* — is watching 55 % of its own corpus.

## Why this is worth more than the red

**`tools/suite.py`'s own comment says this corpus is 93 and the baseline is not.**
The census's registration carries `extraglob=['formal/examples/*.mojo']`, and
`formal/examples/` grew 52 → 93 in `56c3f8ca` ("the proof corpus grows 52 -> 93
examples").  `write_baseline` **merges** and only drops a row whose example was
DELETED, so the 41 new examples can only enter the baseline by a deliberate
`--write-baseline` run over them — which is the tool working as designed, and
which nobody has done.  There is a partial attempt: `c6b8105f`, "record the
eleven changed examples in the proof-regression baseline", which banked ELEVEN
of the forty-one.

**The consequence is a green that does not mean what it says.**  `compare` skips
a stem the baseline does not name with an `INFO` finding ("not in the baseline —
a new example"), and `INFO` does not fail the run.  So `formal-proof-census`
reports no regression for 41 programs it has never measured, and the tool's own
`--list` prints the corpus it is about to sweep without saying that 41 of them
have nothing to compare against.

## The exact next step

**Superseded by the Status at the head: half 1 is DONE (`07cc3260` banked the
rows, 93 of 93) and half 2 resolved in favour of banking.** What remains is the
re-seed of the one changed row, `fact`, and the x86-64 baseline; both are the
head Status's. The text below is the record of what the work was.

Two halves, and the order matters:

1. **Bank the missing rows, in bounded runs.**  The census is a *timing*
   measurement (`-j` defaults to 1, "because this is a timing measurement") and a
   full 93-example pass is a multi-hour `lean` workload, so it is not one
   command.  `--only` narrows the workload and `--write-baseline` merges, which
   is what `c6b8105f` did for eleven:

        python3 tools/memslot.py --gb 8 --label census-arm -- \
          python3 tools/formal_proof_census.py --only <stem> --write-baseline

   Run it per stem (or per small group), arm64 first, and then
   `--arch x86_64` — `tools/formal_proof_census_baseline_x86_64.json` is the
   other architecture's file and it does not exist yet, so the x86-64 half of the
   ratchet has never run.

2. **Decide what a corpus file added AFTER the last banking means for the
   tool's own test.**  `test_every_example_has_a_row_and_every_row_a_status` is
   red, and the alternative to banking the rows is to stop asserting that every
   example has one — which would make the job green and the ratchet weaker, and
   is the direction this project argues against every time
   (`tools/formal_proof_census.py`'s own docstring: *"A finding is not a failure;
   a REGRESSION is"*, and a corpus member with no row is a silent gap rather than
   a finding).  **Recommendation: bank the rows.**  **Resolution: the rows were
   banked, and a row that is already present but whose example changed is the
   half the merge did not handle — that is the stale `fact` row the head Status
   names.**

## Reproducing

    export PATH=/opt/homebrew/bin:$PATH
    cd /Users/mrs/net/chatgpt/claude/work-531

    python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_proof_census.py      # 55 tests, 1 failure

    python3 - <<'EOF'
    import sys; sys.path[:0] = [".", "tools"]
    import formal_proof_census as C
    banked = set(C.load_baseline(C.baseline_path("arm64"))["records"])
    corpus = set(C.corpus())
    print(len(banked), "banked,", len(corpus), "in the corpus, missing:",
          sorted(corpus - banked))
    EOF

## Why it is filed and not fixed here

The census is `formal41`/`formal32`-shaped work with its own claims behind it,
the fix is a multi-hour `lean` measurement plus a decision about the tool's own
test, and the task this branch carries is loop invariants.  A worker that runs
the bank while another worker edits the baseline produces exactly the class of
conflict this repository's `compare`/merge design exists to survive and no
faster.