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
