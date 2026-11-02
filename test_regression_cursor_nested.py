"""Regression for CODEGEN_a_materialised_sequence_cursor_needs_nested_element_cursors.
The cursor must read a container element (e.g. MojoList *) as the container
type, not as int64_t. Fails before the itcursor.py fix, passes after."""
import sys
sys.path.insert(0, '.')

from mojo.middle import itcursor

# Before fix: slot_ctype('MojoList *') returned 'int64_t', wrong.
assert itcursor.slot_ctype('MojoList *') == 'MojoList *', \
    f"slot_ctype('MojoList *') = {itcursor.slot_ctype('MojoList *')!r}"
assert itcursor.slot_ctype('MojoDict *') == 'MojoDict *'
# Scalar types unchanged
assert itcursor.slot_ctype('int64_t') == 'int64_t'
assert itcursor.slot_ctype('double') == 'double'
assert itcursor.slot_ctype('char *') == 'char *'

print("PASS: nested-element cursor slot_ctype")
