# FORMAL_tempfile_no_space_answers_a_path_where_cpython_raises

**Status: OPEN, pre-existing (verified against a tree with the fix under test
reversed), and host-specific to this machine's HFS+ behaviour.** Found
2026-10-08 on `work/formal258-docs` while running `test_formal_tempfile.py` as
one of the narrow files covering an unrelated change. It is **not** caused by
that change: the failing program is

```mojo
from tempfile import mkdtemp, gettempdir

def main(n):
    printf("base=[%s]@@", gettempdir())
    printf("made=[%s]@@", mkdtemp(prefix="probe-"))
    return 0
```

which contains no `with`, and reversing the change under test reproduces it
byte for byte.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_tempfile.py
...
FAIL no-space  Failure: [arm64] mkdtemp(prefix=…) answered
  '/Volumes/FORMALFULL/base/probe-Fvfr47' into a filesystem with no space left,
  where CPython raised "OSError: [Errno 28] No space left on device:
  '/Volumes/FORMALFULL/base/cpy-jx70ut5x'". This path has no raise and "" is its
  documented answer for every failure; anything else is a path to a directory
  that does not exist
...
10/11 groups passed (arm64, x86_64)
```

## What I saw

`test_formal_tempfile.py::group_no_space` builds a 24 MB HFS+ image, fills it
until `mkdir` fails, checks `os.mkdir(base/probe)` still fails (so the state is
real), then builds and runs the program above with `TMPDIR=base` on both
backends. CPython's own `mkdtemp(dir=base)` raises `ENOSPC`, as the group
expects. The **image's** `mkdtemp(prefix="probe-")` answers a path
(`/Volumes/FORMALFULL/base/probe-XXXXXX`), which means libc's `mkdtemp(3)`
**succeeded** — `formal/hostmods/os/_syscalls.mojo::fs_mkdtemp` only clears the
string when the C call returns NULL.

## What is expected

`""`, which is what `formal/hostmods/tempfile.mojo::mkdtemp` documents for every
failure and what the group asserts. The two engines must agree.

## Why this is filed rather than fixed here

It is outside this worker's task and not a defect in the lowering: on this host
the filesystem state the group constructs is not actually full for a
subsequent `mkdir`/`mkdtemp(3)`, even though `os.mkdir` from the test process
fails. The HFS+ volume appears to keep room for at least one more directory
entry that the test's 4 KiB fill loop does not consume, so CPython's
`os.mkdir`-based `mkdtemp` sees `ENOSPC` on one name while libc's `mkdtemp(3)`
finds a name it can create.

## The exact next step

Reproduce the state by hand and ask the question the test cannot, on this host:

1. Build the image the way `_full_filesystem_base` does, fill it, and then, from
   **one** process in that directory:
   `os.mkdir(base + "/probe")` (expected to fail),
   `libc.mkdtemp(base + "/zzXXXXXX")` via `ctypes` (the image's call), and
   `open(base + "/zz", "wb")` — to see whether it is `mkdir` specifically or the
   volume that still has room.
2. If libc `mkdtemp` genuinely succeeds where `mkdir` fails, the volume is not
   the state the group names and `_full_filesystem_base` needs a fill that
   leaves **zero** catalog headroom (larger files, or a filesystem that does not
   reserve it) — otherwise the group should degrade to a stated SKIP on this
   host the way an `hdiutil` refusal already does.
3. If it is host-specific (HFS+ free-space accounting), record it as such and
   keep the group host-gated rather than asserting `""` unconditionally.

No code changed for this; nothing about the formal backend's `mkdtemp` lowering
is implicated.
