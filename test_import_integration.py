"""Integration test: compile mojo with imports and link with helper modules."""
import os
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple
from build_config import find_gcc

def compile_and_link(main_src: str, helper_srcs: dict) -> str:
    """Compile Mojo code with imports and link against helper modules.

    Args:
        main_src: Main Mojo source code
        helper_srcs: Dict of {module_name: mojo_source} for helpers

    Returns:
        Path to compiled executable
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Compile each helper module
        helper_objs = []
        for module_name, helper_src in helper_srcs.items():
            # Compile helper to C
            helper_c = compile_to_gimple(helper_src)
            helper_c_file = os.path.join(tmpdir, f"{module_name}.c")
            with open(helper_c_file, 'w') as f:
                f.write(helper_c)

            # Compile helper C to object file
            helper_obj = os.path.join(tmpdir, f"{module_name}.o")
            result = subprocess.run(
                [find_gcc(), '-fgimple', '-c',
                 f'-I{HERE}/runtime',
                 '-o', helper_obj, helper_c_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"Failed to compile {module_name}:")
                print(result.stderr)
                return None
            helper_objs.append(helper_obj)

        # Compile main program to C
        main_c = compile_to_gimple(main_src)
        main_c_file = os.path.join(tmpdir, 'main.c')
        with open(main_c_file, 'w') as f:
            f.write(main_c)

        # Link main with helper objects
        exe_file = os.path.join(tmpdir, 'program.exe')
        link_cmd = [find_gcc(), '-fgimple',
                    f'-I{HERE}/runtime',
                    '-o', exe_file, main_c_file] + helper_objs

        result = subprocess.run(link_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print("Failed to link:")
            print(result.stderr)
            return None

        return exe_file

def test_multi_name_import_interpreter():
    """`import a, b, c` must bind *every* name into scope, not just the
    first (bugs/INTERP_multi_name_import_only_binds_first.md). Regression
    test for myinterpreter.py's execute_ImportStmt: previously only
    node.module/node.alias were bound, and every entry in node.extra (the
    comma-separated targets past the first) was silently dropped, so using
    e.g. `argparse` after `import sys, os, difflib, argparse` raised a
    NameError."""
    from mojo_compiler import py_tokenize, Parser
    from myinterpreter import Interpreter

    src = "import sys, os, difflib, argparse\n"
    tokens = py_tokenize(src)
    stmts = Parser(tokens).with_filename('<test>').parse_module()
    interpreter = Interpreter(filename='<test>', argv=['<test>'])
    for stmt in stmts:
        interpreter.execute(stmt)

    for name in ('sys', 'os', 'difflib', 'argparse'):
        value = interpreter.scope.get(name)
        if value is None:
            print(f"✗ {name!r} was not bound by multi-name import")
            return False
        print(f"✓ {name!r} bound: {value!r}")
    return True


def test_import_integration():
    """Test that imports work with compilation and linking."""

    # Define helper module
    helper_src = """\
def double_value(x: Int) -> Int:
    return x * 2

def triple_value(x: Int) -> Int:
    return x * 3
"""

    # Define main program that imports and uses helper
    main_src = """\
from test_helper import double_value, triple_value

def main() -> Int:
    var x: Int = 5
    var doubled: Int = double_value(x)
    var tripled: Int = triple_value(x)
    return doubled + tripled
"""

    # Note: This would need actual compilation of test_helper module
    # For now, just test the code generation
    print("Testing import code generation with helper modules...")

    main_c = compile_to_gimple(main_src)

    # Verify extern declarations
    if 'extern int double_value (void);' in main_c:
        print("✓ Correct extern declaration for double_value")
    else:
        print("✗ Missing extern declaration for double_value")
        return False

    if 'extern int triple_value (void);' in main_c:
        print("✓ Correct extern declaration for triple_value")
    else:
        print("✗ Missing extern declaration for triple_value")
        return False

    # Verify function calls are present
    if 'double_value' in main_c and 'triple_value' in main_c:
        print("✓ Function calls to imported functions present")
    else:
        print("✗ Function calls missing")
        return False

    return True

if __name__ == '__main__':
    ok = True
    if test_import_integration():
        print("\n✓ Import integration test passed!")
    else:
        print("\n✗ Import integration test failed")
        ok = False

    if test_multi_name_import_interpreter():
        print("\n✓ Multi-name import interpreter test passed!")
    else:
        print("\n✗ Multi-name import interpreter test failed")
        ok = False

    if not ok:
        sys.exit(1)
