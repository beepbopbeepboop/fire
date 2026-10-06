# FORMAL_a_linked_library_path_is_in_the_image: one image cannot be byte-identical across two CAS roots, and the reason is dyld

**Measured 2026-10-05 on `work/formal38-reproducible-builds`, both backends.**
This is the one axis of the reproducibility sweep that is left, and it is not a
defect in the emitter: it is the load contract.

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

Every differing byte is inside one `LC_LOAD_DYLIB` name:

```
offset 904, 67 568-byte image:
  …/home1.EnYH/cas/formal-imports/arm64/helper.95a751d9e3bc.ab4a34d4f62e.arm64.dylib
  …/home2.uiVV/cas/formal-imports/arm64/helper.95a751d9e3bc.ab4a34d4f62e.arm64.dylib
```

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
* the **directory** is `$GMOJO_HOME/cas/…`, a per-user, per-machine
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
"two trees cannot produce one signature without one path". **The signature half
of that is now closed**: the ad-hoc signature's identifier no longer comes from
the file name (`formal/build.py::_signature_identity`), so two trees at two
paths with one compiler produce one signature. The `LC_LOAD_DYLIB` half is this
document. That doc belongs to another worker's branch and is left alone here.

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
