# A deleted bug doc is still cited in two places, and one of them is a test

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

---

Found 2026-09-30 while merging `work/mod-re` (merge `14648b5a`). **Not caused
by that work and not a live defect** — nothing computes anything from these
strings — but it is a dangling reference in a file that exists to be believed,
which is the same class of thing as a stale test name.

## What I ran

    $ grep -rn "FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8" \
          --include=*.md --include=*.py .
    ./bugs/FORMAL_arm64_right_shift_is_always_arithmetic.md:143
    ./test_formal_hashlib.py:32

    $ git ls-tree master --name-only bugs/ | grep -i lsl
    (nothing)

`git log --all --diff-filter=A -- '*FORMAL_arm64_lsl*'` shows the doc was added
by `b2451fe3` and later deleted, which is correct on its own terms: CLAUDE.md
says a doc for a fully-fixed bug is removed rather than left with a Status
history, and the LSL-immediate encoder was fixed on master in `e60ff1d0`
("formal: fix the LSL-immediate encoder and make shifts saturate"), which also
added the 0..63 sweep of all three shift encoders to `test_arm64_encoders.py`.

## Expected

Nothing cites a `bugs/` path that is not in `bugs/`.

## What is actually there

Three citations existed. `work/mod-re` carried its own explanation of the same
bug in `formal/arm64.py` and `test_arm64_encoders.py`, both of which also
describe a bug fixed on master in `e60ff1d0` — so the branch and master had
each written the same comment independently, and the merge had to keep one.
While resolving that I dropped the citation from `test_arm64_encoders.py` and
kept the facts, which is the fix, applied to one of the three.

The other two are untouched and outside that merge's subject:

  * `bugs/FORMAL_arm64_right_shift_is_always_arithmetic.md:143` — a
    "not this one" cross-reference in a doc that is still OPEN, distinguishing
    the right-shift defect from the LSL one it was found alongside.
  * `test_formal_hashlib.py:32` — the same cross-reference, in a test file's
    module docstring, and the one that matters most: a test's docstring is
    documentation a reader trusts, and this one sends them to a file that is
    not there.

## Exact next step

Rewrite both to name the bug rather than the doc — `e60ff1d0`, or the symptom
(`1 << 12` returned `16`; only amounts 1-8 were right) — which is what
`test_arm64_encoders.py` now says after the merge. Then, if the cross-reference
is worth keeping at all, have it point at `test_arm64_encoders.py`'s sweep
comment, which is where the facts now live.

Worth pairing with a check, because this is the third time this shape has
appeared in this tree's own history: a `bugs/*.md` path mentioned in a
`.py` file or another `.md`, verified to exist. It is a five-line walk in
`test_suite.py`, which already walks the repo for `test_*.py` and for stale
`UNREGISTERED` entries — the same "an inventory that can go stale" shape, and
`bugs/` is an inventory.
