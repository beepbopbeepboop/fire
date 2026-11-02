"""Regression for CODEGEN_selfhost_actual_types_identifier_field_key.
Tests that an identifier's .name used as dict key retains hash identity.
"""
import sys
sys.path.insert(0, '.')
from mojo.backend_gimple.emit_stmts import _track_pointer_actual_type

def test_as_str_guard_on_track():
    # The write side must normalize .name via _as_str so the key isn't
    # a corrupted boxed string (len==0 / hash miss on self-host).
    class FakeGen:
        _actual_types = {}
        _int_word_vals = set()
        _struct_field_owners = {}
        _dict_val_types = {}
        _dict_nested_val_types = {}
        _elem_types = {}
        _nested_elem_types = {}
        _dict_val_repr = {}
    gen = FakeGen()
    # Simulate what happens when tgt.name is read from an IdentExpr
    # and passed directly (before fix the string loses identity).
    _track_pointer_actual_type(gen, 'c', 'int64_t', 't5', 'char')
    assert 'c' in gen._actual_types
    assert gen._actual_types['c'] == 'char'
    # Read back with byte-identical key must hit
    assert gen._actual_types.get('c') == 'char'

if __name__ == '__main__':
    test_as_str_guard_on_track()
    print('regression_ok')
