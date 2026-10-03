# A subscript STORE into a headered blob is accepted, runs, and then aborts in
# the module's own `free`

**Area:** FORMAL (host modules, the blob representation). **Status: OPEN,
measured on both backends, NOT fixed.** Found 2026-10-03 while correcting
`bugs/FORMAL_collections_is_a_type_factory_and_four_containers.md`; the
companion `bugs/FORMAL_a_blob_is_two_conventions.md` carries the rest of that
measurement.

## What I ran

`fire.py build --formal --no-prove` and then **run**, arm64 and x86-64, on a
program that stores an integer into an entry word of a `listdir` blob and then
releases it the documented way.

```mojo
from os import listdir, listdir_len, listdir_free

def main() -> int:
  var names = listdir("<a directory with two entries>")
  printf("before=%d", listdir_len(names))
  names[1] = 5            # word 1 is entry 0's POINTER
  printf("after=%d", listdir_len(names))
  listdir_free(names)     # frees names[1 + i] as a pointer
  printf("freed")
  return 0
```

## What I saw

**Both backends: exit 134, SIGABRT.** `before=2after=2`, then the abort, and
`freed` is never printed. The build is silent — no warning, no refusal, and
nothing in the generated C that says what is wrong.

The mechanism is `formal/hostmods/os/__init__.mojo:504`:

```mojo
def listdir_free(names: Pointer[Int64]) -> int:
  if names == 0:
    return 0
  i = 0
  while i < names[0]:
    free(names[1 + i])     # ← the word the caller just overwrote with 5
    i = i + 1
  free(names)
```

`free(5)` is what aborts. So the caller replaced a `malloc`'d pointer with a
small integer and the module's own release loop then freed it.

## What I expected

One of three things, and none of them is what happened:

1. **A refusal.** The blob's type is `Pointer[Int64]`, which permits any store,
   so there is nowhere for a type-based refusal to come from — but a
   `formal/`-side refusal is exactly what this tree does for the analogous
   cross-image case (`formal/model.py`'s `resolve_frame_parameter_contract`
   refuses a store through a frame-holder parameter), and a blob's entry words
   are as much the module's as a frame's words are the caller's.
2. **An abort at the store.** Not possible: the store is a plain 8-byte write
   into memory the program legitimately has a pointer to.
3. **Nothing, i.e. it works.** A `Counter` on a blob is the case this was
   measured for, and this is what it actually does.

## Why this matters beyond `Counter`

It is a **silent run-time abort for a program the compiler accepted**, in a
module (`os.listdir`) that the gate exercises. That is the shape of bug this
project has been bitten by repeatedly — a wrong-but-exit-0 artifact, or here a
build-clean artifact that aborts on a store the language permits. And the
knowledge needed to avoid it is currently only in `listdir_get`'s docstring
("must NOT be passed to `os_free` on its own"), which is about the *return*
value and says nothing about the blob's own words.

## The exact next step

1. **Publish the contract where the type is.** The dylib manifest already
   carries a per-parameter frame-holder contract for exports
   (`formal/build.py`'s `_frame_param_contract`, read by
   `check_imported_frame_handoffs`). The same mechanism with a second predicate
   — "parameter `p` is a headered blob; its word 0 is the count and its words
   `1 + i` are module-owned pointers, so it is read-only for an importer" — is
   the smallest change that makes the refusal possible at all, and the emitter
   would apply it to `listdir`/`walk` the same way it applies `frame_params`
   today. It is a `formal/build.py` change, which is a shared file, so it wants
   its own pass.
2. **Then refuse the store** in the importer, by name, with a message that says
   which word is the header and which are the pointers. A `Counter`-shaped
   consumer of a blob is the caller this exists for, and it should be told
   "pre-size and use the accessors" rather than left to find a SIGABRT.
3. **Do not "fix" it by making `listdir_free` tolerant.** A `free` that ignores a
   word it does not own would leak every name the caller legitimately replaced,
   and it would turn a loud abort into a silent wrong answer — which
   `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §2 records as the rule
   this project keeps being bitten by.
4. Whatever is done, add the store to `test_formal_os.py`'s `blob` group as a
   case that must be **refused**, replacing the note in
   `bugs/FORMAL_a_blob_is_two_conventions.md` that says the group deliberately
   avoids it.