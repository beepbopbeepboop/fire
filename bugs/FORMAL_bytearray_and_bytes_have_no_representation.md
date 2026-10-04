# FORMAL: `bytes()` and `bytearray()` have no representation; a bytes LITERAL does

**Area:** FORMAL — the two backends' type constructors (`formal/model.py`'s
`type_constructor_kind` / `EMPTY_BLOB_CTORS`, and the emitter arm each backend
reaches through them).
**Status: OPEN, measured on `work/formal8-1` (2026-10-02), not fixed here.** It
is the second half of what
`bugs/FORMAL_a_dict_subscript_has_no_value_kind.md` was filed with: that
document's program needs a dict subscript's value kind AND this, and the first
landed.

## What I ran

```console
$ cat t.py
def main():
    var b = bytearray()
    printf("built %d\n", 1)
    return 0
$ python3 fire.py build --formal --no-prove -o t.bin t.py
build: t.bin: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: bytearray. Nothing on this link line defines them: not the
C library, and not any library this program linked. Two very different causes
produce this, and the distinction is not lost — each name in this list is either
a call the codegen emitted … or a name that entered the image as a bare
reference with no call site behind it. Deciding which is a question for the
assembler, and it is asked nowhere in this backend, so this message stops at the
fact both causes share. (Provider check: asked the C library (dlsym).)
```

Measured, all four constructor spellings, both architectures, all four the same
way:

| spelling | result |
|---|---|
| `bytearray()` | dangling `bytearray` |
| `bytearray(3)` | dangling `bytearray` |
| `bytes()` | dangling `bytes` |
| `bytes(3)` | dangling `bytes` |
| **`b'abc'`** | **builds, and `len(b)` answers 3** |

**The literal works, which is the most useful fact here.** So this is not "bytes
have no representation" — the blob a bytes literal builds is a blob this path
already lays out and `len` already reads. What is missing is the CONSTRUCTOR: the
two names are absent from `type_constructor_kind`, whose documented None means
"not a type constructor at all (a genuine function call)", so the call is emitted
as an extern to a symbol no library defines.

## Why the message is the wrong one to stop at

The link-time message is honest about what it found and says nothing about the
cause a reader needs, which is a fact about a TYPE rather than about a symbol.
That is the same shape as a refusal naming a list of names rather than an
explanation, and it is worth fixing at the point of the call: a bare
`bytearray()`/`bytes()` can be refused BY NAME with the reason, exactly as
`List[Int]()` was refused before `EMPTY_BLOB_CTORS` grew — which is a two-line
change and makes every occurrence name itself. It moves no file, and it is worth
doing anyway for the reader.

Three of the tree's own files reach the constructors, so it is not a corner:

| file | spelling |
|---|---|
| `formal/arm64.py:660`, `formal/x86_64.py:794` | `self.sections: dict[str, bytearray] = {"text": bytearray()}` |
| `bugs/FORMAL_a_dict_subscript_has_no_value_kind.md` | the dict subscript above it, whose value kind is now answered |
| `formal/macho_linker.py:226` and the rest of that file | CPython-side `bytearray()` use — listed so nobody re-counts them as formal source |

## The next step, and the question to answer first

The representation is close to free, because the bytes LITERAL already has one.
`bytearray()` is the empty blob — `[count:i64][element 0]…`, the same eight bytes
`_emit_list` builds for `[]` and the same layout `LEN_FROM_BLOB_FIELD` reads — and
`EMPTY_BLOB_CTORS` would grow `bytearray` and `bytes` by DERIVATION once
`BLOB_TYPE_CTORS` carries them (`EMPTY_BLOB_CTORS` is computed from it precisely
so a second hand-kept list cannot go stale).

The hard half is the **element width**, and it is the same question whichever way
the constructor is spelled. `bytearray`'s element is a byte, and every `len` in
the tree counts EIGHT-BYTE slots: a blob of three bytes with a count word of 3 is
24 bytes of memory, and every index read is off by a factor of eight. Note the
bytes LITERAL does not have this problem and neither does the width-1 answer,
which is evidence that this path already treats a bytes value as a blob of words
— i.e. option 1 below is what the tree is already doing, and the question is
whether to keep doing it deliberately. Two honest answers:

