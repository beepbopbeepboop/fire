#!/usr/bin/env python3
"""elaborate.py — the CAS-backed semantic driver (ELABORATION.md).

Elaboration turns parametric Mojo into concrete Mojo by resolving and running the
compile-time parts. This is the demand-driven service the codegen calls into; it
*decides* what to instantiate and *records* the result, while the engines
(`monomorphize`, `comptime`) execute and the CAS caches.

Slice 1 — generic call elaboration: `Generic[TypeArgs](args)` from an imported
generic → instantiate the template for those type args (CAS-cached), and report
the concrete symbol + object + signature so the codegen can lower the call and
record the object on the link line.
"""
import re

import monomorphize as mm
from mojo_compiler import tokenize, Parser, FunctionDef
from gimple_codegen import _mojo_type

_FN_HEAD = re.compile(r'\bfn\s+(\w+)\s*\[([^\]]*)\]')


def extract_fn_source(module_src: str, fn_name: str):
    """Pull the source text of a single `fn fn_name[...](...): body` from a module,
    by indentation (the generic template we'll instantiate). None if not found."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*[\[\(]')
    start = None
    for i, l in enumerate(lines):
        if pat.match(l):
            start = i
            break
    if start is None:
        return None
    base = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= base:
            end = j
            break
    return ''.join(lines[start:end])


def type_param_names(template_src: str):
    """The generic's type-parameter names, e.g. `fn box[T, U]` -> ['T', 'U']."""
    m = _FN_HEAD.search(template_src)
    if not m:
        return []
    return [p.strip().split(':')[0].strip()
            for p in m.group(2).split(',') if p.strip()]


def _signature(concrete_src: str, name: str):
    """(ret_ctype, [param_ctypes]) of the monomorphized function, via the ABI map."""
    for s in Parser(tokenize(concrete_src)).parse_module():
        if isinstance(s, FunctionDef) and s.name == name:
            ret = _mojo_type(s.return_type) if s.return_type else 'void'
            return ret, [_mojo_type(t) for _, t in s.params]
    return 'int64_t', []


class Elaborator:
    """Demand-driven, CAS-backed elaboration service."""

    def __init__(self, gcc=None):
        self.gcc = gcc

    def elaborate_generic_call(self, module_src: str, fn_name: str, type_args):
        """Instantiate `fn_name` for `type_args` (a list of concrete type strings)
        via the CAS. Returns a dict {symbol, object, ret, params} or None.

        Elaborate-once-ever: the instantiation is content-addressed, so a repeat
        (here or in another program) is a cache hit."""
        tmpl = extract_fn_source(module_src, fn_name)
        if tmpl is None:
            return None
        params = type_param_names(tmpl)
        if not params or len(type_args) < len(params):
            return None
        targs = dict(zip(params, type_args[:len(params)]))

        mangled, obj, _hit = mm.instantiate(tmpl, targs, gcc=self.gcc)
        _, concrete = mm.monomorphize_source(tmpl, targs)
        ret, ptypes = _signature(concrete, mangled)
        return {'symbol': mangled, 'object': obj, 'ret': ret, 'params': ptypes}
