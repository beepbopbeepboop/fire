#!/usr/bin/env python3
"""Pinning regression for commit 658deff0d
The list of dispatch globals used to force EVERY name to MojoDict * because
it could not distinguish dict from set / string / regex. Fixed by the single
_DISPATCH_TABLE_GLOBAL_CTYPES mapping + dispatch_table_global_ctype() accessor.
Deleted with the doc; this verifies the fix is still in place.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mojo.middle.types as gimple_ctypes

# The accessor must exist (was introduced by the fix).
assert hasattr(gimple_ctypes, 'dispatch_table_global_ctype'), \
    "dispatch_table_global_ctype accessor missing — fix not present"

# Dict-valued table globals must stay dict-valued (not coerced to set/string).
for name in ('_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_TYPE_MAP',
             '_SIGNED', '_UNSIGNED', '_FLOAT', '_LIBM_FN_RETVALS',
             '_SELFHOST_EXTRA_FIELD_CACHE'):
    t = gimple_ctypes.dispatch_table_global_ctype(name)
    assert t == 'MojoDict *', f"{name} expected MojoDict *, got {t}"

# Set-valued table globals must stay set-valued (the root-cause failure:
# _CMP_OPS previously answered MojoDict *, causing 'cannot coerce MojoSet *').
for name in ('_CMP_OPS', '_C_KEYWORDS', '_C_RESERVED_FUNCS',
             '_FORCE_RENAME_RESERVED', '_CPP_KEYWORD_FIELDS',
             '_C_PARAM_EXTRA_KEYWORDS', '_PSEUDO_DUNDER_ATTRS',
             '_LIST_RETURNING_METHODS', '_STR_RETURNING_METHODS',
             '_SCALAR_INT_TYPES', '_SCALAR_FLOAT_TYPES'):
    t = gimple_ctypes.dispatch_table_global_ctype(name)
    assert t == 'MojoSet *', f"{name} expected MojoSet *, got {t}"

# Plain-string globals.
for name in ('_CPP_CALLABLE_CTYPE', '_CPP_CALLABLE_CTYPE_1ARG',
             '_UNKNOWN_FIELD_CTYPE'):
    t = gimple_ctypes.dispatch_table_global_ctype(name)
    assert t == 'char *', f"{name} expected char *, got {t}"

# No-typed-accessor / boxed entry.
assert gimple_ctypes.dispatch_table_global_ctype('_FIXED_ARRAY_ANN_RE') == 'int64_t'

# Not a table member -> None (membership and type come from one source).
assert gimple_ctypes.dispatch_table_global_ctype('NOT_A_TABLE_NAME') is None
assert gimple_ctypes.dispatch_table_global_ctype('_STMT_DISPATCH') is not None

# The mapping itself must be a dict, not a tuple, so it can carry types.
assert isinstance(gimple_ctypes._DISPATCH_TABLE_GLOBAL_CTYPES, dict)

# Total coverage: the table must contain exactly all 24 names documented.
expected = 24
actual = len(gimple_ctypes._DISPATCH_TABLE_GLOBAL_CTYPES)
assert actual == expected, f"table has {actual} entries, expected {expected}"

print("PINNING PASS: dispatch_table_global_ctype correct for all table globals")
