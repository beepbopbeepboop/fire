"""An imported free function that its home module defines as a plain overload
AND a generic template (`unsafe_memset_zero(ptr, count)` next to
`unsafe_memset_zero[dtype, count](ptr)`) must be called under the name the
definer emits for the plain overload. The import scan records the name as a
variadic stub, which names no overload, so the call used to bind to it.

Checked on the generated C: the caller's call and its declaration name the same
symbol as the definer's definition. The call is a statement, as bitset's is; a
value-returning call is elaborated separately and is not this path.
"""
import os
import re
import shutil
import sys
import tempfile

import build_stdlib_dylib as b

HOME = """
def fill(ptr: Int, count: Int) -> Int:
    return ptr + count

def fill[n: Int](ptr: Int) -> Int:
    return ptr * n
"""

INIT = """
from .home import fill
"""

CALLER = """
from ov_pkg import fill

def use():
    fill(1, 2)
"""


def test_import_overload_choice():
    tmp = tempfile.mkdtemp(prefix='imp_ov_')
    try:
        # The overloads live in `ov_pkg/home.mojo`; the package `__init__` only
        # re-exports the name, as std.memory's does for unsafe_memset_zero.
        pkg = os.path.join(tmp, 'ov_pkg')
        os.makedirs(pkg)
        home_path = os.path.join(pkg, 'home.mojo')
        with open(home_path, 'w') as f:
            f.write(HOME)
        init_path = os.path.join(pkg, '__init__.mojo')
        with open(init_path, 'w') as f:
            f.write(INIT)
        caller_path = os.path.join(tmp, 'ov_caller.mojo')
        with open(caller_path, 'w') as f:
            f.write(CALLER)
        sys.path.insert(0, tmp)
        try:
            home_c = b.compile_module_to_c(HOME, home_path, 'home')
            caller_c = b.compile_module_to_c(CALLER, caller_path, 'ov_caller')
        finally:
            sys.path.remove(tmp)
        defined = set(re.findall(r'\n(?:int64_t|void|_Bool) (home_fill_[0-9a-f]+) \(int64_t \w+, int64_t \w+\)\s*\n\{', home_c))
        assert len(defined) == 1, f'expected one definition of the plain overload, got {defined}'
        sym = defined.pop()
        calls = set(re.findall(r'\b(home_fill_[0-9a-f]+) \(', caller_c))
        assert calls == {sym}, f'caller calls {calls}, definer defines {sym}'
        assert 'home_fill (...)' not in caller_c, 'caller still binds the variadic stub'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TYPED_HOME = """
def nap(sec: Float64):
    print(sec)

def nap(sec: Int):
    print(sec)
"""

TYPED_CALLER = """
from typed_home import nap

def use():
    nap(1)
    nap(1.5)
"""


def test_import_overload_by_argument_type():
    """Two plain overloads of one arity (`time.sleep(Float64)` / `sleep(Int)`):
    each call names the overload its argument type selects, and both names are
    the definer's own."""
    tmp = tempfile.mkdtemp(prefix='imp_ovt_')
    try:
        home_path = os.path.join(tmp, 'typed_home.mojo')
        with open(home_path, 'w') as f:
            f.write(TYPED_HOME)
        caller_path = os.path.join(tmp, 'typed_caller.mojo')
        with open(caller_path, 'w') as f:
            f.write(TYPED_CALLER)
        sys.path.insert(0, tmp)
        try:
            home_c = b.compile_module_to_c(TYPED_HOME, home_path, 'typed_home')
            caller_c = b.compile_module_to_c(TYPED_CALLER, caller_path, 'typed_caller')
        finally:
            sys.path.remove(tmp)
        defined = set(re.findall(r'\n(?:int64_t|void|_Bool) (typed_home_nap_[0-9a-f]+) \(([^)]*)\)\s*\n\{', home_c))
        by_type = {params.strip(): name for name, params in defined}
        assert set(by_type) == {'int64_t sec', 'double sec'}, f'definitions: {defined}'
        calls = re.findall(r'\b(typed_home_nap_[0-9a-f]+) \((_t\d+|1\.5)\)', caller_c)
        names = sorted(c[0] for c in calls)
        assert names == sorted([by_type['int64_t sec'], by_type['double sec']]), f'calls {calls}'
        assert 'typed_home_nap (...)' not in caller_c, 'caller still binds the variadic stub'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


EXT_HOME = """
from std.ffi import external_call

def nap(sec: Float64):
    print(sec)

def nap(sec: Int):
    external_call["ext_nap", NoneType](Int32(sec))
"""


def test_external_call_overloads_are_all_emitted():
    """An overload set in which one body calls `external_call[...]` emits every
    overload (it was dropped whole, which left `time.sleep` undefined)."""
    tmp = tempfile.mkdtemp(prefix='ext_ov_')
    try:
        path = os.path.join(tmp, 'ext_home.mojo')
        with open(path, 'w') as f:
            f.write(EXT_HOME)
        c = b.compile_module_to_c(EXT_HOME, path, 'ext_home')
        defs = re.findall(r'\n(?:int64_t|void|_Bool) (ext_home_nap_[0-9a-f]+) \(', c)
        assert len(set(defs)) == 2, f'expected both overloads defined, got {set(defs)}'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ok = (test_import_overload_choice() and test_import_overload_by_argument_type()
          and test_external_call_overloads_are_all_emitted())
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
