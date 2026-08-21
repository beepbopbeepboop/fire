# HARD BUG: struct typedef emission sorts fields ALPHABETICALLY, breaking base/subclass memory-layout compatibility

## Status (found 2026-08-20, not fixed — out of scope for the session that found it)

Found while verifying `bugs/CODEGEN_generator_function_Lib_mailbox.md`'s
and `bugs/CODEGEN_generator_function_Lib_ipaddress.md`'s 2026-08-20
unbound-instance-method arity fix (the `Mailbox.__init__(self, path,
factory, create)` / `IPv4Address.__eq__(self, other)` idiom). That fix
made the unbound-instance-method call SHAPE correct (right argument
count/order at the C call site), but end-to-end runtime verification of
a subclass adding its OWN fields on top of an inherited base exposed
this separate, pre-existing bug.

## Root cause

`_merge_struct_inheritance` (`gimple_codegen.py` ~line 1718) correctly
computes `s.fields = merged_fields + s.fields` for an inheriting struct
— base fields first, own fields after — specifically so that casting a
subclass pointer to its base pointer type (`(Base *)self`, the exact
shape an unbound base-method call like `Base.__init__(self, v)` lowers
to) sees the SAME field layout as a real `Base *`, C-struct-inheritance
style (no vtable in this codegen; layout compatibility IS the
inheritance mechanism for field access through a base-typed pointer).

But there are TWO independent struct-typedef emission paths in
`gen_module` (confirmed by direct trace during this session's
verification):

- **Section 2** (`gen_module`, ~line 39422, `for sd, _ in
  track_best.values(): ... for field in sd.fields:`) — walks
  `sd.fields` directly, in order. Respects the merge's base-first
  ordering correctly.
- **Section 1** (`gen_module`, ~line 38409-38498, the earlier
  `struct_field_types`-keyed pass — "Emit struct typedefs early... This
  includes structs from struct_field_types") — walks
  `sorted(fields.items())`, i.e. **alphabetical field-name order**,
  ignoring `sd.fields`'s (correct, merge-established) order entirely.

Section 1 runs FIRST and marks the struct name in `self._emitted_structs`
(the shared dedup set both sections check), so for any struct with a
`struct_field_types` entry when Section 1 runs (essentially all of
them), Section 1's alphabetically-sorted typedef wins and Section 2's
loop is skipped as already-emitted — silently discarding the correct
ordering Section 2 would have produced.

## Confirmed repro

```mojo
struct Base:
    var val: Int
    fn __init__(out self, v: Int):
        self.val = v

struct Derived(Base):
    var extra: Int
    fn __init__(out self, v: Int, e: Int):
        Base.__init__(self, v)
        self.extra = e

def main():
    var d = Derived(3, 4)
    print(d.val)     # prints 0, should print 3
    print(d.extra)   # prints 4 (correct, by luck of overwrite order)
```

Generated layout (confirmed via direct inspection of the emitted C):

```c
typedef struct Base {
  int64_t __mojo_type_id;
  int64_t val;
} Base;
typedef struct Derived {
  int64_t __mojo_type_id;
  int64_t extra;   /* offset 8 — "e" < "v" alphabetically */
  int64_t val;     /* offset 16 */
} Derived;
```

`Base.__init__(self, v)` (called unbound via `(Base *)self`) writes
`v` to offset 8 (`Base`'s own `val` field lives there) — which in
`Derived`'s actual layout is `extra`, not `val`. `Derived.__init__`
then writes `e` to its own real `extra` offset (also 8), silently
clobbering the value `Base.__init__` just wrote. `Derived`'s real
`val` field (offset 16) is never written, stays 0-initialized.

No crash — silent data corruption. Confirmed via a live trace
(`_merge_struct_inheritance` correctly produces `Derived.fields =
[val, extra]`; a print statement inserted directly into Section 2's own
loop confirms `sd.fields` is STILL `[val, extra]` at that point) that
this is exclusively Section 1's `sorted(fields.items())` at fault, not
a merge-ordering bug.

## Why this wasn't caught before

Any subclass that (a) adds no fields of its own (pure layout passthrough
— trivially safe regardless of sort order), or (b) happens to have
field names that sort in inheritance order by coincidence, or (c) never
has a base method invoked unbound through a `(Base *)self` cast (the
overwhelmingly common case — `super().__init__(...)`-shaped or
implicit-inheritance code never takes this path) — never exercises the
mismatch. The unbound-instance-method idiom fixed alongside this
finding (`Base.method(self, ...)`) is exactly the shape that DOES
depend on layout compatibility, which is presumably why this session's
verification (deliberately testing that idiom with a field-adding
subclass) is what surfaced it.

## Suggested fix direction (not attempted)

Delete Section 1's independent, `struct_field_types`-driven typedef
emission path (or make it walk the same `s.fields`-in-declared-order
representation Section 2 uses, e.g. by iterating a per-struct ordered
field-name list captured at merge time instead of
`sorted(dict.items())`), consolidating on ONE emission path per
CLAUDE.md's "consolidate duplicates rather than maintaining parallel
implementations" convention — Section 1 and Section 2 already dedup
against the same `self._emitted_structs` set and are clearly meant to
be mutually exclusive fallbacks for structs known via different
sources (`struct_field_types` only vs. a real `StructDef.fields` list),
not two independently-correct alternatives; only one of them is
respecting `_merge_struct_inheritance`'s ordering contract. This is a
non-trivial, register-two-different-registries change — not attempted
in the session that found it, flagged here as a real, currently-open,
silent-data-corruption-class bug for anyone touching this call path
next.
