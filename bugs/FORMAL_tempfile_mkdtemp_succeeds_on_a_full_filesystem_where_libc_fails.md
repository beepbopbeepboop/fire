# TEST_the_tempfile_no_space_group_cannot_build_a_durable_full_filesystem: the image's `mkdtemp` creates a directory where the test's own `mkdir` and libc `mkdtemp` both fail with ENOSPC

**Class:** a gate job's own environment, not a semantic defect in the backend.
**Area:** `test_formal_tempfile.py::group_no_space` and
`formal/hostmods/tempfile.mojo::mkdtemp` / `os/_syscalls.mojo::fs_mkdtemp`.
**Status:** open, measured 2026-10-08 on this worktree at `3bc7d54b`, and
**pre-existing** — it reproduces identically with the two hostmod files taken
from `HEAD~1` (verified, then restored), so it is not the `st_dev` sign fix in
the same file.

## What I ran

`formal-tempfile` is a registered gate job. On this host, with the mandated
`export PATH=/opt/homebrew/bin:$PATH`:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_tempfile.py no-space
FAIL no-space  Failure: [arm64] mkdtemp(prefix=…) answered
  '/Volumes/FORMALFULL/base/probe-xvkErt' into a filesystem with no space left,
  where CPython raised "OSError: [Errno 28] No space left on device:
  '/Volumes/FORMALFULL/base/cpy-4mdgwis5'". …
0/1 groups passed (arm64, x86_64)
```

It is reproducible three times, with and without `memslot`, and it is the ONLY
failure in that file (10/11 groups pass).

## What I measured, and the part that is not yet understood

The group builds its state deliberately: it creates a 24 MB HFS+ image, fills
it 4 KiB at a time until `ENOSPC`, and then checks that `mkdir` still fails
before it claims the state (`_full_filesystem_base`). That check passes here.
Then, in this order, the group:

1. asks the CPython oracle, `CPY_TEMPFILE.mkdtemp(dir=base)`, which raises
   `ENOSPC` — as intended; and
2. builds and runs the image, expecting `mkdtemp(prefix=…)` to answer `""`.

The image answers a real path, and the directory EXISTS:

```console
$ … build --formal --no-prove --backend=arm64 … ; ./p.arm64
base=[/Volumes/FORMALFULL/base]@@made=[/Volumes/FORMALFULL/base/probe-HpLsfr]@@
made exists? True
```

The confusing measurement is that the filesystem is STILL full for every other
caller after the oracle raises, including a fresh libc call from the test
process:

```console
cpy raised 28
after cpy: mkdir probe2 failed 28
ctypes mkdtemp -> None errno 28          # libc mkdtemp(3), same process
mkdir probe3 failed 28
```

So the same `mkdtemp(3)` that fails in the test process succeeds inside the
image's process, on the same volume, at the same time. `os.mkdir` fails for
both. The image's directory is created and visible to the test process.

**The trigger is the CPython oracle call, and that is the surprise**: without
step 1 above (fill + probe + build + run only) the image answers `""`
correctly, reproduced. With step 1 it answers a path, reproduced. So a failed
`os.mkdir` from the test process changes what a later process's `mkdtemp(3)`
does, on an HFS+ image that still refuses the test process's own `mkdir`.

## The exact next step

This is a filesystem-behaviour question before it is a backend question, and the
first thing to settle is which of the two it is:

1. **Determine whether the image's `mkdtemp(3)` is libc's or its own symbol.**
   The image links `tempfile`, `os`, `os_path`, `os__syscalls` dylibs from
   `~/.gmojo/cas/formal-imports/arm64/`, and `formal/hostmods/tempfile.mojo`
   DEFINES a function named `mkdtemp` while `os/_syscalls.mojo::fs_mkdtemp`
   calls a bare `mkdtemp(b)` that is meant to bind libSystem's. If that bare
   call binds the image's own `mkdtemp` instead of libc's, the two are not the
   same function and the whole comparison is about the wrong one. Check the
   emitted call and the linked symbol (`otool -tv` on the cached
   `os__syscalls.*.dylib`, or a `--dump` of `fs_mkdtemp`).
2. **If it IS libc's, measure the HFS+ state from a fresh process before and
   after the oracle call** — a one-line C program, run twice, that calls
   `mkdir` and `mkdtemp` on the filled image. If a fresh process can `mkdtemp`
   where the Python process cannot, the state `_full_filesystem_base` builds is
   not durable across processes and the group's premise is the thing to fix
   (re-establish the state, or skip when it does not hold), not the backend.

Until one of those is answered, this group's assertion is comparing two
different filesystem states and the `FAIL` says nothing about the hostmod.
