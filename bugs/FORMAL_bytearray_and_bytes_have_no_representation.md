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
   `bugs/FORMAL_a_pointer_through_a_variadic_argument.md` is blocked behind.

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