"""Pinning regression for bug-compile-fail-tools-c-analyzer-c-analyzer-info (6663).

The one-slot tuple loop target (`for i, in ...` / `[i for i, in ...]`)
used to declare the literal string `'(i,)'` as a C variable name instead
of extracting `i`, producing gcc errors like "expected ')' before ',' token".
Fixed by `_single_loop_target_name` in mojo/middle/loops_shared.py.
"""
from mojo.middle.loops_shared import _single_loop_target_name

def test_single_slot_tuple_target_extracts_name():
    # Before fix: would return None or emit `(i,)` as identifier.
    assert _single_loop_target_name('(i,)') == 'i'
    assert _single_loop_target_name('i') == 'i'
    assert _single_loop_target_name('(a,b)') is None

def test_compr_target_does_not_use_tuple_spelling_as_name():
    # The comprehension result locals (`includes`, `macros`, etc.) must
    # be declared by name, not by the `(i,)` spelling reaching the generator
    # consumer as a variable identifier.
    target = _single_loop_target_name('(patterns,)')
    assert target == 'patterns'
    # Must NOT be the literal tuple spelling
    assert target != '(patterns,)'

if __name__ == '__main__':
    test_single_slot_tuple_target_extracts_name()
    test_compr_target_does_not_use_tuple_spelling_as_name()
    print("PASS: c-analyzer info regression pinned")
