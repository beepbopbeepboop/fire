import subprocess
import sys
import os
import tempfile


def test_for_tuple_enumerate_with_var_in_second_position():
    """Regression for bug PARSER_type_refinement_tuple_enumerate - var/ref in tuple unpacking after first element."""
    code = '''for i, var item in enumerate([10, 20, 30]):
    pass
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=os.path.dirname(__file__)) as f:
        f.write(code)
        fname = f.name
    try:
        result = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'fire.py'), 'run', fname],
                              cwd=os.path.dirname(__file__), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert result.returncode == 0, result.stderr.decode()
    finally:
        os.unlink(fname)


def test_for_tuple_enumerate_with_ref_in_second_position():
    code = '''for i, ref item in enumerate([1, 2, 3]):
    pass
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=os.path.dirname(__file__)) as f:
        f.write(code)
        fname = f.name
    try:
        result = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'fire.py'), 'run', fname],
                              cwd=os.path.dirname(__file__), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert result.returncode == 0, result.stderr.decode()
    finally:
        os.unlink(fname)


if __name__ == '__main__':
    # Registered as a `cmd` job whose command is `python3 <this file>`, so with
    # no `__main__` the interpreter ran only the top level (imports + defs) and
    # exited 0 -- none of the `test_*` functions below ever ran. Same no-op
    # class as bugs/SUITE_module_loader_stdlib_job_is_noop.md. Every function
    # here is fixture-free, so they can be run directly.
    import traceback

    _cases = [(n, f) for n, f in sorted(globals().items())
              if n.startswith('test') and callable(f)]
    _failed = 0
    for _n, _f in _cases:
        try:
            _f()
        except Exception:
            traceback.print_exc()
            print('FAIL ' + _n)
            _failed += 1
        else:
            print('PASS ' + _n)
    if _failed:
        raise SystemExit('%d failure(s) of %d' % (_failed, len(_cases)))
    print('%d passed, 0 failed' % len(_cases))
