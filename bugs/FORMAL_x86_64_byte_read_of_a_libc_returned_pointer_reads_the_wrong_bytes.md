# FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes: `os.listdir` answers wrongly on x86-64

**Status: OPEN. Found 2026-10-01 while writing
`formal/hostmods/platform.mojo` (the `module:platform+fnmatch+collections-rest`
claim). Pre-existing on master: measured identically on `HEAD~1`, extracted to a
scratch tree and run there. NOT caused by that work, and NOT fixed by it —
`os`'s `_syscalls.mojo` was only extended beside this, and the reads below are
untouched code.**

**It is a SILENT WRONG ANSWER on the x86-64 backend, and it is invisible today
for two reasons that are both in the tree as written: the only test that would
catch it skips x86-64, and the reason it gives for skipping is itself false.**

---

## What I ran, and what came out

The smallest reproducer I found is a 32-byte hex dump of the `struct dirent *`
that `readdir(3)` returns. `formal/hostmods/os/_syscalls.mojo`'s `fs_readdir`
hands back exactly that pointer, and `fs_dirent_name` reads `d_name` out of it
at byte 21 — so dumping 32 bytes shows both the pointer and the field.

`.tmp/exp/rd3.mojo` (the program, in full):

    from os._syscalls import fs_opendir, fs_readdir, str_alloc

    def main() -> int:
        var d = fs_opendir(".tmp/exp/dirtest")
        var e: Pointer[UInt8] = fs_readdir(d)
        var k = 0
        while e != 0 and k < 4:
            printf("k=%lld bytes:", k)
            var i = 0
            while i < 32:
                var q: Pointer[UInt8] = e + i
                printf("%02x", q.value())
                i = i + 1
            printf("@@")
            e = fs_readdir(d)
            k = k + 1
        return 0

against a directory with exactly three files (`aaa.txt`, `bbb.txt`, `ccc.txt`):

    $ python3 fire.py build --formal --no-prove --backend=x86_64 -o rd rd3.mojo
    $ arch -x86_64 rd
    k=0 bytes:43643a030c0004012e0000006db039030c0004022e2e000046643a0310000807
    k=1 bytes:6db039030c0004022e2e000046643a03100008076363632e7478740045643a03
    k=2 bytes:46643a03100008076363632e7478740045643a03100008076262622e74787400
    k=3 bytes:45643a03100008076262622e7478740044643a03...

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o rd rd3.mojo
    $ ./rd
    k=0 bytes:43643a0300000000000000000000000020000100042e00000000000000000000
    k=1 bytes:6db0390300000000000000000000000020000200042e2e000000000000000000
    k=2 bytes:46643a0300000000000000000000000020000700086363632e74787400000000
    k=3 bytes:45643a0300000000000000000000000020000700086262622e74787400000000

The arm64 dumps are **byte-identical to the truth**, which `ctypes` gives
directly from the same `readdir`:

    struct dirent { int64 d_ino; …; uint16 d_reclen; uint16 d_namlen; …; char
    d_name[]; }        # d_name at byte 21

    k=0 bytes: 43643a0300000000000000000000000020000100042e00000000000000000000
    k=1 bytes: 6db0390300000000000000000000000020000200042e2e000000000000000000
    k=2 bytes: 46643a0300000000000000000000000020000700086363632e74787400000000
    k=3 bytes: 45643a0300000000000000000000000020000700086262622e74787400000000

So arm64 reads the struct correctly and x86-64 does not, and the difference is
not a wrong POINTER: the first four bytes of every entry are right (the inode
number), and x86-64's `k=1` is visible inside x86-64's own `k=0` dump — the
stream is shifted, not the base.

## What the wrongness costs, in user-visible answers

`fs_dirent_name` is the only reader, and `os.listdir` is built on it. The same
directory, same tree, `os.listdir(".tmp/exp/dirtest")` + `listdir_get`:

