# a `Pointer[UInt8]` local's subscript is read as a STRING subscript, so `os._syscalls` no longer imports at all

**Area:** FORMAL — the value-kind machinery (`formal/model.py`'s
`declared_type_kind` / `ValueKinds`) meeting the non-ASCII string refusal
(`model.string_index_refusal`), on both backends. **Found 2026-10-05 on
`work/formal28-6-r2`** while re-measuring
`bugs/FORMAL_trust_audit_2026-10-04.md`'s instrument. **Pre-existing**, and not
on that branch's own changes: it reproduces on this task's base commit
(`77b24183`) with identical output, and `non_ascii_strings` landed in `8de63388`
("a string's length, position and element count CODE POINTS, not bytes"), which
is on `master`.

## What I ran, and what I saw

`test_formal_admitted.py` — the audit's own instrument — is **red on 7 of its 20
rows**, and every one of the seven fails the same way, which is not a wrong
verdict but a refusal to build at all:

```
$ python3 tools/memslot.py --gb 8 --label adm -- python3 test_formal_admitted.py
  FAIL  ctypes      ct: the image did not build.
    build: t_….mojo imports 'ctypes', which cannot be built either:
    _syscalls.mojo: d[i] is refused on a string whose text is not ASCII. …
  FAIL  fcntl       (same)
  FAIL  threading   (same)
  …
admitted contracts: PASS=20 FAIL=7 SKIP=0  (19 declared across 36 hostmod modules)
```

Reproduced byte for byte on this task's base commit (`77b24183`), so it is not a
regression from anything on this branch.

Reduced to four lines, which is where the next step starts:

```
$ cat .tmp/si/q.mojo
from os._syscalls import str_alloc

def main(n) -> int:
    var e: Pointer[UInt8] = str_alloc(64)
    e[0] = 65
    printf("%d", e[0])
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/si/q .tmp/si/q.mojo
build: q.mojo imports 'os._syscalls', which cannot be built either:
_syscalls.mojo: d[i] is refused on a string whose text is not ASCII. …
```

**The damage is not the seven rows: `formal/hostmods/os/_syscalls.mojo` no longer
imports AT ALL**, on either backend, in any program. Every host module that
reaches it is unbuildable, which is `argparse` and everything through it — the
refusal `bugs/FORMAL_type_name_as_a_value.md` §3.1 records for
`tools/detrace_diff.py`, on a path one step further back than that doc measured.

## What it is, exactly

The offending line is in `fs_dirent_name`
(`formal/hostmods/os/_syscalls.mojo:1160`):

```mojo
def fs_dirent_name(e: Pointer[UInt8]) -> str:
    var d: Pointer[UInt8] = str_alloc(1024)
    while e[21 + i] != 0 and i < 1023:
        d[i] = e[21 + i]
```

and the two halves of it are each right on their own. `e` is annotated
`Pointer[UInt8]` and the function's own docstring says the annotation is
"load-bearing: it is what makes `e[21 + i]` a one-byte load rather than a
list-blob walk bounds-checked against the inode number at offset 0". `d` is
annotated the same way and `d[i]` is the same one-byte store. The refusal's own
last sentence names this construct as the way to read a byte on purpose — "with
a `Pointer[UInt8]` subscript and the arithmetic written out" — so the emitter
already agrees.

**The kind of `d` comes from the INITIALISER, and the annotation does not
outrank it.** `str_alloc` is declared `-> str` (correctly: it hands back a
`char *` that `printf("%s", …)` reads), so the value kind of `d` is `STR_KIND`
and `d[i]` reaches `model.string_index_refusal`, which fires because
`non_ascii_strings()` is true for this image — some literal somewhere in the
closure is not ASCII, so `base + 1` could land inside a character.

`formal/model.py::declared_type_kind` is where a local's declared kind is
looked up, and it has **no row for `POINTER_TYPE_CTORS`**. Its rows are the
string names, the float names, the bool names, the int names, the `DType` names,
a framed struct, `BYTE_BLOB_CTORS` and `BLOB_TYPE_CTORS`; a `Pointer[T]`
annotation returns `None` for "unclassified", and an unclassified declaration
loses to the callee's return kind. That is the whole cause, in one sentence:

> **There is no representation for a pointer in `declared_type_kind`, so an
> explicit `Pointer[UInt8]` on a local is weaker evidence than the type its
> initialiser was inferred to have.**

## Why it is not fixed here

Two reasons, and the second is the one that matters.

1. `ValueKinds` has no pointer kind, so this is a new kind rather than a row:
   every consumer of a kind (`is_number_kind`, the string tests, the list/blob
   tests, `len`, `printf`'s conversion switch, both backends' `_load_var`) has to
   answer for it, and a half-answered kind is worse than a missing one — it puts
   a word where a `char *` belongs in exactly the place
   `formal/model.py`'s `pointer_value_model` docstring warns about.
2. `formal/model.py` and `formal/hostmods/` are shared write sets and neither
   `formal/model.py`'s pointer handling nor the hostmod belongs to the claim
   this session was working on. Guessing at a new kind from here is how a
   value-model change lands wrong.

## The exact next step

In order, and each step is checkable without the next one:

1. **Decide what a pointer local's kind should be**, and write down which
   questions it must answer differently from `STR_KIND`. Two candidates, and the
   second is the cheaper one that does not need a new kind:

   * a `POINTER_KIND`, with `POINTEE_WIDTHS` supplying the element width —
     correct, and the width is what `d[i] = e[21 + i]` needs;
   * or a narrow fix at the refusal: `string_index_refusal` must not fire on a
     base whose DECLARED annotation's base name is in `POINTER_TYPE_CTORS`.
     That is one guard and it is exactly true (a pointer subscript is a byte
     load), but it leaves the local still classified as a string, so `len(e)`,
     `printf("%d", e)` and `e + 1` keep whatever answers they have now.
2. **Make the declaration outrank the inferred kind**, which is the second half
   and is worth doing whichever of the two the first step picks: a local with an
   explicit annotation whose `declared_type_kind` is not `None` should not take
   its kind from the initialiser's callee. Check it does not regress
   `bugs/FORMAL_type_name_as_a_value.md` §5's six `DType`-annotated shapes,
   which is the row that made `declared_type_kind` win for a field.
3. **`test_formal_admitted.py` is the acceptance test and it is already
   written**: 20 rows, 7 red, and the seven must go to `PASS=27 FAIL=0`… or
   `PASS=20 FAIL=0`, whichever the truth group counts once the builds work — read
   the count off the run rather than assuming it. Nothing else needs to be
   measured to know the fix landed.
4. **`os._syscalls` importing at all** is the second assertion, because it is the
   larger claim: `formal/hostmods/os/_syscalls.mojo` and `argparse.mojo` build
   and the four-line program above answers `65` on both architectures.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label adm -- python3 test_formal_admitted.py
$ python3 fire.py build --formal --no-prove -o /tmp/q /tmp/q.mojo   # the 4-liner above
```
