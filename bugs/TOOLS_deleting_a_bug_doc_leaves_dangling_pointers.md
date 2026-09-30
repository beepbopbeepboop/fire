# TOOLS_deleting_a_bug_doc_leaves_dangling_pointers: 184 places in this tree cite a `bugs/*.md` that does not exist, and nothing checks

**Area:** TOOLS / the repo's own documentation discipline: every `bugs/*.md`
path written into a source comment, a test's docstring or another bug doc.

**Found while:** landing `work/fix-merge-formal-cross-module`, which deleted
five bug docs (correctly — CLAUDE.md: "A doc for a bug that is fully fixed is
deleted, not left behind") and which left, in the two docs it filed in the same
commit, three pointers to two of them. Those three are fixed by that branch.
The seventy other dead targets are not, and the one in this backend is
measured below.

**Status: OPEN, measured, pre-existing on `master`.** Not caused by any branch:
`git cat-file -e master:bugs/FORMAL_toplevel_statements_dropped.md` fails, and
every site below is master's.

## What I ran

```console
$ python3 - <<'PY'   # every `bugs/<name>.md` reference, resolved against bugs/
...                   # 70 distinct targets do not exist, 184 sites in total
PY
$ rg -n 'FORMAL_toplevel_statements_dropped' --glob '!build/**' .
12          # 5 of which are this doc; 7 are real citations
$ python3 tools/memslot.py --gb 8 --label suite-self-test -- python3 test_suite.py
Results: 170 passed, 1 failed
  - the estate: every test file is run by something, or says why not: …
```

The `test_suite.py` line is the neighbouring half of the same hole and is
already filed: `TOOLS_the_test_estate_check_has_been_red_since_eight_formal_
suites_landed`. It checks that every `test_*.py` is run or excused. There is no
such check for the other direction — that every `bugs/*.md` a file CITES still
exists — and `tools/suite.py` has none either.

**The 70/184 is a FLOOR, not a count.** The scan resolves paths written as
`bugs/<name>.md`, and the house convention after a doc is deleted is to name the
SLUG without the prefix (this repo's own rule: a deleted bug's slug stays
findable in the commit that fixed it). Every such citation is invisible to a
path-only scan, and this backend has one on the very doc at issue —
`bugs/FORMAL_module_state_no_storage.md:146` writes
`` `FORMAL_toplevel_statements_dropped.md` `` with no `bugs/` in front. A check
that resolves only the prefixed form would report that site clean, which is the
false negative that matters, so whatever shape it takes has to resolve a bare
slug against `bugs/` too and accept the false positives (`ABI.md`,
`CLAUDE.md` and `PLAN.md` are real files at the root, and a naive scan collects
all three).

## The one in this backend, in full

`6ad8efd5` ("docs: close the top-level-statements bug, file what lowering it
exposed") deleted `bugs/FORMAL_toplevel_statements_dropped.md` and left seven
citations of it:

| site | what it says |
|---|---|
| `formal/build.py:105` | "The whole of the fix for `bugs/FORMAL_toplevel_statements_dropped.md`." |
| `formal/build.py:663` | "That third bullet is the fix for `bugs/FORMAL_toplevel_statements_dropped.md`" |
| `formal/model.py:9350` | a premise's provenance |
| `test_formal_imports.py:590` | a test's docstring |
| `test_formal_toplevel.py:4` | that suite's own docstring |
| `bugs/FORMAL_read_before_store_returns_a_register.md:4` | "…lowered module top-level statements — `bugs/FORMAL_toplevel_statements_dropped.md`" |
| `bugs/FORMAL_module_state_no_storage.md:146` | a sweep census cell, bare slug, no `bugs/` |

The first two are the worst shape, because they are the sentences a future
reader uses to reconstruct WHY a piece of code looks the way it does, and the
answer is now a filename that resolves to nothing. The honest replacement is
the same one this branch used at its own sites: name the slug, say the doc was
deleted and which commit deleted it, and keep the substance of the sentence
that pointed at it — which every one of these seven already has, they just also
carry a dead path.

## Why this is worth a check and not just a sweep

A one-off sweep fixes today's seventy and leaves the mechanism, and the
mechanism is the whole of it: **deleting a bug doc is now the CORRECT action
under CLAUDE.md and it is exactly the action that produces a dangling pointer**,
because the discipline added in the other direction (a fixed bug must not stay
listed) has no counterpart saying that the pointers to it must move with it. So
the number only grows, and it grows in the direction that makes the tree's
provenance unreadable — which is the only reason most of this repo is
navigable.

Two shapes of check would do it, and the cheap one is enough:

1. **A check in `test_suite.py`**, beside `test_every_test_file_is_registered`,
   walking the same file set for `bugs/<name>.md` and asserting each resolves.
   It runs in the `smoke` bucket, so per
   `TOOLS_the_test_estate_check_has_been_red_since_eight_formal_suites_landed`
   §"Why nobody noticed" it will not be run by the gate until that doc's step 2
   is done — so this fix should land in the same commit as the bucket move, or
   at least be written to be run by `python3 test_suite.py` directly, which is
   how it was measured here.
2. **A `pre-commit`-style check on the deletion itself**: refuse `git rm
   bugs/*.md` while any file in the tree still cites the basename, and print
   the citing sites. This is the one that cannot rot, because it fires at the
   only moment the reference can stop existing.

**Not this:** do not "fix" it by restoring the deleted docs. A fixed bug still
listed is indistinguishable from an open one, which is the exact reason those
docs were removed and the reason this doc is about the pointers instead.

## Not this either

- **Not** a stale `UNREGISTERED` entry or a stale `expect=` marker. Both already
  have anti-rot checks that work; those checks are about the *test estate* and
  about *known failures*, and neither can see a comment in `formal/model.py`.
- **Not** worth seventy doc rewrites in one commit. The six FILES this
  backend's area owns (`formal/build.py`, `formal/model.py`,
  `test_formal_imports.py`, `test_formal_toplevel.py` and the two `bugs/` docs
  in the table) are the ones to do first; the rest belong to whoever owns the
  area, which is why the count is reported and not enumerated here.
