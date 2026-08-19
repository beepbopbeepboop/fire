"""Integration test: compile mojo with imports and link with helper modules."""
import os
import re
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple, GimpleGen
from mojo_compiler import py_tokenize, Parser
import ast_rewriter
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
            # Compile helper to C with emit_entry_points=False: a helper
            # module compiled standalone still gets a `main`/`_gimple_main`
            # entry-point stub (compile_to_gimple's default), which would
            # collide with the importing program's own `main` at link time
            # since these are separately-compiled objects statically linked
            # together (not a shared-library workflow). Mirrors how
            # gimple_codegen.py itself compiles an inlined import's nested
            # GimpleGen instance (do_imports=True path).
            tokens = py_tokenize(helper_src)
            stmts = ast_rewriter.rewrite(
                Parser(tokens).with_filename(f"{module_name}.mojo").parse_module())
            helper_gen = GimpleGen(do_imports=False, emit_entry_points=False,
                                    module_name=module_name)
            helper_c = helper_gen.gen_module(stmts)
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

        # mojo_runtime.o provides the print/repr/dispatch helpers every
        # compiled Mojo program references — build it fresh for the host
        # arch rather than trusting any prebuilt runtime/mojo_runtime.o
        # (which may be stale for a different architecture).
        runtime_obj = os.path.join(tmpdir, 'mojo_runtime.o')
        rt_result = subprocess.run(
            ['cc', '-c', f'-I{HERE}/runtime', '-o', runtime_obj,
             f'{HERE}/runtime/mojo_runtime.c'],
            capture_output=True, text=True, timeout=30
        )
        if rt_result.returncode != 0:
            print("Failed to compile mojo_runtime.c:")
            print(rt_result.stderr)
            return None

        # Link main with helper objects. The executable is placed OUTSIDE
        # tmpdir (which this function's `with` block deletes on return) so
        # callers can still run it after compile_and_link() returns.
        exe_fd, exe_file = tempfile.mkstemp(suffix='.exe')
        os.close(exe_fd)
        link_cmd = [find_gcc(), '-fgimple',
                    f'-I{HERE}/runtime',
                    '-o', exe_file, main_c_file] + helper_objs + [runtime_obj]

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
    """Test that imports work with compilation and linking.

    Uses `runtime/test_helper_values.mojo` (a real module module_loader.py
    can resolve, distinct from `runtime/test_helper.mojo`'s double/add so
    the two import tests' resolved signatures never collide) so the extern
    declaration this test checks reflects a REAL resolved signature, not an
    unresolved-import fallback. `double_value`/`triple_value` each take one
    Int argument, so the correct C signature is `int64_t <name> (int64_t x)`
    per gimple_codegen.py's canonical Int -> int64_t mapping (ABI.md) — NOT
    the old, always-wrong `(void)` (a function taking a parameter can never
    correctly get a no-args extern) this test used to assert.

    Beyond the string check, this now actually compiles the helper module,
    compiles+links the importing program against it via compile_and_link(),
    and RUNS the result — the strongest evidence that cross-file imports
    genuinely work, not just that some extern text is present.
    """

    # Define helper module (mirrors runtime/test_helper_values.mojo)
    helper_src = """\
def double_value(x: Int) -> Int:
    return x * 2

def triple_value(x: Int) -> Int:
    return x * 3
"""

    # Define main program that imports and uses helper
    main_src = """\
from test_helper_values import double_value, triple_value

def main() -> Int:
    var x: Int = 5
    var doubled: Int = double_value(x)
    var tripled: Int = triple_value(x)
    print(doubled + tripled)
    return 0
"""

    print("Testing import code generation with helper modules...")

    main_c = compile_to_gimple(main_src)

    # Verify extern declarations: real resolved signature, int64_t (Int's
    # canonical C type), one named param, with the overload-hash suffix
    # _func_csym appends to every mangleable free function's C symbol.
    if re.search(r'extern int64_t double_value_[0-9a-f]{6} \(int64_t x\);', main_c):
        print("✓ Correct extern declaration for double_value")
    else:
        print("✗ Missing/incorrect extern declaration for double_value")
        for line in main_c.split('\n'):
            if 'double_value' in line:
                print(line)
        return False

    if re.search(r'extern int64_t triple_value_[0-9a-f]{6} \(int64_t x\);', main_c):
        print("✓ Correct extern declaration for triple_value")
    else:
        print("✗ Missing/incorrect extern declaration for triple_value")
        for line in main_c.split('\n'):
            if 'triple_value' in line:
                print(line)
        return False

    # Verify function calls are present
    if 'double_value' in main_c and 'triple_value' in main_c:
        print("✓ Function calls to imported functions present")
    else:
        print("✗ Function calls missing")
        return False

    # Real end-to-end check: compile the helper module, compile+link the
    # importing program against it, run it, and verify the actual computed
    # result (5*2 + 5*3 = 25) — the strongest signal that cross-file
    # imports work, stronger than any extern-declaration string match.
    exe = compile_and_link(main_src, {'test_helper_values': helper_src})
    if not exe:
        print("✗ Failed to compile and link the import-integration program")
        return False

    run_result = subprocess.run([exe], capture_output=True, text=True, timeout=10)
    if run_result.returncode != 0:
        print(f"✗ Program exited with code {run_result.returncode}: {run_result.stderr}")
        return False
    if run_result.stdout.strip() != '25':
        print(f"✗ Program printed {run_result.stdout.strip()!r}, expected '25'")
        return False
    print("✓ Compiled, linked, and ran correctly: double_value(5) + triple_value(5) == 25")

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
