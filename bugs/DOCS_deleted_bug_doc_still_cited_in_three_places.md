# DOCS: 335 citations of `bugs/` docs that were deleted, and a walk that measures them

*(The filename still says "three places". It named two when it was written and
the walk found 335; renaming it would churn every citation of it, and this
doc's own lesson is that citations outlive their filenames. The first line is
the subject.)*

## SECOND INSTANCE, 2026-10-01 — eleven places, and this one hid a real bug

`bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md` is cited **11
times** and **does not exist**:

    $ ls bugs/ | grep x86_64_dylib
    (nothing)
    $ grep -rn "FORMAL_x86_64_dylib_with_an_extern_call_does_not_load" \
          --include=*.py --include=*.mojo --include=*.md .
    formal/hostmods/os/__init__.mojo:29
    formal/hostmods/os/_syscalls.mojo:55
    formal/hostmods/os/path/__init__.mojo:15
    formal/hostmods/argparse.mojo:116
    formal/hostmods/ast.mojo:194
    formal/hostmods/hashlib.mojo:48
    formal/hostmods/time.mojo:19
    test_formal_os_backing.py:104
    test_formal_argparse.py:705
    test_formal_x86_64_dylib.py:179
    tools/suite.py:2138
    (+ bugs/FORMAL_no_elf_shared_object_emitter.md:38,
       bugs/FORMAL_x86_64_hostmods_that_do_not_build.md:15,53)

Seven of those are in `formal/hostmods/`, and **every one of them uses the
citation to justify the claim that a module dylib which calls the C library is
arm64-only.** That claim was measured FALSE on 2026-10-01: a program importing
`os` and calling `getcwd` builds with `--backend=x86_64` and runs under
`arch -x86_64`, printing the right answer. So this instance is not cosmetic —
it is a deleted doc being cited as the authority for seven stale claims, and one
of those claims is why `test_formal_os_backing.py` skips its `listdir_and_walk`
case on x86-64, which is why
`bugs/FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes.md`
(a silent wrong answer in `os.listdir` on x86-64) has been invisible.

**Exact next step:** correct the seven `formal/hostmods/` claims first (they are
the ones that are false, and the measurement is in that bug doc), then delete
the citation wherever the corrected text no longer needs it, and add the check
this file asks for at the bottom — a `bugs/*.md` path mentioned in a `.py`, a
`.mojo` or another `.md`, verified to exist. Seven of the eleven are in files
one claim owns; the rest are spread across claims that are not mine, which is
why it is recorded here rather than fixed.

**Update, later the same day:** the check this asks for at the bottom landed
with the 335-citation rewrite below — `tools/dangling_doc_refs.py`, wired into
`test_suite.py` — so what remains of this instance is the eleven citations
themselves, not the absence of a walk over them.

---

Found 2026-09-30 while merging `work/mod-re`, with two places named; the walk
that came with the write-up turned out to be a hundred times bigger than that,
so this is rewritten around what is actually there. **Not a live defect** —
nothing computes anything from these strings — but a dangling reference in a
file that exists to be believed, which is the same class of thing as a stale
test name.

CLAUDE.md manufactures them. It deletes a bug doc when a bug is fixed, rather
than leaving it behind with a Status history, and that is the right rule: a
fixed bug still listed is indistinguishable from an open one to whoever reads
the queue next. Every deletion leaves behind whatever cited the doc, and
nothing measured how many citations a deletion invalidates. `3bf50d83` retired
four fixed docs in one commit and left five citations of them.

## What was run

    $ python3 tools/dangling_doc_refs.py
    335 citations of 127 bugs/ docs that are not there, across 110 files

    $ python3 tools/dangling_doc_refs.py --by-file | head -20
      30  test_gimple.py
      20  fire_compiler.py
      16  test_gimple_runner.py
      15  gimple_codegen.py
      …

The walk is `tools/dangling_doc_refs.py`, added with this doc. It reuses
`checked_run.is_derived_dir` for the repo walk, for the reason that function's
docstring gives: two lists of "not part of the repo" are two answers, and they
eventually disagree.

## Expected

Nothing cites a `bugs/` path that is not in `bugs/`.

## What is actually there

Two thirds of the 335 are inside `fire_compiler.py` (20), `gimple_codegen.py`
(15), `formal/` (9 files, 32), `mojo/` (11 files, 46) and `test_gimple*.py`
(46) — the compiler's own source and its largest suites. Those are not this
branch's to edit: they belong to whichever worker owns the area, and a commit
that rewrote 335 citations across all of them would be a merge conflict with
every branch in flight.

