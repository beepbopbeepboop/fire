import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _python_cflags():
    cfg = sys.executable + '-config'
    try:
        return subprocess.check_output([cfg, '--cflags'], text=True,
                                       stderr=subprocess.DEVNULL).strip().split()
    except Exception:
        return subprocess.check_output(['python3-config', '--cflags'],
                                       text=True).strip().split()


def _compile(extra, outname):
    src = os.path.join(HERE, 'runtime', 'fire_python.c')
    out = os.path.join(HERE, '.tmp', outname)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cc = os.environ.get('CC', 'cc')
    r = subprocess.run([cc] + _python_cflags() + extra + ['-c', src, '-o', out],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'compile failed ({extra}):\n{r.stdout}\n{r.stderr}'


def test_fire_python_compiles_use_python():
    """fire_python.c must compile against Python 3.15 with USE_PYTHON=1."""
    _compile(['-DUSE_PYTHON=1'], 'fire_python_use_python.o')


def test_fire_python_free_threaded_safe():
    """fire_python.c must be safe for free-threaded Python (PEP 703/3.15):
    API calls that touch Python objects must run with a valid thread state.
    The shim acquires the GIL/thread state around Python API entry points.
    """
    src = os.path.join(HERE, 'runtime', 'fire_python.c')
    with open(src) as f:
        text = f.read()
    # Must use GIL/thread-state guards for free-threaded compatibility.
    assert 'PyGILState_Ensure' in text or 'PyThreadState' in text, (
        'fire_python.c must acquire thread state (PyGILState_Ensure) '
        'around Python API calls for free-threaded/3.15 compatibility')


def test_fire_python_modern_exception_api():
    """fire_python.c must use 3.12+/3.15-compatible exception APIs where
    applicable (PyErr_GetRaisedException), not only legacy fetch/restore,
    for stable ABI / free-threaded build compatibility."""
    src = os.path.join(HERE, 'runtime', 'fire_python.c')
    with open(src) as f:
        text = f.read()
    assert 'PyErr_GetRaisedException' in text, (
        'fire_python.c should use PyErr_GetRaisedException (3.12+, stable ABI '
        'friendly) for Python 3.15 compatibility')


def test_fire_python_stable_abi_free_threaded():
    """Python 3.15 provides stable ABI for free-threaded builds (PEP 703/abi3t).
    The shim must compile under the 3.15 limited API (stable ABI)."""
    _compile(['-DUSE_PYTHON=1', '-DPy_LIMITED_API=0x030F0000'],
             'fire_python_limited315.o')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items())
             if k.startswith('test_') and callable(v)]
    for fn in tests:
        fn()
        print('ok', fn.__name__)
    print('ALL OK')
