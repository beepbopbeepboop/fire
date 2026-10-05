# `selfhost` no longer fails at gcc: the closure LINKS, and the self-hosted binary SIGSEGVs on a two-line program

**State: OPEN, measured, not fixed.** Found 2026-10-04 on `work/merge-formal26`
while merging `work/bugs-segfaults-r2`, whose `mojo/backend_gimple/emit_exprs.py`
is inside the compiled closure and therefore owes the `selfhost` job.
**Pre-existing on master, measured rather than assumed** — see "Not a
regression".

## Where this doc stands against the other `CODEGEN_selfhost_*` docs

The GCC-era docs are GONE, and this paragraph is the reconciliation they owed:
six of them — the ones about a selfhost build red on the branch base, about
"157 distinct gcc errors" on a merged tree, about 13 still remaining, and three
siblings — were consolidated and deleted in `2e9349ed`, because the generated C
now COMPILES AND LINKS and every one of their error counts stopped reproducing.
The survivor is `bugs/CODEGEN_selfhost_closure_compiles_and_the_binary_segfaults.md`,
which carries the same measurement this doc does (the closure builds, the
two-line run is `exit=-11`) from a different tree; this file is the earlier
filing and is kept for the two things that one does not say: the A/B against
master that shows the shape is not a merge regression, and the module-by-module
bisect plan below. Neither cites the deleted names, which is why
`tools/dangling_doc_refs.py --ratchet` is clean on this file.

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label sh -- python3 tools/suite.py selfhost
```

on two trees, each in its own `git worktree`, one merge run each:

```
merged (work/merge-formal26)   selfhost FAIL 569 s  peak 4.3 GB
master  (4b8c27e1)             selfhost FAIL 522 s  peak 4.4 GB
```

Both print the same three lines and stop:

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  dylib module path refuses an unlinkable generated_cpp: True
  self-host closure: 1549 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /…/.tmp/tmpax_k0njb/mojo_selfhost
  self-hosted compiler on a two-line program: exit=-11 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
Results: 1 passed, 1 failed
```

The closure walk, the generator/async lowering and the hand-written signature
table all PASS; `gcc` accepts the generated C; the link succeeds; and the
resulting binary dies of SIGSEGV (exit -11) with no output on a two-line
program. `ci_bytes=0` and `stub_hits=0` are the test's own instrumentation and
they say the crash is not a stub dispatch and left no partial output.

**Master's closure is 1548 functions and the merged one is 1549** — the one
`work/bugs-segfaults-r2` adds. Nothing else in the two summaries differs, which
is the comparison that matters: the merge changed the size of the closure and
not the shape of the failure.

### Not a regression, measured

Both trees fail on the same assertion with the same instrumentation zeros
(`exit=-11 ci_bytes=0 stub_hits=0`), from separate worktrees, on separate runs.
The merge therefore did not bring this red with it, and hunting it as a
regression from five merged branches would be hunting a bug that was already
there. That is the useful part of the measurement: it converts "selfhost is
red" into "selfhost has been red, in this shape, since at least 4b8c27e1".

## What I expect, and what I did not do

I expected the `selfhost` job to be green, because `tools/suite.py` registers
it with **no** `expect=` and no `disabled=` — the registry says this job must
pass, and `bugs/UNTESTED.md`'s status line does not contradict that. Either the
registration is wrong or the binary regressed without anyone noticing.

I did not investigate further: this is a merger, the area belongs to the
self-host/compiled-path work, and the next step is a bisect rather than a
hypothesis — the closure is 62 modules and I have no measurement of which one
the crash is in.

## The exact next step

1. **Bisect the closure by module, not by commit.** The three PASSing lines say
   the problem is after the binary exists, so the useful split is "which of the
   62 modules' generated C, dropped one at a time, makes the binary survive a
   two-line program" — and `test_selfhost.py` already builds a named artifact,
   so a bisect harness over its own output is cheaper than a commit bisect over
   a 522-second job.
2. ~~Reconcile the eight `CODEGEN_selfhost_*` docs.~~ DONE in `2e9349ed`: the
   GCC-error docs are deleted and
   `bugs/CODEGEN_selfhost_closure_compiles_and_the_binary_segfaults.md` carries
   the state, so the only doc-level work left is deleting THIS one when the
   bisect above lands, and its citations with it.
3. **Then decide the registration.** A `selfhost` that cannot run its own
   output is either `expect=`'d with the reason this doc gives (cheap — 0.2 GB
   measured for the sibling, ~4.4 GB here) or fixed. It must not stay
   registered-and-required-green, because that is the state in which a red like
   this one is indistinguishable from a regression.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label sh -- python3 tools/suite.py selfhost
# or, without the runner:
$ python3 tools/memslot.py --gb 8 --label sh -- python3 test_selfhost.py
```