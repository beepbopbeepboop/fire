# Three places state a test's status, and the registry no longer agrees with any of them

Found 2026-09-30 while merging `work/disabled-until-fixed` (which moved
`ab-native` from `expect=` to `disabled=`, see
`bugs/CODEGEN_ab_native_fails.md`). **Not caused by that work for two of the
three, and none of them is a live defect** — nothing computes a verdict from
these strings — but each one is a place a reader is told what the suite is
doing, and all three are now wrong about the same job.

**Status: 2 of 3 corrected in place, 1 left for the owner.** Corrected in the
2026-09-30 merge with master: `CRASH.md` (banner + the one row the `disabled=`
change falsified) and `bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`
(its table, re-censused). Left open: the `CLAUDE.md` "gate is otherwise clean"
tally, because that is a claim about a *run* and only a gate run establishes
it — a light merge worker is not allowed to run one. What did land in
`CLAUDE.md` is the annotation that says so, plus the corrected `EXPECTED`/
`DISABLED` table above it, which master had falsified by registering three more
`expect=` jobs.

The numbers below are the census as it was when this was found. **Master moved
all three of them** while this doc was open — `check` is 32 tests, not 22, and
`expect=` is 16, not 13 — which is the point: the same three files went stale
underneath a change made in none of them, twice.

## What I ran

    $ python3 tools/suite.py --dry-run check
    22 tests, 22 jobs, -j18          # 32 on the merged tree

    $ python3 tools/suite.py --dry-run native
    3 tests, 2 jobs, -j18
    mojoc  (1 job)  [exclusive]
      ab-native  (DISABLED: not run, 0 jobs, reserves 0 GB)  — not run: known to fail …
    native-dumpfull  (1 job)

    $ python3 -c "…load tools/suite.py…; print(len([n for n,s in REGISTRY.items() if s.expect]))"
    13                               # 16 on the merged tree

## Expected

No file states a status for a registered test that differs from what the
registry says, and no file states a bucket's size that the runner would not
print.

## What is actually there

1. **`CLAUDE.md`, "The gate is otherwise clean"** —

   > **The gate is otherwise clean**: `check` 11/11, `coro` 20/20, `stdlib` 2/2,
   > `mojoc` builds, `bootstrap` green through `stage2-cc`.

   `make check` is `suite.py check`, and that bucket holds 21 names plus
   `preflight` (pulled in by the four `deps=['preflight']` members), so the
   runner prints **22 tests**. This sentence is pre-existing: it is unchanged at
   the merge base `f78afc35`, whose `check` bucket has the same 21 members, so
   nothing about this merge made it more false — which is why it was left alone
   rather than rewritten from a registry count, because "11/11" is a claim about
   a *run* (11 tests passed of 11) and only a gate run can establish it.

2. **`CRASH.md` §2, "Blast radius in the gate"** — the table still said

   > | `ab-native` | EXPECTED |

   and the surrounding text said "One root cause makes three registered steps
   red. They are marked `expect=` … and report as EXPECTED". `ab-native` now
   reports `DISABLED` and is not run at all. The rest of that document was
   already overtaken: its headline claim ("`mojoc` segfaults on every input")
   was measured false on 2026-09-27 (`./mojoc --dump-full` on a two-line program
   is exit 0 / 12.1 MB / 94.6 M instructions), and the root cause it names was
   fixed in `e7fc3ece`. It is a handoff from branch `crash`, commit `19bc0dd`,
   and its facts now live in `runtime/fire_runtime.c`'s `_mojo_ptr_shaped` /
   `_mojo_tagged_addr_ok` split and in
   `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`. **Marked SUPERSEDED
   in place in the 2026-09-30 merge commit**, with a banner saying which parts
   still stand (the method in §4, the deployment reasoning in §5) and the
   `ab-native` row corrected to name `disabled=`. Not deleted — see the next
   step.

3. **`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`** — opened with
   "`tools/suite.py --list` shows 16 `EXPECTED-FAIL` tests" and listed
   `ab-native` in the table with its buckets. On the merged tree that number is
   still 16, but three of the sixteen are the `formal-*` host-module suites
   that arrived on master, and the `ab-native` row's marker is `disabled=`.
   **Corrected in the 2026-09-30 merge commit**: the table now carries all six
   gated rows so the 16 reconciles, says which doc owns the ungated group, and
   the "next step" points at `coro`/`x86` by name instead of at an `abtest`
   bucket that does not exist. The merged registry has **16** `expect=` tests
   plus the one `disabled=` job.

   A second doc was added on master for the wider census,
   `bugs/TEST_registered_tests_in_no_bucket_never_run.md` (19 registered tests
   in no bucket, of which these 11 are the `expect=`-marked group). It
   deliberately leaves this group alone and defers to this one, so the two
   partition rather than duplicate — but its own count went stale the moment the
   commit that wrote it also moved five of the seven unmarked ones into a
   bucket, so its Status and census were corrected to **14** in the same commit.

## Exact next step

* For `CLAUDE.md`: whoever runs `make gate` next reads the real tally off
  `build/suite.log` and rewrites that one line from it. **The count to check it
  against moved with master and is now `--dry-run check` = 32, not 22** — the
  `check` bucket gained `suite-self-test`, the four cheapest formal host-module
  suites, `llm-reference` and the four that were registered-but-ungated. The
  sentence has been annotated to say so in place rather than left as a bare
  number nobody can date; only a gate run can supply the real replacement.
* For `CRASH.md`: it documents a fixed bug, and this repo's rule is that a fixed
  bug's doc is deleted rather than left with a Status history, so delete it —
  after checking nothing still needs it as a handoff. The banner added in the
  merge commit says so explicitly and names what a reader loses (§3, the
  root-cause diagnosis). Two `bugs/` docs do cite it
  (`bugs/FORMAL_string_value_model.md` cites "the CRASH.md fix" by *name*, not
  by path, and those citations survive the deletion). **This is the owner's
  call, not a merge's** — it is a top-level file, not a `bugs/` doc, and
  deleting it is a separate decision from keeping its one false row from
  misleading a reader.
* Done, for the record: both no-bucket docs were re-censused with
  `python3 tools/suite.py --list` in the merge commit, and the 19/16/13 numbers
  in them now agree with the registry (14 ungated, 16 `expect=`, 1 `disabled=`).

Worth pairing with a check, for the same reason
`bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md` asks for one: a doc
that names a registered test and states its status is an inventory that can go
stale, and `test_suite.py` already walks the repo for stale `UNREGISTERED`
entries and stale `expect=`/`disabled=` markers. It does not currently walk the
Markdown for a status that disagrees with `REGISTRY`.

This doc is the second time in two merges that the same three files went stale
underneath a change made in none of them, which is the argument for the check
rather than for another merge. The shape it would take: for every registered
name, every Markdown file in the repo that writes it inside a backticked
`| \`name\` |` table row or a `name: STATUS` line has its status word compared
against `REGISTRY` — `expect=`/`EXPECTED` versus `disabled=`/`DISABLED` — and a
mismatch is reported with both the file and the line. The hard part is not the
comparison, it is the false-positive rate: `ab-native` legitimately appears in
prose that is talking about something else, so the check has to be scoped to
lines that already look like a status inventory, and every exemption it needs is
a place the rule was found to be wrong.