# CODEGEN_linked_list_hash_probe_link_error

## Summary
A program that hashes two equal `LinkedList[Int]` values and compares the hashes does not link. The compiled path
emits a call to `_int64_t__get_ref_with_unsafe_interior_origin`, which is never defined. This is the open half of
`CODEGEN_linked_list_hash_stubbed` (the `hash(l)` path), and it hides whether that half works.

## Evidence (2026-11-11)
- Program: `from std.collections import LinkedList`; `var a = LinkedList[Int](1, 2, 3)`; `var b = LinkedList[Int](1, 2, 3)`;
  `print(hash(a) == hash(b))`.
- Master and the branch `work/bug-codegen-linked-list-hash-stubbed` give the same result:
  `gcc -fgimple compilation failed: Undefined symbols ... "_int64_t__get_ref_with_unsafe_interior_origin", referenced from: _LinkedList`.
- The branch's own `test_linked_list_hash_step1.py` passes on master, so the element-hash part is fixed; this link
  error is the `hash(l)` path, which the doc says is still open.

## Repro
The program above, with `python3 fire.py build` or the gimple harness. Expected: prints `True`.

## Status
Open. Not started. First step: find what references `int64_t.__get_ref_with_unsafe_interior_origin` for a generic
struct's `hash` path, and why no definition is emitted.

## Done when
The program above prints `True`, and `CODEGEN_linked_list_hash_stubbed`'s open half is closed. Then delete this doc and
that one in the same commit.
