# FORMAL_a_linked_library_path_is_in_the_image: one image cannot be byte-identical across two CAS roots, and the reason is dyld

**Measured 2026-10-05 on `work/formal38-reproducible-builds`, both backends;
re-measured and corrected 2026-10-08 on `work/formal156-docs`.** This is the one
axis of the reproducibility sweep that is left, and it is not a defect in the
emitter: it is the load contract. **Status: OPEN as a limitation, and the
"every differing byte is the load name" claim is WITHDRAWN** — the load path is
the cause, and the uuid and both signature fields differ as well because they
digest the image that carries it (see "What was measured"). No code fix is
available without relocating libraries or changing where they are published, and
the doc's two rejected alternatives are still the only two.

**2026-10-28, re-measured on this tree: the limitation is unchanged and the
pinned property holds — stays OPEN as a limitation.** Ran this doc's named
quick test, `test_formal_reproducible.py`'s `two CAS roots differ only by the
library path`: 6/6 checks PASS on both architectures (one content-addressed
library NAME set for the two roots, same-length images, every differing byte
inside a path-naming load command or the image's own digests). Re-ran the
"What was measured" scenario by hand (an importing program, two same-length
`GMOJO_HOME` roots, `arm64`): `cmp` differs, first at char 809; the images are
49 632 bytes on both sides with **9 differing runs** — 16 B inside `LC_UUID`,
1 B inside `LC_LOAD_DYLIB` (the `home1`/`home2` byte), and the rest inside the
`LC_CODE_SIGNATURE` blob (the `gmojo-<uuid>` identifier hex and the CDHash) —
the same shape the 2026-10-12 table records, with this tree's offsets and run
lengths; the module dylib's content-addressed BASENAME is identical on both
sides. The no-import half is unchanged as well: a program that links nothing
but libSystem builds byte-identical across two roots (`cmp` clean). Nothing the
PROGRAM wrote moves, and the alternatives in "Why it is not fixed here" remain
the only two, both of them design changes this round does not make — so the
remainder is the same and the doc stays open.**

## The corrected byte account (2026-10-12), and why the old one was one byte

The original account was taken when `LC_UUID` was the **all-zero constant** this
backend used to emit, so the only byte a CAS root moved was the one character of
the path — `home1` vs `home2` — inside the `LC_LOAD_DYLIB`. `LC_UUID` is now a
content digest (`test_formal_reproducible.py`'s case 6, `formal/macho_linker.py`'s
`_stamp_content_uuid`) and the ad-hoc signature signs the content, so BOTH
move with the path. Re-measured on this tree, one importing program built from
two same-length CAS roots (`arm64`):

```
differing runs: 9
  run 808:824   len=16  inside=LC_UUID            (a content digest)
  run 958:959   len=1   inside=LC_LOAD_DYLIB      (the "home1"/"home2" byte)
  run 49330:49463 …      inside=LC_CODE_SIGNATURE  (signs the whole image)
same length: 49600 / 49600
the module dylib's content-addressed BASENAME is the same on both sides
```

So the honest sentence is: **every differing byte lies in a load command that
NAMES A PATH, or in a digest that is a function of the image.** Nothing the
PROGRAM wrote moves, and the library's own name does not. That is the property
`test_formal_reproducible.py`'s `two CAS roots differ only by the library path`
pins, by asserting every differing run is inside `LC_LOAD_DYLIB`/`LC_ID_DYLIB`/
`LC_RPATH`/`LC_UUID` or the `LC_CODE_SIGNATURE` blob — a `LC_SEGMENT` that moved
would be a real defect and the case would fail on it.

The DESIGN conclusion is untouched: making the two images equal needs the
library beside the executable (`@executable_path`), which §"Why it is not fixed
here" already weighs and declines as a worker's change.


## What was measured

A program that imports a local module, built twice from one CAS root, is
byte-identical (that is `test_formal_reproducible.py`'s "a program that imports a
module" case, and it passes). Built twice from **two** CAS roots, it is not:

```
$ GMOJO_HOME=$PWD/.tmp/repro/home1 fire.py build --formal --no-prove \
      -o .tmp/repro/mod1/prog.aout -n 10 .tmp/repro/mod1/prog.mojo
$ GMOJO_HOME=$PWD/.tmp/repro/home2 fire.py build --formal --no-prove \
      -o .tmp/repro/mod2/prog.aout -n 10 .tmp/repro/mod2/prog.mojo
