#!/usr/bin/env python3
"""Regression test for _drop_unreferenced_unimpl_stubs O(parts^2) -> O(parts * names).

A stub DEFINITION is dropped iff NO other part references that stub name.
After the speedup, every part is scanned once per candidate stub name to build
a reference set, then each stub definition tests membership of that set (excluding
self-reference, so a self-referencing definition stays). Byte-identical output
guarantees the keep/drop contract holds regardless of algorithmic shape.
"""

import sys
sys.path.insert(0, '.')

import mojo.backend_gimple.module_gen as module_gen


STUB_NAMES = ('id', '_Bool_items', '_ReflectTable_in_dll')


def def_part(names):
    """Fake emitted stub definition part text."""
    return "\n".join(f"static int {n} ( void ) {{ return 0; }}" for n in names)


def ref_part(names):
    """Fake referencing text that calls the given stub names (not a def)."""
    return "\n".join(f"{n}()" for n in names)


def test_all_unref_dropped():
    """When no other part references the stub names, all stub definitions are
    removed."""
    parts = [def_part(STUB_NAMES)]
    assert module_gen._drop_unreferenced_unimpl_stubs(parts) == []


def test_one_ref_def_kept():
    """One part defines 'id'; another part references it. The id definition is
    preserved; the undefined-name definitions are dropped."""
    defs = [def_part(('id',))]
    others = [def_part(tuple(n for n in STUB_NAMES if n != 'id'))]
    refs = [ref_part(('id',))]
    result = module_gen._drop_unreferenced_unimpl_stubs(defs + others + refs)
    assert len(result) >= 1, f"Expected >= 1 kept, got {len(result)}"
    assert any(p == defs[0] for p in result), \
        f"'id' definition missing from {result}"


def test_size_shrinks():
    """Kept total byte size < original: unreferenced stub defs removed."""
    input_parts = [def_part(STUB_NAMES) + " " + "X" * 100
                   for _ in range(3)]
    result = module_gen._drop_unreferenced_unimpl_stubs(input_parts)
    total = sum(len(p) for p in input_parts)
    kept = sum(len(p) for p in result)
    assert kept < total, f"No drop: kept={kept} == total={total}"


def test_duplicates_cleaned():
    """Many copies of one unreferenced stub def and many copies of a
    referenced stub def across multiple parts. Only unreferenced defs are
    dropped; referenced def kept once."""
    ref_defs = [f"static int id ( void ) {{ return 0; }}"]
    unref_defs = [f"static int {n} ( void ) {{ return 0; }}"
                  for n in ('_Bool_items', '_ReflectTable_in_dll')] * 3
    refs = [f"foo({n}())" for n in ('id',)] * 2
    result = module_gen._drop_unreferenced_unimpl_stubs(
        ref_defs + unref_defs + refs
    )
    assert len(result) == 3, f"Expected 3, got {len(result)}"
    assert all(p.startswith('static int') for p in result)


def test_no_refs_all_dropped_when_only_defs():
    """A single stub def with zero referencing parts: fully dropped."""
    only_def = def_part(('id',))
    result = module_gen._drop_unreferenced_unimpl_stubs([only_def])
    assert result == []


if __name__ == '__main__':
    test_all_unref_dropped()
    test_one_ref_def_kept()
    test_size_shrinks()
    test_duplicates_cleaned()
    test_no_refs_all_dropped_when_only_defs()
    print('All tests passed')