| | arm64 | x86-64 | CPython |
|---|---|---|---|
| `listdir_len` | 3 | **4** | 3 |
| entry 0 | `ccc.txt` | **`cc.txt`** | `ccc.txt` |
| entry 1 | `bbb.txt` | **`""`** | `bbb.txt` |
| entry 2 | `aaa.txt` | **`""`** | `aaa.txt` |

`os.listdir("formal")` behaves the same way: 24 entries correct on arm64, and on
x86-64 a count one too high with garbage names after the first. `os.walk` is
`listdir` applied recursively, so it inherits every one of these. Nothing
crashes, nothing is refused, and the exit status is 0.

## What is NOT the cause, measured

Three candidate spellings, each isolated so the next person does not re-run them:

1. **Not the `Pointer[UInt8]` byte read.** On a `malloc`'d buffer, `b[i]` and
   `b[3 + i]` and `q: Pointer[UInt8] = b + i; q.value()` all read the correct
   bytes on **both** backends (24 bytes of `0xab`/`"0123456789abcdef"` verified).
2. **Not a blob-of-`Int64` element read.** `b[0] = 3; b[1] = "hello"; b[2] =
   "world"` then `b[1]`, `b[2]`, `b[1 + i - 1]`, `b[1 + i]` all correct on both.
3. **Not `fs_dirent_name`'s copy.** Rewriting its body to `memcpy(d, e + 21, i)`
   instead of the byte-at-a-time store gives **the identical wrong string** on
   x86-64, so the defect is in what the read produces, not in how the bytes are
   moved afterwards.

That leaves one discriminator: **the pointer came out of a libSystem call.**
Everything above returns from `malloc`/`str_alloc` and is correct on x86-64;
`readdir(d)` is not. So the next thing to look at is how `formal/x86_64_codegen.py`
lowers a one-byte load through a pointer whose value came from an extern call —
most likely the returned pointer is being spilled or reloaded through a path
that does not preserve it (or a callee-saved register is clobbered between the
extern call and the first load), which is also consistent with the shift being
visible INSIDE a single dump rather than between dumps.

## Why nothing caught it, and the two false claims that did it

Both are in the tree as written and both are wrong; they are recorded here
rather than fixed because neither file is this claim's.

  * `test_formal_os_backing.py:873` registers `listdir_and_walk` as
    `archs=["arm64"]`, and lines 885/900 skip it on x86-64 with the message
    "an `os` dylib that calls the C library is arm64-only on this backend:
    bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md". **That dylib
    does load and run on x86-64**, measured on this tree: a program importing
    `os` and calling `getcwd` builds with `--backend=x86_64` and runs under
    `arch -x86_64`, printing the right cwd. So the skip is protecting against
    nothing, and it is the only reason this bug is invisible. `arch -x86_64`
    is exactly what that file's own `run()` already does for its other cases
    (line 696), so the machinery to un-skip it is in the file.
  * `formal/hostmods/os/_syscalls.mojo`'s docstring says the same thing, and six
    other `formal/hostmods/*.mojo` files repeat it. Those seven claims are stale
    and the citation they all share names a `bugs/` file that does not exist —
    see the last section of `bugs/DOCS_deleted_bug_doc_still_cited_in_three_
    places.md`, where that inventory now lives.

## Exact next step

1. Remove `archs=["arm64"]` from `Case("listdir_and_walk", …)` in
   `test_formal_os_backing.py` and run it on both backends. It should FAIL on
   x86-64, which is the assertion that stops being true: a directory listing
   compared ENTRY BY ENTRY AND IN ORDER against CPython's own is exactly the
   test that sees a truncated `cc.txt`.
2. Then find the extern-returned-pointer bug in `formal/x86_64_codegen.py`. The
   narrowest reproducer is the hex dump above, and the discriminator to keep in
   hand is that the SAME read on a `malloc`'d pointer is correct — so the
   reproducer is `readdir`, not `Pointer[UInt8]`.
3. Once it is fixed, `test_formal_os_backing.py`'s two x86-64 SKIPs and the
   seven stale "arm64-only" claims in `formal/hostmods/` can go, and the
   `readdir`/`opendir`/`stat`-family cross-backend agreement becomes something
   the suite asserts rather than something the tree assumes.