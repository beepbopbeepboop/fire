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


def test_scalar_integer_overload_choice():
    import uuid
    from gimple_codegen import GimpleGen
    import module_loader
    import mojo.middle.funcs_shared as fns
    tag = uuid.uuid4().hex[:8]
    mulhi_mod = f'scov_mulhi_{tag}'
    fd_mod = f'scov_fd_{tag}'
    caller_mod = f'scov_caller_{tag}'
    mulhi_src = f"""
def mulhi(a: Int64, b: Int64) -> Int64:
    return 0

def mulhi(a: UInt32, b: UInt32) -> UInt32:
    return UInt32((UInt64(a) * UInt64(b)) >> 32)
"""
    fd_src = f"""
from {mulhi_mod} import mulhi

struct Fd[dtype: DType]:
    var m: Scalar[dtype]
    def __init__(out self, m: Scalar[dtype]):
        self.m = m
    def hi(self, other: Scalar[dtype]) -> UInt32:
        var a = UInt32(self.m)
        var b = UInt32(other)
        return mulhi(a, b)
"""
    caller_src = f"""
from {fd_mod} import Fd

def use() -> UInt32:
    var x = Fd[DType.uint32](UInt32(1))
    return x.hi(UInt32(2))
"""
    tmp = tempfile.mkdtemp(prefix='scov_')
    emitted = []
    orig_gen_module = GimpleGen.gen_module

    def capture_gen_module(self, stmts):
        c = orig_gen_module(self, stmts)
        emitted.append(c)
        return c

    GimpleGen.gen_module = capture_gen_module
    mods = {mulhi_mod, fd_mod}
    orig_can = module_loader.can_resolve_module_path
    orig_load = module_loader.load_module
    orig_resolve = module_loader._module_loader.resolve_module_path
    orig_gpi = GimpleGen._parsed_import

    def my_can(name):
        if name in mods:
            return True
        return orig_can(name)

    def my_resolve(name):
        if name in mods:
            return os.path.join(tmp, name + '.mojo')
        return orig_resolve(name)

    def my_load(name):
        if name in mods:
            return module_loader._module_loader.load_module_from_path(
                os.path.join(tmp, name + '.mojo'))
        return orig_load(name)

    def my_gpi(self, module):
        if module in mods:
            path = os.path.join(tmp, module + '.mojo')
            try:
                src = open(path).read()
                from fire_compiler import Parser, py_tokenize
                stmts = Parser(py_tokenize(src)).parse_module()
                if not hasattr(self, '_imported_src_cache'):
                    self._imported_src_cache = {}
                self._imported_src_cache[module] = (path, src, stmts)
                return (path, src, stmts)
            except Exception:
                pass
        return orig_gpi(self, module)

    module_loader.can_resolve_module_path = my_can
    module_loader._module_loader.resolve_module_path = my_resolve
    module_loader.load_module = my_load
    GimpleGen._parsed_import = my_gpi
    try:
        mulhi_path = os.path.join(tmp, mulhi_mod + '.mojo')
        with open(mulhi_path, 'w') as f:
            f.write(mulhi_src)
        fd_path = os.path.join(tmp, fd_mod + '.mojo')
        with open(fd_path, 'w') as f:
            f.write(fd_src)
        caller_path = os.path.join(tmp, caller_mod + '.mojo')
        with open(caller_path, 'w') as f:
            f.write(caller_src)
        sys.path.insert(0, tmp)
        try:
            mulhi_c = b.compile_module_to_c(mulhi_src, mulhi_path, mulhi_mod)
            fd_c = b.compile_module_to_c(fd_src, fd_path, fd_mod)
            caller_c = b.compile_module_to_c(caller_src, caller_path, caller_mod)
        finally:
            sys.path.remove(tmp)
        mul_defs = re.findall(
            rf'\n(?:int64_t|uint32_t|void|_Bool) ({mulhi_mod}_mulhi_[0-9a-f]+) \(([^)]*)\)\s*\n\{{',
            mulhi_c)
        by_type = {params.strip(): name for name, params in mul_defs}
        int_sym = by_type.get('int64_t a, int64_t b')
        uint_sym = by_type.get('uint32_t a, uint32_t b')
        assert int_sym and uint_sym, f'expected both mulhi overloads in home, got {by_type}'
        all_c = '\n'.join(emitted)
        hi_bodies = []
        for m in re.finditer(
                r'(?:uint32_t|__GIMPLE uint32_t|static uint32_t)\s+([A-Za-z0-9_]*_hi)\s*\([^)]*\)\s*\{(.*?)\n\}',
                all_c, re.S):
            hi_bodies.append((m.group(1), m.group(2)))
        # Prefer the specialised hi body; fall back to any hi body.
        chosen = None
        for name, body in hi_bodies:
            if 'DType_x002Euint32' in name or 'uint32' in name.lower():
                chosen = (name, body)
                break
        if chosen is None:
            assert hi_bodies, f'no hi body found in emitted C'
            chosen = hi_bodies[-1]
        _, body = chosen
        assert uint_sym in body, f'hi body does not call uint32 mulhi {uint_sym}: {body[:400]}'
        assert int_sym not in body, f'hi body calls int64 mulhi {int_sym}: {body[:400]}'
        print('PASS')
        return True
    finally:
        GimpleGen.gen_module = orig_gen_module
        GimpleGen._parsed_import = orig_gpi
        module_loader.can_resolve_module_path = orig_can
        module_loader._module_loader.resolve_module_path = orig_resolve
        module_loader.load_module = orig_load
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ok = (test_import_overload_choice() and test_import_overload_by_argument_type()
          and test_external_call_overloads_are_all_emitted()
          and test_scalar_integer_overload_choice())
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
