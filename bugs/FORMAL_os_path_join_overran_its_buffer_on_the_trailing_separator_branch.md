# FORMAL_os_path_join_overran_its_buffer_on_the_trailing_separator_branch: `str_append(str_dup(a), b)` writes past the end of the allocation, and `join`'s ANSWER is still right

**Status 2026-10-04 (`work/formal20-hostmods-wave3`): FIXED at the root, in
commit `b5ea7787`** — `formal/hostmods/os/path/__init__.mojo::join`'s
trailing-separator branch is `str_build(a, "", b)` instead of
`str_append(str_dup(a), b)`, and `_syscalls.mojo::str_append`'s docstring now
states the in-place contract. This document is kept rather than deleted because
the property it records is a property of the ORACLE, not of one function: **the
whole `test_formal_os.py` corpus passed with the overrun in place, and will pass
again if it is reintroduced**, so what was needed was a caller that could see
the damage and not a bigger corpus. §5 says which.

**Claim** `sweep20:hostmods-wave3` on `work/formal20-hostmods-wave3`. Found
while writing `formal/hostmods/glob.mojo` (this wave's other half); not a `glob`
bug and not claimed by whoever owns `os.path`.

## 1. What it was

`formal/hostmods/os/path/__init__.mojo::join`, third branch:

```mojo
    if str_at(a, str_len(a) - 1, "/") == 1:
        return str_append(str_dup(a), b)      # was
        return str_build(a, "", b)            # now
```

`str_dup(s)` is `str_copy(str_alloc(str_len(s)), s, str_len(s))` and
`str_alloc(n)` is `malloc(n + 1)` — so `str_dup(a)` is a block of
`strlen(a) + 1` bytes: room for `a`, room for its terminator, and nothing else.
`str_append` is `strcat`, which writes `strlen(b) + 1` bytes at
`dst + strlen(dst)`, i.e. starting **at the terminator**. So every byte of `b`
and `b`'s own terminator are written past the end of the allocation:

| | `a` | `b` | allocated | bytes `strcat` touches | past the end by |
|---|---|---|---|---|---|
| measured shape | 36 bytes, ends `/` | 100 bytes | 37 | 101, from offset 36 | **71 bytes** |

`join`'s **answer was correct throughout**. `strcat` appends at the terminator
by design, so the string it leaves behind is the right string; what is wrong is
the 71 bytes it wrote to get there.

## 2. Why every existing test passed, and what that means for the oracle

`test_formal_os.py`'s `strings` group is the differential for `os.path`, and its
`join` corpus is the cross product of `JOIN_FIRSTS` (`"a"`, `"a/b"`, `"/a"`,
`""`, `"."`, **`"a/"`**, `"/"`) with twelve `JOIN_SECONDS` — so **14 of the 84
`join` cases took the overrun branch**, including `join("a/", "b")` and
`join("/", "b/c")`, which are exactly the shapes below. All 84 answers matched
CPython's own `posixpath.join`, before and after the fix, and so do
`test_formal_posixpath.py`'s re-export group and `test_formal_os.py`'s `fs`
group, which reaches `join` through a fixture path.

**A wrong answer is what a differential test can see, and this defect had
none.** The only observable is the damage to whatever the allocator had placed
after the block, which is a property of the heap rather than of the function —
so no corpus over `join`'s inputs can catch it, and §5 is about a different kind
of test rather than a longer list.

Two smaller measurements belong here because they are the shape of the wrong
conclusion:

* **A canary does not catch it either, on this allocator.** A program that
  allocated 40 same-size blocks filled with a known pattern after a
  `join("some/dir/with/slash/", <100 bytes>)` and re-read them found all 40
  intact — on three runs out of three — while the same program **with the fix
  reverted** also found all 40 intact. macOS's allocator had the slack. The
  first version of that canary reported "40 of 40 clobbered" and was measuring
  nothing: its expected checksum was wrong, so every block failed the test
  including the correct ones. The number that looked like the strongest evidence
  for the bug was an arithmetic error in the test.
* **The abort is not deterministic in general.** A single `join` overruns and
  does not abort. What reproduces it is a CALLER that overruns on every entry of
  a walk, which is §3.

## 3. The reproduction: `glob`'s `**`, and why that shape

CPython's `glob._glob2` yields the pattern's own directory first:

```python
def _glob2(dirname, pattern, dir_fd, dironly, include_hidden=False):
    if not dirname or _isdir(dirname, dir_fd):
        yield pattern[:0]              # the EMPTY string
    yield from _rlistdir(dirname, dir_fd, dironly, ...)
```

and `_iglob` joins it onto the pattern's directory — so the first directory
`_glob2` produces ends in `/`, and **every** join `_iglob` does for it is the
trailing-separator branch. Under `recursive=True` that is one overrun per
directory at every level of the tree, which is why this is the shape that turns
a survivable overrun into a heap the allocator stops trusting.

`formal/hostmods/glob.mojo` is a transcription of that structure, so it inherits
the shape exactly. A 20-case probe program over a fixture tree, arm64:

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o probe6 probe6.mojo      # the 20 cases, one image
$ ./probe6 ; echo $?

without the fix   10 runs: 134 134 134 134 134 134 134 134 134 134   (SIGABRT)
with the fix      10 runs:   0   0   0   0   0   0   0   0   0   0
```

and the diagnostic, on the run that aborted:

```
br9(13470,0x1f6c56180) malloc: Heap corruption detected, free list is damaged
                                     at 0x600003d50060
*** Incorrect guard value: 8306754912372
```

`lldb`'s frame at the abort, which is what says the damage is the write rather
than something else:

```
frame #3: nanov2_guard_corruption_detected
frame #4: nanov2_allocate_outlined
frame #5: nanov2_malloc_type_zero_on_alloc
frame #6: os__syscalls....dylib            <- str_alloc / str_build
frame #8: glob....dylib
frame #9: glob....dylib
frame #10: glob....dylib
```

**The blob indices were checked and are not the cause.** With every write in
`_blob_new`, `_glob1`, `_glob2`, `_rlistdir_fill` and `_iglob` instrumented
against its capacity, the abort reproduced with **zero** overruns reported — the
heap was already damaged when the walk started, and the allocator noticed at the
next allocation. That is also how the `glob` bugs were separated from this one
during the session: there were two, a wrong base directory in `_rlistdir_fill`
(fixed in the same commit as the module, and the answers were wrong rather than
the heap) and this one (fixed first, and nothing was wrong until the heap was).

The same run fixed a third defect that was neither: `os.listdir`'s `0` for "no
such directory" reaches a caller as `listdir_len(0) == -1`, and a blob sized by
that is `malloc(0)` with word 0 written past its end. `_glob1` and
`_rlistdir_count` now clamp it to 0, which is what CPython's `_iterdir` does by
swallowing the `OSError` — that one is in `glob.mojo` and needed no change
outside it.

## 4. The fix

```mojo
    if str_at(a, str_len(a) - 1, "/") == 1:
        return str_build(a, "", b)
```

`str_build(a, sep, b)` is `str_alloc(len(a) + len(sep) + len(b))` and three
`str_put`s, so with `sep` empty the allocation is exactly the string plus its
terminator. It is also **one copy fewer**: `str_append(str_dup(a), b)` copies
`a` into a fresh block and then walks it again, where `str_build` writes each
byte once. `str_append` is not wrong and stays in `_syscalls.mojo` — it appends
in place into a `dst` that has the room, and its docstring now says so, with
this measurement as the reason the sentence is there.

`str_append`'s import is dropped from `os/path/__init__.mojo`; it had one caller
and that caller is gone.

## 5. What would catch it, and what this branch did about it

**Not a longer corpus** (§2). The test that has the property is one that puts
the allocator in a position to notice, which means a *caller* that overruns
repeatedly:

> **`test_formal_glob.py`'s `listing` and `hidden` groups are the regression
> test for this defect**, and they are on both backends. They build one image
> over a fixture tree and walk it with `**` under `recursive=True` and with
> `include_hidden=1`, which is the §3 shape: one overrun per directory per
> level. Under the old `join` they abort (`exit != 0`, so `run()` raises and the
> group FAILs with the allocator's own message); under the new one they pass.
>
> That is an honest placement and it is worth saying why it is not circular:
> the test's ORACLE is CPython's `glob`, its cases are glob's rules, and it
> fails for this reason only because the image died. A test that watched
> allocations would be the general answer and there is no allocator
> introspection on this path — `formal/model.py` has no `malloc_size`, and a
> probe for one is refused as a call to a name no module declares.

**The gap this leaves, stated rather than papered over:** a module that
overruns once, in a tree small enough that the allocator has slack, still ships
green. Nothing in this repository catches that today, and `strcat` is the only
unbounded write left in `formal/hostmods/` — measured by grep, `strcat` appears
in `_syscalls.mojo::str_append` and nowhere else, so this fix took the count
from one reachable caller to zero. That is the whole of the remaining
exposure and it is a property of `str_append`'s being callable, not of `join`.

## 6. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
cd "$(git rev-parse --show-toplevel)"

# §3: the 20-case glob probe.  Exit 0 with the fix, SIGABRT without it.
python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
    --no-prove -o .tmp/g/probe6 .tmp/g/probe6.mojo
for i in $(seq 1 10); do .tmp/g/probe6 >/dev/null 2>&1; printf '%s ' $?; done; echo

# §5: the regression test, both backends, ~4 images.
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_glob.py

# §2: the oracle that passes either way, which is the point of §2.
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py strings posixpath
```

`.tmp/g/` is scratch and git-ignored. Nothing here is a `formal_sweep` run, a
whole-closure compile or a lean invocation; the whole measurement is four
single-file builds and some image runs.