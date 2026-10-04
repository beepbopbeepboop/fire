# TEST: `TestTheRecursionFamiliesStillGenerate` pins `sum_range` as REFUSED, and the doc it cites says that refusal is fixed

**Area:** tests (`test_formal_call_proof_gen.py`,
`TestTheRecursionFamiliesStillGenerate`). **Status: OPEN, measured, pre-existing
on `master` (4eca3e65), not fixed.** Found 2026-10-04 while merging
`work/formal23-2` into `work/merge-formal23` and running the file. It is NOT
caused by that merge: a pristine archive of `master`'s HEAD reproduces it
identically (§"What I saw", third command), and the fix that closed the refusal
(`work/formal21-6`, "the back edge is discharged by a bottom-tested loop
contract") is already on `master`.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label cpg -- python3 test_formal_call_proof_gen.py
  ...
  Ran 81 tests in 19.718s
  FAILED (failures=1, skipped=5)

# and, to attribute it, on a pristine copy of master rather than on the merge:
$ mkdir -p .tmp/head_tree && git archive HEAD | tar -x -C .tmp/head_tree
$ (cd .tmp/head_tree && python3 test_formal_call_proof_gen.py \
      TestTheRecursionFamiliesStillGenerate)
  ...
  Ran 3 tests in 0.454s
  FAILED (failures=1)
```

## What I saw

```
FAIL: test_the_one_that_refuses_says_why
  (TestTheRecursionFamiliesStillGenerate.test_the_one_that_refuses_says_why)
  (stem='sum_range')
  ...
  self.assertIsNone(
      text, f"{stem} generates now ({err}); delete it from "
            f"REFUSED and say what closed it — the doc this row "
            f"cites names the owner of the fix")
```

arm64 emits a proof for `formal/examples/sum_range.mojo`.

**The row contradicts the document it names, and the document is the one that is
right.** `bugs/FORMAL_sum_range_generation_refused_and_it_is_not_an_expected_
failure.md`'s own first Status paragraph, at line 3:

> **Status (2026-10-04, `work/formal21-6`): the GENERATION refusal is FIXED at the
> root cause … The proof now generates on arm64.** It still does not TYPECHECK,
> for a reason in the walk's SHARED conditional-branch machinery that this branch
> did not take.

So what that doc still owns is the typecheck, and what
`TestTheRecursionFamiliesStillGenerate.REFUSED` pins is the generation — a
distinction the row's own failure message draws and the row itself does not
respect. `REFUSED` (line 2238) says `sum_range` refuses with
`"cbz taken continuation"`, which was the pre-`work/formal21-6` refusal and is
exactly the `ValueError` the doc's §0 records as gone.

The class's docstring makes the same claim in prose (line 2208: "`sum_range` is
the only one of the twelve that still refuses at generation"), so there are two
places to correct and not one.

**Why the row has been able to stay wrong without being noticed.** Nothing runs
this file's Lean, and the two companion rows both pass:

* `test_every_one_of_them_still_generates` — the eleven that do generate, and
  `sum_range` is not among them, so it never reads as "everything generates";
* `test_the_owner_of_the_one_refusal_still_exists` — asserts a
  `bugs/FORMAL_sum_range*.md` exists. It does, because the typecheck half is
  still open. **This row passes for a doc that no longer documents what the row
  pins**, which is the failure mode CLAUDE.md's "a marker whose test starts
  passing is a FAILURE" exists to catch, running the other way.

The file's own rule is generation-only and no-Lean, which is exactly why
generation is the thing it can decide and the typecheck is not; the row is
therefore asking its own file to assert something the file cannot see.

## The exact next step

1. Delete the `sum_range` entry from `TestTheRecursionFamiliesStillGenerate.REFUSED`
   — which empties the dict, so `test_the_one_that_refuses_says_why` and
   `test_the_owner_of_the_one_refusal_still_exists` have nothing to iterate. Merge
   the first into `test_every_one_of_them_still_generates` (add `sum_range` to
   `GENERATE`, which now passes) and delete the second, or keep both classes and
   give them a stem that refuses for a reason this file can still see.
2. Amend the class docstring at line 2208: `sum_range` GENERATES, and the doc
   that names it now owns the typecheck — which this file deliberately does not
   see, and says so.
3. Consider whether `formal/examples/sum_range.mojo` belongs in a census of "the
   corpus examples that generate", because that is the list this class is now
   really maintaining and only eleven of the corpus are in it.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label cpg -- python3 test_formal_call_proof_gen.py \
      TestTheRecursionFamiliesStillGenerate
```