$ cmp .tmp/repro/mod1/prog.aout .tmp/repro/mod2/prog.aout
.tmp/repro/mod1/prog.aout .tmp/repro/mod2/prog.aout differ: char 959, line 1
```

**The load path is the CAUSE and it is NOT the only differing byte, and that
sentence had to be corrected.** It used to read "Every differing byte is inside
one `LC_LOAD_DYLIB` name", which is false, and a reader who believed it would
normalise the load command out, compare again, and still find a difference they
had no explanation for. Re-measured 2026-10-08 (`work/formal156-docs`) on a
program that imports a local module: **74 bytes of a 49 616-byte image differ,
in four runs**, and only one of them is the load command itself.
**Re-measured 2026-10-12 (`work/merge-qwen1` merge, same two-`GMOJO_HOME`
setup, `libmod`/`twice` module):** the merged tree's compiler gives a
49 600-byte image with **80 differing bytes** — the SAME four fields, offsets
shifted and the run lengths moved because the two random uuids happen to
collide on different bytes:

| byte run (2026-10-12, merged tree) | where | why it moves |
|---|---|---|
| 16 B at `0x328`, the whole `LC_UUID` (the 10-08 build's two uuids collided on one byte, hence its 15) | load commands | the uuid is a CONTENT digest (`formal/macho_linker.py::_stamp_content_uuid`), and the content it digests carries the load path |
| 1 B at `0x3c1`, `0x31` vs `0x32` — the `home1`/`home2` in the path | load commands | the `$GMOJO_HOME/cas/…` directory — the root cause, and the only byte the old sentence described |
| 32 B scattered in `0xc0b2`–`0xc0d5`, the uuid hex inside the `gmojo-<uuid>` signing identifier | `__LINKEDIT` | `formal/build.py::_signature_identity` is a SHA-256 of the unsigned image, which carries the load path |
| 31 B in `0xc117`–`0xc136` | `__LINKEDIT` | the CodeDirectory/CDHash covers the same image bytes |

The 10-08 table read 15 B at `0x329`, 1 B at `0x3c3`, 24 B at `0xc0c2`, 32 B
at `0xc127`; the difference is which bytes of the two uuids happened to match,
not a change in what moves.

So "the load path is the reason" is true and "the load path is the only
difference" is not: the uuid and both signature fields are **derived** from it.
**A program that links nothing but libSystem does not move at all across two CAS
roots** — measured byte-identical, `cmp` clean — because no real `LC_LOAD_DYLIB`
then names a file under `$GMOJO_HOME`; the derived diffs appear exactly when one
does. That is also why the importing case in `test_formal_reproducible.py` has to
share one `GMOJO_HOME`, and why the no-import cases are stable.

The same is true of the C runtime library, and it reaches every image whose
source calls a word-shaped `mojo_*` name (`formal/build.py::_runtime_word_calls`
— `mojo_print("hi")` is enough, `printf` is not):

```
name …/cas/rtdylib/libmojostdlib.arm64.cba754118176979ebc92c4423071fb6c9ce06a26.dylib
```

Two facts about it are worth separating, because only the second is a choice:

* the **file name** in that path is content-addressed — `helper.<src digest>.
  <compiler digest>.<arch>.dylib` (`formal/imports.py::module_dylib_path`) and
  `libmojostdlib.<arch>.<content digest>.dylib`
  (`build_stdlib_dylib.py::runtime_dylib`). It is the same for two builds on
  one machine and changes when any input changes, which is right;
* the **directory** is `$GMOJO_HOME/cas/…` — the prefix
  `formal/imports.py::module_dylib_path` returns — a per-user, per-machine
  configuration. Two users, two CI workers, or one user with two `GMOJO_HOME`
  settings, produce different bytes for the same source.

## Why it is not fixed here

The path has to be in the image: it is how dyld finds the library, and there is
no way to name a file you have not given a path to. The alternatives were
weighed and both are design changes rather than fixes:

1. **`@rpath/<basename>` plus an `LC_RPATH`.** This is what a dylib's own
   `LC_ID_DYLIB` already says (it is `@rpath/…` today), so the *consumer* half
   is the part that would change. An `LC_RPATH` naming the CAS directory is the
   same absolute directory in a different load command, so it moves the bytes
   rather than removing the dependency — **unless** the rpath is
   `@executable_path`, which requires the library to live BESIDE the
   executable. That is a real option and it is the only one that makes the
   image a function of the source alone; it is also a change to where libraries
   live, which is the shared-CAS design several tests and bug docs depend on
   (`formal/imports.py`'s one-library-per-(module, compiler, arch) cache is
   what makes five worktrees at different commits stop overwriting each
   other's libraries — see `module_dylib_path`'s own docstring). Not a worker's
   side change.
2. **Copy the library next to the executable** and record
   `@rpath/<basename>`. Same trade, plus a copy step on the publish path, plus
   the `manifest.json` beside it, plus `formal/imports.py::dylib_chain`'s
   assumption that a dependency lives in the CAS.

## What a consumer does about it today

* Compare two images of a program that links nothing but libSystem — that is
  every program in `formal/examples/*.mojo`, and
  `test_formal_reproducible.py` does exactly that.
* For a program that links a library, either give both builds the **same**
  `GMOJO_HOME` (what the test does, and why its docstring says so), or compare
  with the load command normalised out. Nothing else in the image moves: with
  one CAS root, the importing program's image and its module dylib are both
  byte-identical, measured.

## Related, and NOT open any more

`bugs/FORMAL_pointer_value_model.md` §"Three of those BUILD" recorded the same
cluster from the other direction — two worktrees at two paths, 12 bytes inside
an `LC_LOAD_DYLIB` name and 31 inside the `LC_CODE_SIGNATURE` — and concluded
"two trees cannot produce one signature without one path". **The half that is
closed is the identifier's SPELLING**: the ad-hoc signature's identifier no
longer comes from the file name (`formal/build.py::_signature_identity`), so two
trees at two paths with one compiler and ONE CAS produce one signature. **What is
not closed — and the correction above is the measurement — is that the signature
still moves when the signed image does**: the identifier is a SHA-256 of that
image, so when the two trees use two `GMOJO_HOME`s the load path changes, the
image changes, and the identifier (and the CDHash beside it) changes with it. The
`LC_LOAD_DYLIB` half is this document, and the signature half is a consequence of
it rather than a second axis. That doc belongs to another worker's branch and is
left alone here.

## The CAS key

`cas.formal_build_key` caches a **verdict** (`ok, detail`), not an image, and a
verdict does not depend on the CAS root: the library's location decides which
symbols the image binds and whether the load succeeds, and both of those are
decided by the modules' *contents*, which the key already folds in through
`imports=import_closure_digest(path)` (`test_formal_sweep_cache_key.py` pins
that clause, including the `formal/hostmods/*.mojo` case that motivated it).
Checked here and not a hole. The `fmt` argument of `compile_formal` is not in
the key either, and needs no clause: `fmt` is `default_format(arch)`, a pure
function of the platform, and `toolchain_fingerprint` folds
`platform.system()/platform.machine()`.
