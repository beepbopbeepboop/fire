# FORMAL_x86_64_dylib_externs_unsigned: an x86-64 module dylib that calls libSystem cannot be codesigned, so no program importing it can be built for that target

**Status: OPEN. Pre-existing, not caused by the `sys` module work, and reproduced
by a two-line module that has nothing to do with `sys`. Every x86-64 program that
links a module which calls out — which is most of them, since almost every real
module calls `strlen` — is unbuildable on that target today.**

Found while writing `sys.mojo` (2026-09-29, the `module:sys` claim), at
`ca6e758`. Reproduced with the export-trie change stashed, so it is not that
either.

---

## What I ran

```console
$ cat x86e.mojo
def emit(s: str) -> int:
  return write(2, s, strlen(s))

$ cat x86ep.mojo
import x86e

def main():
  print(x86e.emit("hi\n"))
  return 0

$ python3 fire.py build --formal --no-prove --backend=x86_64 \
      -o x86ep.aout x86ep.mojo
build: x86ep.mojo imports 'x86e', which cannot be built either: x86e.mojo:
  .../cas/formal-imports/x86_64/x86e.<digest>.x86_64.dylib: main executable
  failed strict validation
```

The same two files on arm64:

```console
$ python3 fire.py build --formal --no-prove -o x86ep.aout x86ep.mojo
Built: x86ep.aout  [arm64/macho]
$ ./x86ep.aout
hi\n4
```

And a module with **no** extern calls builds for x86-64 and runs, so the failure
is the extern machinery and not the dylib path:

```console
$ cat x86m.mojo
def aa() -> int:
  return 1
$ cat x86p.mojo
import x86m

def main():
  print(x86m.aa())
  return 0
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o x86p.aout x86p.mojo
Built: x86p.aout  [x86_64/macho]        # and it prints 1
```

## Why it matters here, and what it cost this task

`sys.mojo` calls `write`, `strlen` and `fflush`, so **on x86-64 no program can
import `sys` at all**. `test_formal_sys.py` therefore runs the `sys` end-to-end
assertions on arm64 and covers the cross-architecture half of the module-call
contract with a module that makes no extern calls
(`test_the_dotted_spelling_runs_on_both_backends` — `lefty`/`righty`, both
architectures, both print the right strings). When this is fixed, the `sys` test
should go back to both architectures; the test says so at its own definition.

## The message, and what it is

`codesign -s -` refuses the image with `main executable failed strict
validation`. That is dyld's own validation of the load commands and segments, and
this tree already knows the message from the other direction — see
`formal/macho_linker.py`'s `_assert_no_unclaimed_bytes` ("that one unclaimed byte
was the whole reason the extern path could not be built") and the
`LC_BUILD_VERSION` comment beside it ("dyld has no declared platform/minimum OS
to validate the load commands against").

So the first thing to do is the one that worked before: get dyld's own reason
rather than its summary.

```console
$ DYLD_PRINT_APIS=1 DYLD_PRINT_INITIALIZERS=1 codesign -s - <the dylib>
```

and compare the image's `__TEXT`/`__DATA_CONST`/`__LINKEDIT` layout and
`LC_LOAD_DYLIB` list against the arm64 dylib for the same source, which signs
and runs. The three candidates I would look at, in order, all of them specific to
the x86-64 emitter rather than to the container:

1. **Alignment.** `formal/x86_64.py`'s stub is 6 bytes (`JMPQ *disp32(%rip)`) and
   `build_macho_dylib` packs `stub_file = (code_file + len(code) + 3) & ~3` and
   `ssize = spec["stub_size"]`. A `__TEXT,__stubs` section whose entries are not
   16-byte aligned is accepted on arm64 (12-byte entries) and is exactly the kind
   of thing x86-64's stricter validation rejects. Compare `__stubs`' `addr`/`size`
   modulo 16 between the two architectures' dylibs for one source.
2. **The `__DATA_CONST,__got` size.** `data_size = _align_up(8 * n, PAGE_SIZE)`
   with `got_base_vm = TEXT_BASE + data_file`; on x86-64 the GOT indirects are
   RIP-relative, so a `__got` whose `vmsize` does not cover the last slot
   computes an address outside the segment and fails validation.
3. **The bind stream's opcode count.** `_bind_info` is shared, so this is less
   likely, but `n = len(external_syms)` for the x86-64 dylib is worth printing
   next to arm64's for the same source.

`_assert_no_unclaimed_bytes` already runs on this path and did not fire, so the
file is not longer than its segments claim — the defect is inside a segment, not
past the end of one.

## The exact next step

Add the x86-64 extern dylib to `test_formal_dylib.py` as a case that builds it
and `dlopen()`s it (the file already has `build_dylib` and `call_exported` for
exactly this), with the two-line module above as the source. It will fail at the
`codesign` inside `build_dylib` with the message above, which is the assertion
that makes the failure visible without a human reading a build log; then bisect
the three candidates with the `DYLD_PRINT_*` run.
