# FORMAL_x86_64_dylib_with_an_extern_call_does_not_load: `os` is arm64-only, and it is not `os`

**Status:** open. Found while writing the `os` module; not fixed here, because
it is in the x86-64 dylib emitter and no part of the `mod-os` task owns that.
It is written down because it is the reason a whole, tested, working module is
arm64-only today, and because the message it produces
(`main executable failed strict validation`) is famously unhelpful — it names a
signing symptom rather than the one extra byte.

## What I ran

Two files, and the only difference between them is that one calls the C
library:

```
$ cat > .tmp/xm/b.mojo
def probe():
    return strlen("abc")

$ cat > .tmp/xm/bmain.mojo
from b import probe

def main(n):
    printf("%d@", probe())
    return 0

$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/xm/b .tmp/xm/bmain.mojo
build: bmain.mojo imports 'b', which cannot be built either: b.mojo:
  …/cas/formal-imports/x86_64/b.a80a754e59f0.x86_64.dylib: main executable
  failed strict validation

$ python3 fire.py build --formal --no-prove -o .tmp/xm/ba .tmp/xm/bmain.mojo
Built: …/.tmp/xm/ba  [arm64/macho]
$ ./.tmp/xm/ba
3@
```

With `def probe(): return 2` in `b.mojo` — no extern — the x86-64 build
succeeds. So the boundary is exactly: **a module DYLib on x86-64 that makes an
extern call produces an image the loader refuses.** A module with no extern is
fine; the same module on arm64 is fine.

## What it costs, measured

`os`, `os.path` and `os/_syscalls.mojo` call the C library in every function
they have — `malloc`, `memmove`, `strlen`, `stat`-free but `access`,
`opendir`, `getcwd`, `getenv`, `unlink`. So the whole module is arm64-only:

```
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/x86 .tmp/x86.mojo
build: x86.mojo imports 'os.path', which cannot be built either: _syscalls.mojo:
  …/os_path___syscalls.728aa3f1589a.x86_64.dylib: main executable failed strict validation
```

`test_formal_os.py` therefore exercises one architecture. A module that is
supposed to be the portable half of a compiler cannot be, and the sweep runs
both architectures, so the coverage number for x86-64 gets nothing from this
work at all.

## What I expect, and where it almost certainly is

The message is the one `formal/macho_linker.py` already knows: it is what
`codesign` says when the image has a byte no segment claims, and
`_assert_no_unclaimed_bytes` (`:388`) exists because of exactly that — the
docstring there records the same failure for the arm64 EXECUTABLE path, where
an `LC_LOAD_DYLIB` name slice one byte too wide made `bytearray` *insert*
rather than overwrite and left `__LINKEDIT` one byte short. The dylib emitter
has its own load-command writer, and an extern call is what adds a
`__TEXT,__stubs` entry, a `__DATA_CONST,__got` slot and a bind stream to it —
three more tables whose sizes have to agree with the segment commands on the
x86-64 side.

**The exact next step** is to print the unclaimed bytes rather than assert
there are none: `_assert_no_unclaimed_bytes` already computes `end` and the
declared segment list, so when it fires it should say *which* segment's
`filesize` the tail overshoots and by how many bytes. One run then names the
table, and the fix is a slice width in the x86-64 dylib path rather than a
search. Compare `formal/x86_64_dylib` (if it has since been split out) against
the arm64 dylib emitter's handling of the same three tables, since arm64 is
known good for this exact input.