The other third is `bugs/` itself (96 citations in 38 docs, nearly all of them
one doc naming another to say "checked and NOT this one"), plus `tools/`
(5), `doc/` (2) and `CRASH.md` (1). Four of those were fixed with this doc's
landing, and the rest are a campaign, not a commit.

## Fixed here

Both places the original write-up named, and two more found while doing it:

* `test_formal_hashlib.py:32` — a module docstring, which is documentation a
  reader trusts, citing three of the four docs `3bf50d83` deleted. It now names
  each of the four defects by SYMPTOM and says where the facts live: the stray
  `immr` bits in the `lsl` base opcode (`test_arm64_encoders.py`'s 0..63 sweep
  comment), the ninth argument the ABI cannot pass (`formal/build.py` emits
  the refusal, `test_formal_run.py` asserts it), `UInt64 >> Int` shifting
  arithmetically (its doc is still open, so it is still cited), and a shift of
  64 or more wrapping instead of saturating (`formal/model.py`'s
  `shift_saturated_is_zero`).
* `bugs/FORMAL_arm64_right_shift_is_always_arithmetic.md:143` — the same
  rewrite, in a "Checked and NOT these, so nobody re-derives it" section that
  exists precisely to be durable, and which was citing two deleted docs.
* `bugs/FORMAL_cross_module_call_arity_is_never_checked.md:148` and
  `bugs/FORMAL_negative_shift_amount_masks_instead_of_raising.md:106` — found
  by the walk, both in the same "not this one" shape, both rewritten.

`formal/model.py:1718` is the one remaining citation of the four retired docs.
It is in the formal tier and not this branch's to edit.

## Why the walk is a tool and not a `check()`

`test_suite.py` runs `tools/dangling_doc_refs.py` — four checks, all green,
all about the WALK rather than the corpus: that it finds a real corpus, that it
does not invent one (a doc this tree cites and that exists is not reported),
that every name it reports really is absent, and that the two citations this
doc named are gone by name rather than by a total that could have gone down for
an unrelated reason. `suite-self-test` gained the tool in its cache key.

What it deliberately does NOT do is fail on the corpus. A `check()` over all
335 would go red on every branch touching `fire_compiler.py`,
`gimple_codegen.py`, `formal/`, `mojo/` or `test_gimple*.py` — for a dangling
citation that branch did not write — and a red check is indistinguishable from
a real regression, which is worse than no check. The same reasoning is recorded
in `tools/suite.py` at the bucket additions for the `expect=`-marked cluster:
a permanently-EXPECTED line in a gate tally is a report nobody reads.

The exemption the walk needs is one line and is not an exception list:
`test_suite.py` is skipped, because it is where a walk for missing files is
guaranteed to find one — the `expect=`/`disabled=` marker checks below
deliberately name `NEVER_WRITTEN.md` and `NO_SUCH_DOC_ANYWHERE.md` to prove they
can fail.

## The next step, in landing order

`--by-file` sorts by count, which is the order to work in: the top file is
three times the next one's citations, and each is a one-line prose fix.

1. `test_gimple.py` (30) and `test_gimple_runner.py` (16) — pure `test_*.py`,
   no compiler area, 46 citations between them. The single highest-value
   commit available and it touches nothing anybody else owns.
2. `bugs/` (96 across 38 docs) — nearly all one doc naming another to rule it
   out, so the fix is mechanical: "not `<deleted doc name>` (fixed, doc
   deleted): `<symptom>`". Still 38 files, and other workers hold most of
   them, so this wants an owner per doc rather than one sweep.
3. The compiler's own source — `fire_compiler.py` (20), `gimple_codegen.py`
   (15), `formal/` (32), `mojo/` (46) — by whoever owns each area, and worth
   filing per area rather than as one commit.
4. When the corpus reaches zero, promote the tool to a `check()`: the walk is
   already the assertion, and the only reason it is not one is the corpus.
   That is the shape `test_suite.py`'s `the buckets:` checks took — a rule
   added when the thing it names stopped existing.

## Related

* This is the third time this shape has appeared in this tree's own history,
  which is what the walk is for. The first two were a test docstring and a doc
  cross-reference; the third is a hundred times the size of either.
* The same "an inventory that can go stale" shape as
  `bugs/DOCS_stated_test_statuses_the_registry_no_longer_has.md` (closed and
  deleted 2026-10-01 with its check in `test_suite.py`, and whose doc was
  itself cited by this one). Both are a file stating something about the
  registry and nothing verifying it; one of the two is now a check.