1. **A byte is a word on this path** (`_ttype` of an element is `Int8` and the
   slot is 8 bytes). Then `bytearray(n)` reserves `n` slots, `b.extend(1)` costs
   8 bytes per byte, and `b[i] = 300` truncates rather than raising
   `ValueError`. Cheap, and it makes the tree's own `bytearray()` sites work —
   they use it as a growable buffer, not as a byte-exact one.
2. **A byte blob is its own layout** (`[count][bytes…]`, with the element width
   carried in the kind). Then `b"abc"` is three bytes and `b + b` concatenates
   correctly, and `memoryview` / `struct.pack_into` become reachable — which is
   what `formal/hostmods/struct.mojo` needs and what
   `FORMAL_a_pointer_through_a_variadic_argument` is blocked behind.

Option 2 is the one that makes `struct.mojo` and the corpus move, and it is a
new element-width axis on a value model that currently has none — so it is a
design decision with a measurement attached, not a table entry. **A reader should
not assume option 1 is free**: it makes `len(b)` right and `b[i]` wrong by a
factor of eight, and those two disagreeing is worse than either.

**Do not fix it in a host module.** There is no `bytearray.mojo`, and adding one
would be the same non-move `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`
warns about for `collections`: the name resolves, the callers still cannot write
the line, and the failure moves from a link message to a build refusal that
sounds like a fact about the program.
## Status, 2026-10-03 (`formal13-3`): the refusal is landed by NAME; the width decision is not

The second half of the "why the message is the wrong one to stop at" section —
"a bare `bytearray()`/`bytes()` can be refused BY NAME with the reason" — is
done, and it is the whole of what could be done without deciding the element
width. All four spellings, both backends, measured:

    $ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
        --backend=$a -o .tmp/ba/t.bin .tmp/ba/t.mojo; done
    build: constructing bytearray is refused on this path, and the reason is a
    fact about the TYPE rather than about a symbol: a bytearray is a counted
    region, and every counted region here is laid out as `[count:i64][element
    0]…` in EIGHT-BYTE slots — the same blob `[]` is, and the one `len` reads
    its answer from. A byte is one byte, so the element width is the undecided
    part: … Nothing here guesses between those. What this path CAN already do is
    the part that needs no width: a bytes LITERAL is a blob of this layout and
    `len` of it answers 3, so `b"abc"` is not what is missing — the
    CONSTRUCTOR is. …

against the previous answer, which was `the image would bind 1 symbol(s) that
nothing provides …: bytearray` — a statement about the LINK LINE, produced four
stages after the one that could have named the type.

**What changed, and why the message is not the generic one.** `bytearray` and
`bytes` are in `model.UNREPRESENTABLE_TYPE_CTORS`, which is what
`type_constructor_kind` answers `("unsupported", None)` for — so both backends
route them to the one place that already refuses a type with no representation
and neither backend needed an edit to the routing. The TEXT is now
`model.unrepresentable_type_ctor_refusal`, and it has two arms, because the
generic sentence is **false** of these two: it says "a formal value is one
64-bit word … there is no field list to bring up", and a byte blob is neither a
word nor short of a field list — the blob layout is one this path already lays
out (`[]` is it, and `LEN_FROM_BLOB_FIELD` reads it), and the bytes LITERAL
already builds one. Only the element width is undecided, so that is what the
message says, with both candidate answers named. Moving the wording into
`formal/model.py` also removed the two byte-identical copies of it that
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` each carried.

**Not decided, deliberately:** the width. Neither option is adopted, and the
section above is why — option 1 makes `len(b)` right and `b[i]` wrong by a
factor of eight, and two disagreeing answers are worse than either. So this
document stays open, and what is left is exactly the decision it already named.

**Nothing in the corpus moves.** Measured: the 17 `bytes`/`bytearray` spellings
in the new-modular stdlib are all `.bytes()` / `.alignment.bytes()` METHODS, so
no swept file changes class. The tree's own `formal/arm64.py:660` use is
CPython-side, and `formal/hostmods/struct.mojo`'s only mention is in a comment.

Pinned by three cases: `test_formal_run.py`'s `constr_refuse_bytearray_by_name`
(the undecided-width clause, by its words) and
`constr_refuse_bytes_with_an_argument_by_name` (an argument does not make the
width any more decided), and `test_formal_x86_64_parity.py`'s
`bytearray_constructor_refused_identically`, which is the only one of the three
that can see the other backend.
