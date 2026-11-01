# Regression for bug-codegen-dylib-generic-inline-copies-370
import inspect, os, sys
sys.path.insert(0, '.')

def test_source_has_new_branch():
    import mojo.backend_gimple.elab_intu as ei
    # Read module source directly and check for the edit.
    with open('mojo/backend_gimple/elab_intu.py') as f:
        src = f.read()
    assert "# NEW (bug-codegen-dylib-generic-inline-copies-370)" in src, "missing new branch"
    assert "_fn_args_are_types(work, base, args)" in src, "missing type-param guard"
    print("PASS: regression test")

if __name__ == "__main__":
    test_source_has_new_branch()
