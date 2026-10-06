# `formal-os-backing` is registered with NO marker and is red 30 of 58 on `master`

## Status

OPEN, measured, NOT fixed here — pre-existing on `master`, and `tools/suite.py`
is not this worker's write set. Filed because a registered job that is red with
no marker is the specific hole CLAUDE.md's `expect=`/`disabled=` rule exists to
close, and because the number is stable enough to hand over as a claim.

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os_backing.py
FAIL listdir_is_a_python_level_list [arm64]   build failed: one that reads plausible: …
FAIL listdir_is_a_python_level_list [x86_64]  build failed: …
FAIL string_equality_annotated_callee [arm64] …
…
28/58 passed
```

**30 failures of 58**, and all 30 are the SAME refusal, on both
architectures: the formal path refuses to index a string when the text is not
ASCII, because `char *` is bytes and `s[i]` on `"héllo"` would answer with the
byte at the wrong offset (`s[2]` is `l`, and the neighbouring indices' answers
are each other's).

## What I expected

Either green, or an `expect=` marker stating the count. `formal-os-backing` is
registered in `tools/suite.py:2612` with no `expect=` and no `disabled=`:

```python
test('formal-os-backing', [PY, 'test_formal_os_backing.py'], mem='tiny',
     deps=['preflight'],
     extra=[...],
     desc='the syscalls under the os host module, through real images')
```

so it must be GREEN, and it is not — on `master`, not only here.

## Why it is not this merge's

Measured at this merge's own base and after the merge that touched the file:

```console
$ .tmp/tryos.sh 77b24183 base     # -> 28/58 passed
$ .tmp/tryos.sh 8d94b3ee merge2   # -> 28/58 passed
```

`work/bugs5-2` did edit this test file (+177 lines) — its commit `89bbfcd6`
made a SIGKILL'd child report as a kill rather than as a wrong answer, which
changes how a failure is LABELLED, not how many there are. The count is
identical on both sides.

## The exact next step

Two lines of decision, and the first is the cheap one:

1. `expect='30 of 58: every failing case is the non-ASCII string-subscript
   refusal — see <this doc>'` on the registration, which makes the red
   TRACKED and lets the count be checked against the run (the harness reads
   `PASS=`/`FAIL=` out of this file's summary line). If the 30 are genuinely
   one class, that is the honest marker and the doc below is the reason.
2. The underlying gap is a formal-path representation question, not a
   registration one: `s[i]` on a non-ASCII `char *` cannot be answered without
   knowing the encoding, and the refusal's own text says what the path CAN do
   (keep the text ASCII, or read the byte deliberately through a
   `Pointer[UInt8]`). `bugs/FORMAL_string_value_model.md` is where a string's
   representation is argued; a fix belongs there, not here.

Cheap to re-measure either way: 0.1 GB, a few seconds, no Lean.