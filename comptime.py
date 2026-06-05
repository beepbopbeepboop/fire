#!/usr/bin/env python3
"""Comptime as cached machine code — MODULE_CACHE_DESIGN.md stage 6.

Mojo's comptime is Turing-complete. Tree-interpreting it (today's
`_eval_const_*` only constant-folds) does not scale. Instead we compile a
comptime function to a CAS-cached artifact *once*, then the compiler `dlopen`s it
and **calls** it with the comptime arguments — executing real machine code at
compile time. "That's what the interpreter was doing anyway", now done for real,
and cached so it is compiled at most once ever.

This is the mechanism; the integration point is `_eval_const_*` in
`gimple_codegen.py` (a `comptime` call whose evaluator returns None today would
fall through to `evaluate()` here). Foundation-first: the interpreter remains the
fallback; this is the fast, fully-general path.
"""
import os
import ctypes
import tempfile
import subprocess

import cas
from build_config import find_gcc
from gimple_codegen import GimpleGen
from mojo_compiler import tokenize, Parser, FunctionDef

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
_OBJ_FLAGS = ('-fgimple', '-fPIC', f'-I{RUNTIME}')

# C type → ctypes, for marshaling comptime args/results across the dlopen call.
_CTYPES = {
    'int': ctypes.c_int, 'int8_t': ctypes.c_int8, 'int16_t': ctypes.c_int16,
    'int32_t': ctypes.c_int32, 'int64_t': ctypes.c_int64,
    'uint8_t': ctypes.c_uint8, 'uint16_t': ctypes.c_uint16,
    'uint32_t': ctypes.c_uint32, 'uint64_t': ctypes.c_uint64,
    'unsigned int': ctypes.c_uint, '_Bool': ctypes.c_bool,
    'float': ctypes.c_float, 'double': ctypes.c_double,
    'char *': ctypes.c_char_p, 'void': None,
}


def _signature(src: str, fn_name: str):
    """(ret_ctype, [param_ctypes]) for fn_name, via the ABI type mapping."""
    from gimple_codegen import _mojo_type
    for s in Parser(tokenize(src)).parse_module():
        if isinstance(s, FunctionDef) and s.name == fn_name:
            ret = _mojo_type(s.return_type) if s.return_type else 'void'
            params = [_mojo_type(t) for _, t in s.params]
            return ret, params
    raise ValueError(f"comptime: function {fn_name!r} not found")


def _build_dylib(src: str, fn_name: str, gcc: str) -> str:
    """Compile src to a CAS-cached dylib exporting fn_name. Returns its path."""
    key = cas.comptime_key(src, fn_name, gcc, _OBJ_FLAGS)
    ext = '.dylib'

    def build():
        gen = GimpleGen(emit_entry_points=False, module_name=fn_name)
        c = gen.gen_module(Parser(tokenize(src)).parse_module())
        wd = tempfile.mkdtemp(prefix='mojo_ct_')
        cfile = os.path.join(wd, fn_name + '.c')
        ofile = os.path.join(wd, fn_name + '.o')
        rt_o = os.path.join(wd, 'rt.o')
        dy = os.path.join(wd, fn_name + ext)
        with open(cfile, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile], check=True)
        subprocess.run([gcc, '-fPIC', f'-I{RUNTIME}', '-c', '-o', rt_o,
                        os.path.join(RUNTIME, 'mojo_runtime.c')], check=True)
        subprocess.run([gcc, '-dynamiclib', '-o', dy, ofile, rt_o], check=True)
        with open(dy, 'rb') as f:
            return f.read()

    path, _hit = cas.get_or_build(key, ext, build)
    return path


def evaluate(src: str, fn_name: str, args, gcc: str = None):
    """Compile (once, cached) and CALL a comptime function at compile time.
    Returns the function's result, computed by executing real machine code."""
    gcc = gcc or find_gcc()
    ret, params = _signature(src, fn_name)
    dylib = _build_dylib(src, fn_name, gcc)

    # Only scalar param types can be marshaled across the dlopen call. Raise a
    # clear error (caught by the caller, which falls back to the constant-folder)
    # rather than KeyError-crashing on a container/pointer param (review finding #6).
    argtypes = []
    for p in params:
        ct = _CTYPES.get(p)
        if ct is None:
            raise ValueError(f"comptime: unmarshalable parameter type {p!r} "
                             f"for {fn_name!r}; not a compile-time-callable signature")
        argtypes.append(ct)

    lib = ctypes.CDLL(dylib)
    fn = getattr(lib, fn_name)
    fn.argtypes = argtypes
    fn.restype = _CTYPES.get(ret, ctypes.c_int64)
    return fn(*args)
