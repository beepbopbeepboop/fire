# FORMAL_hostmod_defaults_left_required_after_the_cross_dylib_fix: the backend applies a callee's defaults across a dylib now, and five hostmods still spell theirs out

**Area:** CODEGEN/FORMAL (Mach-O): the module documentation and signatures in
`formal/hostmods/`, and `formal/imports.py`'s `external_declarations` — the
reader that made the limit go away. Found while making
`work/formal-cross-module` coherent after its five bug docs were deleted.

**Found while:** landing `work/formal-cross-module`, which fixed
`FORMAL_default_argument_not_applied_across_a_dylib` and deleted its doc, and
which changed exactly ONE hostmod signature (`formal/hostmods/struct.mojo`'s
`pack_into`, the one with a test pinning it). The other four hostmods that had
adopted the same workaround were not revisited, so each still says in prose
that a default argument does not survive a dylib boundary. That is now false,
and each cited a doc that no longer exists.

**Status: OPEN, small, deliberately not done here.** The comments are corrected
in the landing commit, so nothing in the tree asserts a falsehood. Restoring the
defaults is left to a worker who can run a sweep, because that is what it needs
to be believed.

## What the fix made true, and where

`formal/imports.py`'s `external_declarations` reads each linked library's
declaration from the path its manifest records, and both emitters now hand that
declaration to the one argument binder (`bind_call_arguments`) instead of
passing `list(e.args)` for an extern callee. So a defaulted parameter is
materialized at the call site and an argument count outside the declared
overloads is a refusal rather than a dropped word.

`test_formal_cross_module.py` is the proof, and it is not a comment: case 3
builds two images of the same source, calls `need_two(1)` at a dylib boundary
and in-image, and requires both to answer 511 where the pre-change build
answered 1867609072 across the boundary.

## What is still spelled as it was

| file | parameter | CPython's default |
|---|---|---|
| `formal/hostmods/os/__init__.mojo` | `mkdir(path, mode)`, `makedirs(path, mode)` | `mode=0o777` |
| `formal/hostmods/os/path/__init__.mojo` | `relpath(path, start)` | `start="."` (actually `os.curdir`) |
| `formal/hostmods/hashlib.mojo` | `blake2b_hex(data, n, digest_size)` | `digest_size=64` |
| `formal/hostmods/time.mojo` | the `strftime`/`strptime` family and `sleep` | per function |

Every one of them is currently REQUIRED, and every one of them has a prose
paragraph in its module docstring explaining that it has to be, because a
default would arrive as a stack address. Those paragraphs are corrected in the
landing commit to say what is now true and to point here. The signatures are
not changed there, and that is the deliberate part.

## Why it was not done in the same commit

Adding a default to a hostmod signature is additive and cannot change an
existing call site's answer — every call site in the corpus passes the argument
— but it changes the PUBLIC SURFACE of five stdlib modules, and the only thing
that would confirm the surface still behaves is a formal sweep: ~45 files,
two architectures, and the `formal-sweep-truth` / `formal-link-accounting`
census. A worker told to run the narrowest thing that shows its change works
cannot run that, and a change verified only by "the comment now says so" is
exactly the kind of belief this repo's docs keep warning against. So the text
is fixed and the code is not, and this doc is the difference between those two
states.

## The exact next step

1. `formal/hostmods/os/__init__.mojo`: `def mkdir(path, mode=0o777)` and the
   same for `makedirs`. `0o777` is CPython's and is masked by the process
   umask, which is the whole of the difference from a literal `0`.
2. `formal/hostmods/os/path/__init__.mojo`: `def relpath(path, start=".")` —
   CPython's default is `os.curdir`, and this module already spells that name
   `curdir()`, so a module-level constant is the spelling to use rather than a
   string.
3. `formal/hostmods/hashlib.mojo`: `def blake2b_hex(data, n, digest_size=64)`.
   BLAKE2b's own `digest_length` is part of the initial state, so 64 is the
   full-length answer and not a truncation of anything.
4. `formal/hostmods/time.mojo`: one at a time, and only where the module's own
   docstring already names CPython's default for it. `getenv`'s is the case that
   was solved a different way (`getenv_or`) and should STAY that way: a
   two-argument form with a name of its own is better than one that silently
   does nothing, and the limit argument no longer applies to it.
5. Then run the sweep and compare the skip counts: `python3 tools/suite.py
   proofs` covers `formal-sweep`, `formal-sweep-truth`, `formal-imports` and
   `formal-link-accounting`, and a module that stops lowering is a `skip` that
   grows rather than a failure.

## The test that has to be extended with it

`test_struct_formal.py` is the precedent and it is the reason `pack_into` was
safe to change: the two cases that had to stop padding to five slots are in
`test_unpack_from_round_trip` and `test_unservable_formats_are_refused_not_wrong`,
and both were changed in the same commit as the signature. For these four the
equivalent is `test_formal_os.py` / `test_formal_hashlib.py` / `test_formal_time.py`,
which already exist and already call the one-argument forms' two-argument
equivalents. Add the omitted-argument spelling beside each existing case, and
compare with CPython the way those files already do — which, note, is also the
step that makes this doc's claims above checkable at all.
