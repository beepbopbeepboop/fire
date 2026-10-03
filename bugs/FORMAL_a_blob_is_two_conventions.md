# A blob is TWO conventions, and only one of them is store-safe

**Area:** FORMAL (host modules). **Status: OPEN, measured, not fixed.**

**`FORMAL_collections_is_a_type_factory_and_four_containers.md` was `git rm`'d
on 2026-10-03 (was OPEN, measured, not started); this file is where its
measurement went, and the three steps of its "exact next step" were discharged
as follows.** Say the answer where the reader is (done before this file was
written — `HOST_MODULE_ADVICE`); carry the `counts[2] = 5` measurement rather
than re-derive it (this file, and `test_formal_os.py`'s `blob` group); build
nothing module-shaped (`collections` is not a
`formal/hostmods/collections.mojo`, and below is why that is sharper than it
looked).

**This does not restate
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, which owns
`namedtuple` and is the root cause.**

## What I ran

A stub program per spelling, built with
`fire.py build --formal --no-prove --backend=arm64` and **run**, against
`formal/hostmods/os/_syscalls.mojo` and `formal/hostmods/os/__init__.mojo` —
committed modules, not a scratch blob. It is now `test_formal_os.py`'s `blob`
group (10 facts, both conventions, arm64; `str_alloc`'s half also measured on
x86-64).

## What I saw

**1. A caller CAN subscript-assign into a blob a hostmod returned.** `str_alloc`
mallocs inside the dylib and hands back a pointer; the caller writes with
`p[0] = 65`, reads back `p[0]`, and the module's own `str_put` agrees with what
the caller wrote — one buffer, not two private ones. Measured on **arm64 and
x86-64**, and this is the document's original claim, so it stands.

**2. The local must be ANNOTATED, and the unannotated case fails silently.**
`re.escape` is declared `-> Pointer[UInt8]`; `var annotated: Pointer[UInt8] =
escape("AB")` gives `65, 66` and `var unannotated = escape("AB")` gives
**`0, 0`** while `printf("%s", unannotated)` prints `AB` correctly. This is the
same disease as `bugs/CODEGEN_module_boundary_carries_no_value_types.md` shape 1
— an unannotated binding of a pointer is an integer — and it is the difference
between the blob route working and not, so it is now pinned by the `blob` group
rather than left in prose. `os._syscalls.str_alloc` is declared `-> str`, which
is why its unannotated local *is* a pointer and the trap does not fire there.

**3. There are TWO blob conventions, not one**, and the document this replaces
called it one:

| producer | declared | byte 0 | byte `1 + i` | store-safe |
|---|---|---|---|---|
| `os._syscalls.str_alloc` | `-> str` | a byte | a byte | yes |
| `os.listdir`, `os.walk` | `-> int` | the entry COUNT | entry `i`'s `malloc`'d pointer | **no — see the companion document** |

So "word 0 is the blob's LENGTH, by the convention every blob in this tree
follows" is true of the container blobs and false of the string buffers, and a
reader who took it as universal would think `str_alloc`'s first byte is a count.

**4. A caller's subscript of a `listdir` blob does not read word 0**, measured
704698368 where `listdir_len` says 2 — and the number is a heap address. Same
cause as (2): `listdir` is declared `-> int`, so `var names = listdir(...)` is
an integer and `names[0]` addresses the integer's own storage. So fact (1)
holds for `str_alloc` and does **not** generalise to the container blobs, which
is worth stating plainly because the two are both called "a blob".

## What I expected

One convention, and the store half to be safe in all of it.

## The exact next step

1. **A `collections` hostmod is still not a thing**, and the reason is sharper
   than "eight containers": `Counter`'s `__getitem__` returns 0 for an absent
   key and `counts[k] += 1` inserts on a miss, so it needs dispatch the caller
   has to do itself; its key `0` collides with the header of every container
   blob in the tree; and every method call needs a type this image can see,
   while the blob's type is a `Pointer` declared in another dylib.
2. **If anyone builds the dense pre-sized integer case**, start from fact 1 with
   `str_alloc`-style accessors and an ANNOTATED local, and do not put the
   header in word 0 — the collision in fact 3 is silent, and the store in the
   companion document aborts.
3. **Annotation inference for a call's result** is `CODEGEN`'s and not this
   row's: see `bugs/CODEGEN_module_boundary_carries_no_value_types.md`.