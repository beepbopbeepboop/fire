"""Regression for bug:CODEGEN_cyclic_closure_from_import_of_a_container_global_with_no_type_yet."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_fixtures', 'cyclic_test')

def test_cyclic_container_import_resolves_owner_field():
    from gimple_codegen import compile_to_gimple
    old = os.getcwd()
    try:
        os.chdir(FIXTURE_DIR)
        src = open('cyc_root.py').read()
        c = compile_to_gimple(src, do_imports=True)
    finally:
        os.chdir(old)
    # Before fix the unknown-identifier fallback emitted (int64_t)0 for NAMES.
    assert '(int64_t)0;  /* ct param or undeclared: NAMES */' not in c, \
        "Cyclic import of container global fell back to 0"
    print("PASS: cyclic container import resolves owner's field")

if __name__ == '__main__':
    test_cyclic_container_import_resolves_owner_field()
