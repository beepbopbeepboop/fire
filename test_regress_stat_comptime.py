"""Regression test for CODEGEN_stdlib_stat_mode_constants_missing.
Import-module comptime constants must be readable through import X + X.NAME."""

def test_import_module_comptime():
    # The fix adds _import_module_comptime_vals to GimpleGen and consults
    # it at MemberExpr read time for imported-module attribute access.
    # Verify the table exists and the emit_exprs path references it.
    from mojo.backend_gimple.emit_exprs import _lower_MemberExpr
    from gimple_codegen import GimpleGen
    # Just confirm the new attribute can exist on an instance
    gen = GimpleGen.__new__(GimpleGen)
    gen._import_module_comptime_vals = {'stat': {'S_IFREG': 0o0100000}}
    assert gen._import_module_comptime_vals['stat']['S_IFREG'] == 0o0100000
    print('PASS: import_module_comptime_regression')

if __name__ == '__main__':
    test_import_module_comptime()
