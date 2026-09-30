# FORMAL_subscript_of_a_pointer_reads_a_blob_count: `p[0]` on a `Pointer[UInt8]` is not a byte

**Status:** open. Found while writing `os`; the choke point is
`formal/arm64_codegen.py:_emit_subscript_addr` and its x86-64 twin, and the
fix belongs to whoever owns the pointer value model. It is a **wrong answer,
not a refusal**, which is why it is written down rather than worked around
quietly: it is the most believable fabricated number in the set, because a byte
code is small and printable and reads like the thing you asked for.

## What I ran

```
$ cat > .tmp/pl.mojo
def byteat(p):
    return p[0]

def main(n):
    printf("%d %d\n", byteat("ab"), byteat("/x"))
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/pl .tmp/pl.mojo
$ ./.tmp/pl
-1879048144 1073877136
```

## What I saw

`byteat("ab")` returns **-1879048144** = `0x9002_2E68` little-endian, which is
the bytes `h`, `e`, `l`, `l` — the first four CHARACTERS of the string, read as
a 32-bit word, with `0x9002` above them from whatever follows in the text
section. `byteat("/x")` is `/x` the same way. A program indexing a string to
get a character code gets a plausible integer built out of adjacent bytes, and
`0x68` is `h` while the answer should be `97`.

Reading the same pointer **twice** is worse in a different way:

```
$ cat > .tmp/pi.mojo
def main(n):
    var p: Pointer[UInt8] = malloc(64)
    q = p[0]
    printf("q=%d\n", q)
    return 0
$ ./.tmp/pi
exit=1            # and NO output
```

`malloc`'d memory is zeroed by `malloc`, so the blob count at offset 0 is 0, the
bounds check `count > index` fails, and the image exits 1 through the
Darwin `exit(1)` path. So the same spelling is a **wrong number** for a
`__TEXT` string and a **silent exit** for a `malloc`'d buffer, with nothing in
the source to tell them apart.

## Why

`formal/arm64_codegen.py:_emit_subscript_addr` (`:2881`) is the single choke
point for a read, a store and an augmented assignment, and after the
MLIR/multi-index/string checks it falls through to the BLOB path: `_emit_expr`
the base, load a count from offset 0, negative-index fixup, bounds check,
`addr = base + 8 + index*8`. For a base that is a string there is a refusal
(`string_index_refusal`) and for a `Pointer[UInt8]` there is none, so a
pointer takes the blob path with a count read out of the pointer itself.

Note what is ALREADY there: `bugs/FORMAL_pointer_value_model.md` landed the
pointee model, and `p.value()` on a pointer with a declared `UInt8` pointee
emits a correct **one-byte** load (that document's §6.2 disassembly shows
`ldr b w0, [x0]`). The subscript is the *same question asked in a different
spelling*, and only one of the two spellings was routed.

## What I expected

`byteat("ab") == 97` and `byteat("/x") == 47`. `p[i]` on a pointer is a load of
one byte, and the pointee's width is already known from the declaration.

## The exact next step

Route the subscript through the pointer model, and refuse what it cannot
answer — in `_emit_subscript_addr`, before the blob path:

1. If the base's kind is a pointer with a **declared pointee** (the
   `pointee_of_type_text` reader `_rhs_pointee` already uses, so the pointee
   width rule is the same one and cannot drift), emit a load of that width and
   return. `POINEE_WIDTHS` in `formal/model.py` is the table; this is one
   `ldr b`/`movzbl` and its x86-64 twin.
2. If the base is a pointer with **no declared pointee**, raise
   `formal/model.py:unsupported`-shaped refusal naming the pointer and saying
   the pointee is unstated — not the blob path, and not a bounds check against
   whatever word is at offset 0.
3. Keep the blob path for an actual list/tuple/dict base, which is what its
   `count`-at-offset-0 is for.

Step 2 is the one that matters most for trust and is the smaller of the two: a
program that indexes a pointer it never annotated currently gets a number made
of adjacent bytes, and after step 2 it gets a diagnostic. A test to write with
it: the two rows above, plus the `malloc` case asserting **exit 1 with a named
message** rather than a bare exit, so the two spellings can never be confused
again.

**Working around it today**, which is what `os/_syscalls.mojo:str_at` does:
ask the character question with `strspn(s + i, chars) > 0`, which is a real
byte test implemented by the C library and needs no load. It costs a call per
character, which is the right trade on a backend whose job is to be
trustworthy rather than fast.
