# Three places state a test's status, and the registry no longer agrees with any of them

Found 2026-09-30 while merging `work/disabled-until-fixed` (which moved
`ab-native` from `expect=` to `disabled=`, see
`bugs/CODEGEN_ab_native_fails.md`). **Not caused by that work for two of the
three, and none of them is a live defect** — nothing computes a verdict from
these strings — but each one is a place a reader is told what the suite is
doing, and all three are now wrong about the same job.

## What I ran

    $ python3 tools/suite.py --dry-run check
    22 tests, 22 jobs, -j18

    $ python3 tools/suite.py --dry-run native
    3 tests, 2 jobs, -j18
    mojoc  (1 job)  [exclusive]
      ab-native  (DISABLED: not run, 0 jobs, reserves 0 GB)  — not run: known to fail …
    native-dumpfull  (1 job)

    $ python3 -c "…load tools/suite.py…; print(len([n for n,s in REGISTRY.items() if s.expect]))"
    13

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

2. **`CRASH.md` §2, "Blast radius in the gate"** — the table still says

   > | `ab-native` | EXPECTED |

   and the surrounding text says "One root cause makes three registered steps
   red. They are marked `expect=` … and report as EXPECTED". `ab-native` now
   reports `DISABLED` and is not run at all. The rest of that document was
   already overtaken: its headline claim ("`mojoc` segfaults on every input")
   was measured false on 2026-09-27 (`./mojoc --dump-full` on a two-line program
   is exit 0 / 12.1 MB / 94.6 M instructions), and the root cause it names was
   fixed in `e7fc3ece`. It is a handoff from branch `crash`, commit `19bc0dd`,
   and its facts now live in `runtime/fire_runtime.c`'s `_mojo_ptr_shaped` /
   `_mojo_tagged_addr_ok` split and in
   `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`.

3. **`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`** — opens with
   "`tools/suite.py --list` shows 16 `EXPECTED-FAIL` tests" and lists `ab-native`
   in the table with its buckets. The merged registry has **13** `expect=` tests
   plus the one `disabled=` job; the other 11 rows of that table are unchanged,
   and its headline finding (11 expect-marked tests in no bucket) is still
   exactly true. Not edited here because `tools/suite.py:estate-registration`
   is another worker's claim and this doc is that work's problem statement.

## Exact next step

* For `CLAUDE.md`: whoever runs `make gate` next reads the real tally off
  `build/suite.log` and rewrites that one line from it. The count to check it
  against is `--dry-run check` (22) — not the member count of `BUCKETS['check']`
  (21), which is not what the runner prints.
* For `CRASH.md`: it documents a fixed bug, and this repo's rule is that a fixed
  bug's doc is deleted rather than left with a Status history, so delete it —
  after checking nothing still needs it as a handoff. Two `bugs/` docs do cite it
  (`bugs/FORMAL_string_value_model.md` cites "the CRASH.md fix" by *name*, not
  by path, and those citations survive the deletion).
* For `bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`: re-measure with
  `python3 tools/suite.py --list` when that doc is next edited; the row for
  `ab-native` should read `disabled=`, and the remaining 11 rows are what the
  doc is about.

Worth pairing with a check, for the same reason
`bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md` asks for one: a doc
that names a registered test and states its status is an inventory that can go
stale, and `test_suite.py` already walks the repo for stale `UNREGISTERED`
entries and stale `expect=`/`disabled=` markers. It does not currently walk the
Markdown for a status that disagrees with `REGISTRY`.