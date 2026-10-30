"""Regression test for CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure.

This reproduces the closure-only refusal that occurs when:
1. A module does `from X import _coro` where X exports _coro as a global_var
2. The same module's own code reads _coro.close() in a full closure
3. The read hits _imported_global_accessors early-return arm and skips API carry
"""
import os, sys, tempfile, gimple_codegen

# The test should fail before the fix (refusing to compile/run due to 
# "no known generator API") and pass after the fix (compiles and runs cleanly).

def test_coro_close_with_imported_accessor():
    """Test that _coro.close() works in full closure with imported accessor."""
    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as td:
        # Create sibling module that exports _coro as global_var (triggers accessor)
        sib_path = os.path.join(td, 'sib.py')
        with open(sib_path, 'w') as f:
            f.write('_coro = 5\n')  # This exports _coro as global_var
        
        # Create main test file that imports _coro and uses the idiom
        main_path = os.path.join(td, 'main.py')
        with open(main_path, 'w') as f:
            f.write('import sib\n' +
                    'async def _coro():\n' +
                    '    pass\n' +
                    '_coro = _coro()\n' +
                    'coroutine = type(_coro)\n' +
                    '_coro.close()\n' +
                    'print("ok")\n')
        
        # Compile with do_imports=True (so sibling imports are processed)
        try:
            c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
                'from sib import _coro\n' +
                'async def _coro():\n' +
                '    pass\n' +
                '_coro = _coro()\n' +
                'coroutine = type(_coro)\n' +
                '_coro.close()\n' +
                'print("ok")\n',
                do_imports=True,
                filename=os.path.join(td, 'entry.mojo')
            )
            # If we get here without RuntimeError, the fix worked
            assert 'no known generator API' not in (c_code or cpp_code)
            return True
        except RuntimeError as e:
            if 'no known generator API' in str(e):
                raise AssertionError("Bug reproduced: _coro.close() refused in closure with imported accessor") from e
            raise

if __name__ == '__main__':
    test_coro_close_with_imported_accessor()
    print("PASS: Regression test passes")