# CODEGEN: `UnsafePointer[StructType](addr)[0].field` crashes at runtime ("Unhandled exception: AttributeError: `<field>`") in compiled code

## Status

New, found 2026-09-04 while writing user-facing docs on the
`UnsafePointer`/tagged-struct pattern for mmap-style external-memory
interop. Not triaged/fixed, reported per this session's "file bugs you
find" instruction.

## Repro

Reproduces identically whether the pointer's address is a genuine external
address (passed in from outside the process, e.g. from a real `mmap`
region via ctypes) or the address of a local Mojo struct — ruling out
"address didn't really alias" as the cause; this is a dereference/field-
access codegen bug, not an aliasing bug (compare the sibling doc,
`bugs/CODEGEN_unsafepointer_to_kwarg_dropped.md`, which IS an aliasing bug).

**Local-struct case** (`/tmp/t11.mojo` in the session's scratch dir):

```mojo
struct TaggedRecord:
    var tag: Int64
    var as_int: Int64
    var as_float: Float64

fn main():
    var r = TaggedRecord(tag=0, as_int=5, as_float=1.5)
    var p = UnsafePointer(to=r)
    print(p[0].tag)
```

```
$ python3 mojo.py build -o /tmp/t11 /tmp/t11.mojo && /tmp/t11
Unhandled exception: AttributeError: tag
[exited with code 1]
```

(Plain field access on the struct value itself, no pointer involved, works
fine and prints correctly — `var r = TaggedRecord(...); print(r.tag, ...)`
→ `0 5 1.5`, confirming the struct/its constructor are not the problem.)

**External-address case**, via a `mojo dylib` export called from Python
ctypes against a real anonymous `mmap` buffer (`/tmp/t9.mojo` + driver
script in the session's scratch dir):

```mojo
struct TaggedRecord:
    var tag: Int64
    var as_int: Int64
    var as_float: Float64

@export
fn describe(addr: Int) -> Int:
    var rec = UnsafePointer[TaggedRecord](addr)
    if rec[0].tag == 0:
        print("int payload:", rec[0].as_int)
        return rec[0].as_int
    elif rec[0].tag == 1:
        print("float payload:", rec[0].as_float)
        return Int(rec[0].as_float)
    else:
        print("unknown tag")
        return -1

fn main():
    pass
```

Built cleanly (`mojo dylib`), but calling `describe(addr)` against a real
mmap'd buffer laid out with `struct.pack("<qqd", 0, 12345, 0.0)` at that
address raises the identical `Unhandled exception: AttributeError: tag`
from inside the compiled function, before it can even branch on the tag.

For contrast, the **scalar** analog works correctly end-to-end in the exact
same external-address setup: `UnsafePointer[Int64](addr)[0]` /
`UnsafePointer[Int64](addr)[0] = value` round-trip real mmap memory
correctly (read `777` back, then a subsequent write of `424242` was
observed from the Python side after the call returned) — so `UnsafePointer[
ScalarType](addr)` itself, and passing/using an externally-supplied address
in general, are NOT the bug. The bug is specific to a **struct-typed**
pointee: `UnsafePointer[SomeStruct](addr)[0].some_field`.

## Impact

This blocks the natural "define a struct matching your external/mmap data's
C layout, take a pointer to it, read/write named fields" pattern — the most
readable way to do the tagged-struct-over-raw-memory interop this doc's
companion user-facing writeup needed. Current workaround: don't dereference-
then-member-access a struct pointer; instead read/write each field
individually through a `UnsafePointer[ScalarFieldType](addr + byte_offset)`
at the field's own explicit byte offset (confirmed working, see the
external-address paragraph above and the write-up this bug was found while
producing).

## Not root-caused

Not traced into `gimple_codegen.py`/`gimple_gen_exprs.py`'s `MemberExpr`
lowering this session — the "Unhandled exception: AttributeError: `<field>`"
message shape looks like this codegen's dynamic/boxed-object attribute
fallback path (the same style of message the **interpreter**, not the
compiled path, uses for a genuinely-missing attribute), which would suggest
`rec[0]` — subscripting a struct-typed `UnsafePointer` — isn't producing a
real typed struct value/lvalue in the compiled path the way plain
`SomeStruct`-typed locals/params get, and instead falls through to a boxed/
dynamic representation whose runtime attribute lookup then fails. Worth
checking `_lower_pointer_ctor`'s own struct-vs-scalar type resolution
(`gen._resolve_type(f"{base}[{elem_ann}]")`) against how the subsequent
`SubscriptExpr` + `MemberExpr` chain is lowered, but not investigated
further here.
