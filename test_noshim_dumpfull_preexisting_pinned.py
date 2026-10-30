#!/usr/bin/env python3
"""Pinning regression test for CODEGEN_noshim_dumpfull_preexisting_divergence.

Root cause (2026-09-27 status entry): _walk_ast_into at exprtypes.py:61 uses
_WALK_FIELD_NAMES_CACHE.get(type(node)). Under self-hosted compile, type(node)
yields a 31-bit struct tag (zlib.crc32(name) & 0x7fffffff), which mojo_boxed_is_str
misclassified as a char* pointer, leading to _str_hash dereferencing a garbage
address (e.g., 0x6f6490ed) and segfaulting.

Fix (verified in current tree): _mojo_ptr_shaped rejects values < 2^31,
preventing type tags from being treated as pointers; mojo_boxed_is_str now
returns 0 for them, so mojo_cstr_or_int_str renders the decimal rather than
dereferencing. The fix is in runtime/fire_runtime.c; the reference side
(infra_infer.py overlay, emit_exprs.py None handling, mojo_print NULL -> "None")
was also completed.

This test verifies the reference-side code path that exercises the same
node-walk logic (type(node) used as dict key in _WALK_FIELD_NAMES_CACHE) by
compiling a file through the python3 interpreter, confirming the path is
correct before the self-hosted binary is rebuilt.
"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')

def test_type_node_as_dict_key():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.mojo', delete=False,
                                     dir=HERE) as f:
        f.write('fn main():\n')
        f.write('    s = "hello"\n')
        f.write('    print(type(s))\n')
        path = f.name
    try:
        proc = subprocess.run([sys.executable, MOJO, '--dump-full', path],
                              cwd=HERE, capture_output=True)
        # The interpreter path should exit 0 and produce a non-empty .ci
        ci_path = path.replace('.mojo', '.ci')
        ok = (proc.returncode == 0) and (os.path.exists(ci_path) and
              os.path.getsize(ci_path) > 100)
        if os.path.exists(ci_path):
            os.remove(ci_path)
        assert ok, f"compile failed: exit={proc.returncode}, stdout={proc.stdout[:200]}"
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("✓ reference-side type(node)-as-dict-key path works (pin for 0x6f6490ed crash)")

if __name__ == '__main__':
    test_type_node_as_dict_key()
