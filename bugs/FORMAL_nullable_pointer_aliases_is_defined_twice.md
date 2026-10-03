# `NULLABLE_POINTER_ALIASES` is defined twice, and the first definition is dead

**Area:** `formal/model.py` · **Status:** open, not fixed here — it is outside the
merge this branch is doing and it is in a type table other formal workers hold.
**Found while merging** `work/formal8-9`, `work/formal8-2-r2`, `work/formal8-8-r2`
and `work/formal8-13` into `work/merge-formal8b` (it is on `master` too, and on
all four branches, so no merge caused it).

## What is there

Two module-level assignments to the same name, with different contents:

    formal/model.py:8227   NULLABLE_POINTER_ALIASES = ("OptionalPointer", "OpaquePointer")
    formal/model.py:8949   NULLABLE_POINTER_ALIASES = ("OptionalPointer", "_CPointer")

Python rebinds, so the first one is unreachable and every reader of the name gets
the second tuple. There are exactly two readers:

    formal/model.py:1924   external_call_return_kind()   — the C ABI question
    formal/model.py:9008   nullable_pointer_unwrap()     — the value question

The comment above the FIRST definition says, in its own words, why the two
questions must not share a table:

> the extern-return question is about the C ABI, and the pointer question is
> about a value a Mojo function built. … a future reader adding a nullable
> pointer does not put the name in the wrong table

That separation does not exist in the code: there is one name, the second
definition won, and the comment now describes a property of a line that does
nothing.

## Why it is not visibly broken right now

`POINTER_TYPE_CTORS` already contains all three spellings —

    >>> import formal.model as M
    >>> sorted(M.POINTER_TYPE_CTORS)
    ['CPointer', 'DTypePointer', 'ImmOpaquePointer', 'ImmPointer',
     'MutOpaquePointer', 'MutPointer', 'OpaquePointer', 'OptionalPointer',
     'Pointer', 'Reference', 'UnsafePointer', '_CPointer']

— so `external_call_return_kind`'s `base in NULLABLE_POINTER_ALIASES` arm is
redundant and the shadowing changes nothing it can observe:

    >>> M.external_call_return_kind("OptionalPointer[UInt8, ImmUntrackedOrigin]")
    'word'
    >>> M.external_call_return_kind("OpaquePointer[UInt8, ImmUntrackedOrigin]")
    'word'                      # via POINTER_TYPE_CTORS, not via the alias table
    >>> M.external_call_return_kind("_CPointer[UInt8, ImmUntrackedOrigin]")
    'word'

So there is no wrong answer to point at today. The hazard is the next edit: a
reader who finds the *first* definition and adds a name to it gets a green run
and no behaviour change, and a reader who adds the same name to the second gets
a change that may or may not be what the call site at 1924 wanted — the two
call sites have different questions and one table can only answer one of them.

## Next step

Decide which of the two questions the name is FOR and give each its own
constant, then delete the other. The measured content says the split is:

* the C-ABI one (for `external_call_return_kind`, alongside `POINTER_TYPE_CTORS`
  and `STRING_TYPE_CTORS`): every base whose word IS the register, which is the
  whole of `POINTER_TYPE_CTORS | STRING_TYPE_CTORS` — so that arm may be
  deletable outright once someone checks the extern corpus still answers.
* the unwrap one (for `nullable_pointer_unwrap`): the nullable aliases whose
  `value()` is the UNWRAP, which today is `("OptionalPointer", "_CPointer")`.

Whichever way it goes, the first definition and its "does not put the name in
the wrong table" comment go with it, and `bugs/FORMAL_stdlib_optional_needs_a_
representation.md` (claimed by `formal10-5`) is where the alias question itself
is being worked, so this belongs next to that rather than in a parallel list.

No build is needed to check the outcome: `external_call_return_kind` is a pure
function of its argument, as the transcript above shows.
