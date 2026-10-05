# TEST_formal_imports_three_cases_stop_at_a_refusal_that_moved_earlier: the `reflect` chain is never reached, so the import-diagnosis cases assert a message the build no longer produces

**Area:** `test_formal_imports.py` (three cases in the `TESTS` list) against
`formal/hostmods/os/_syscalls.mojo`'s non-ASCII string-subscript refusal.
Registered as `formal-imports` in the `proofs` bucket — **undeclared, so it is a
real red on this tree.**

**Status: OPEN, pre-existing on master, measured 2026-10-04 on `work/formal28-1`
at `b7b249ac`. Not mine: `formal/hostmods/` and `test_formal_imports.py` are
another worker's area, so this is filed rather than fixed.**

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
formal imports: PASS=69 EXPECTED=0 SKIP=0 FAIL=3
  FAIL  a function-local import is a dependency
  FAIL  widening the imported list widens nothing else
  FAIL  a standard-library module in no tier is not reported as a typo
memcap: done, peak 0.2 GB across up to 2 procs (ceiling 8.0 GB), child exit 1
```

The pre-existing part, measured by reverting this branch's whole diff
(`git diff > patch; git apply -R patch`) and re-running: **the same three, with
the same messages.** So nothing here was caused by the work on this branch.

## What I saw

The message every one of the three prints is the same, and it is about a byte
subscript in a file none of them names:

```
build: test_runtime_header_scan.py imports 'os', which cannot be built either:
_syscalls.mojo: d[i] is refused on a string whose text is not ASCII. A string
here is a bare `char *` to BYTES, so the subscript is `base + index` and what it
reads is one byte — while CPython's `s[i]` is one CHARACTER. …
```

Three cases, three subjects, one cause:

| case | needle | what the build says instead |
|---|---|---|
| `a function-local import is a dependency` | `"imports 'reflect'"` and `"has no home" not in text` | `imports 'os'` — the file is refused one edge BEFORE the `reflect` chain |
| `widening the imported list widens nothing else` | a build that must succeed | the same `d[i]` refusal |
| `a standard-library module in no tier is not reported as a typo` | the shlex/tier table | `import shlex is refused although formal/hostmods/shlex.mojo answers it`, with the same `d[i]` tail — so `shlex.mojo` itself no longer builds |

**The shape is a refusal that MOVED EARLIER in the chain, and it is the same
class as the row that was fixed on this branch**: a case's needle names the
diagnostic its subject produces, and something upstream took the file first. The
difference here is that re-pointing the needle is NOT the fix — see below.

## Why re-pointing the needle is wrong, and what the fix is

`a function-local import is a dependency` asserts three things about
`test_runtime_header_scan.py`: the file is refused, the message names the
IMPORT, and the message does not claim `reflect` has no home. The first and
third still hold (it is refused; "has no home" is gone). The second is the one
that moved, and the file's own refusal now names `os` — an import, so the
diagnosis is still an import diagnosis, just not the one the case pinned.

**The fix is a FIXTURE, not a needle.** The case needs a file whose closure
reaches `reflect` and stops there — i.e. it must not import `os`, or must import
something whose own chain reaches `reflect` without passing `_syscalls.mojo`.
`test_runtime_header_scan.py` is a real 623-file-sweep artifact, which is why it
was chosen, and that is also why it is fragile: it imports whatever the program
under test imported. So the case should build a small tree of its own (the
harness has `write_tree` for exactly this, and `formal/hostmods` has 64 modules
that build), with a function-local `import reflect` and a `reflect.collect_…`
call, and assert the three properties on THAT.

`a standard-library module in no tier is not reported as a typo` is a different
problem and possibly a real one: `shlex.mojo` is refused by a `d[i]` on a
non-ASCII string, and the case's subject is the TIER TABLE (`formal/hostmods/`
versus the stdlib), not whether shlex builds. If shlex no longer builds, the
census's answer changes for every module beside it, so the right check is to ask
the tier table directly (it already has a case:
`no standard-library module is left in neither tier`, PASSING) and to drop the
build requirement from this one — or to record the `d[i]` refusal as the reason,
which is a decision about `formal/hostmods/os/_syscalls.mojo` and belongs to
whoever owns that file.

`widening the imported list widens nothing else` is the third shape: it wants a
build to SUCCEED, so it cannot be satisfied by any needle and needs a fixture
whose imports stay out of `os`.

## The next step, exactly

1. Give each of the three its own fixture tree (or, for the third, a direct
   question about the tier table), so no case depends on which module some other
   file happens to import.
2. Then re-point whatever needle remains stale — which is the ordinary half of
   this job and is one string per case.
3. Do NOT add an `expect=`: three cases in a `proofs`-bucket job would be an
   invisible red for the same reason `formal-receiver-position`'s was
   (`bugs/TEST_formal_receiver_position_expect_marker_outlived_its_three_cases.md`,
   since fixed), and this one is in `proofs` only.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/trhs.bin test_runtime_header_scan.py
```
