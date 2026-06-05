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
from mojo_compiler import tokenize, Parser, FunctionDef, StructDef
from gimple_codegen import _mojo_type

_FN_HEAD = re.compile(r'\bfn\s+(\w+)\s*\[([^\]]*)\]')
# Generalized head matching a `fn` or `struct` template with `[type params]`.
_HEAD = re.compile(r'\b(?:fn|struct)\s+(\w+)\s*\[([^\]]*)\]')


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


def extract_overloads(module_src: str, fn_name: str):
    """All non-generic overloads of fn_name: list of (src, [param_mojo_types],
    ret_mojo_type), one per definition, by indentation."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*\(')
    out = []
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            j = i + 1
            while j < len(lines) and not (
                    lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= base):
                j += 1
            src = ''.join(lines[i:j])
            fn = None
            for s in Parser(tokenize(src)).parse_module():
                if isinstance(s, FunctionDef):
                    fn = s
                    break
            if fn is not None:
                ptypes = [t for n, t in fn.params if n != 'self']
                out.append((src, ptypes, fn.return_type))
            i = j
        else:
            i += 1
    return out


def type_param_names(template_src: str):
    """The generic's type-parameter names — for `fn` or `struct`, e.g.
    `struct Box[T, U]` -> ['T', 'U']."""
    m = _HEAD.search(template_src)
    if not m:
        return []
    return [p.strip().split(':')[0].strip()
            for p in m.group(2).split(',') if p.strip()]


def extract_struct_source(module_src: str, name: str):
    """Pull the source text of a `struct name[...]: ...` block, by indentation."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)struct\s+{re.escape(name)}\s*[\[\(:]')
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


# Reverse of the ABI type map, for inferring a generic's type args from the C
# types of its call arguments (slice 2). We substitute the Mojo name into the
# template source, so we need the Mojo spelling, not the C type.
_C_TO_MOJO = {
    'int64_t': 'Int64', 'int32_t': 'Int32', 'int16_t': 'Int16', 'int8_t': 'Int8',
    'int': 'Int', 'uint64_t': 'UInt64', 'uint32_t': 'UInt32', 'uint16_t': 'UInt16',
    'uint8_t': 'UInt8', 'unsigned int': 'UInt', '_Bool': 'Bool',
    'double': 'Float64', 'float': 'Float32', '__fp16': 'Float16', 'char *': 'String',
}


def c_to_mojo(ctype: str) -> str:
    return _C_TO_MOJO.get(ctype, 'Int')


def infer_type_args(template_src: str, arg_ctypes):
    """Infer a generic's type args from the C types of its call arguments. For
    each type parameter that appears directly as a parameter annotation
    (`x: T`), bind it to the Mojo type of the matching argument. Returns the
    ordered list of Mojo type names, or None if any parameter is unbound."""
    params = type_param_names(template_src)
    if not params:
        return None
    fn = None
    for s in Parser(tokenize(template_src)).parse_module():
        if isinstance(s, FunctionDef):
            fn = s
            break
    if fn is None:
        return None
    binding = {}
    for i, (_pname, ann) in enumerate(fn.params):
        if ann in params and ann not in binding and i < len(arg_ctypes):
            binding[ann] = c_to_mojo(arg_ctypes[i])
    if any(p not in binding for p in params):
        return None
    return [binding[p] for p in params]


def _struct_layout(concrete_src: str, name: str):
    """(fields, methods) of the monomorphized struct: fields as (name, c_type),
    methods as (name, ret_ctype, [param_ctypes excluding self])."""
    for s in Parser(tokenize(concrete_src)).parse_module():
        if isinstance(s, StructDef) and s.name == name:
            fields = [(f.name, _mojo_type(f.type_ann)) for f in getattr(s, 'fields', [])]
            methods = []
            for m in getattr(s, 'methods', []):
                ret = _mojo_type(m.return_type) if m.return_type else 'void'
                ps = [_mojo_type(t) for n, t in m.params if n != 'self']
                methods.append((m.name, ret, ps))
            return fields, methods
    return [], []


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

    def elaborate_generic_struct(self, module_src: str, struct_name: str, type_args):
        """Instantiate a generic struct `Struct[TypeArgs]` (slice 5): monomorphize
        the struct + its methods for the type args (CAS-cached), and report the
        concrete name, field layout, method signatures, and object so the codegen
        can materialize the type, construct it, and call its methods."""
        tmpl = extract_struct_source(module_src, struct_name)
        if tmpl is None:
            return None
        params = type_param_names(tmpl)
        if not params or len(type_args) < len(params):
            return None
        targs = dict(zip(params, type_args[:len(params)]))

        mangled, obj, _hit = mm.instantiate(tmpl, targs, gcc=self.gcc)
        _, concrete = mm.monomorphize_source(tmpl, targs)
        fields, methods = _struct_layout(concrete, mangled)
        return {'name': mangled, 'fields': fields, 'methods': methods, 'object': obj}

    def elaborate_overload_call(self, module_src: str, fn_name: str, arg_ctypes):
        """Resolve an overloaded call (slice 4): pick the `fn_name` overload whose
        parameter types match the argument C types, mangle it by signature, and
        compile that one concrete function (CAS-cached). Returns
        {symbol, object, ret, params} or None."""
        overloads = extract_overloads(module_src, fn_name)
        if not overloads:
            return None
        arg_mojo = [c_to_mojo(ct) for ct in arg_ctypes]
        chosen = None
        for src, ptypes, ret in overloads:
            if ptypes == arg_mojo:
                chosen = (src, ptypes, ret)
                break
        if chosen is None:
            chosen = overloads[0]   # best effort: first candidate
        src, ptypes, ret = chosen
        mangled = fn_name + '__' + ('_'.join(ptypes) if ptypes else 'void')
        renamed = re.sub(rf'\bfn\s+{re.escape(fn_name)}\b', f'fn {mangled}', src, count=1)
        obj, _hit = mm.compile_fn(renamed, gcc=self.gcc)
        return {'symbol': mangled, 'object': obj,
                'ret': _mojo_type(ret) if ret else 'void',
                'params': [_mojo_type(p) for p in ptypes]}

    def elaborate_generic_call_inferred(self, module_src: str, fn_name: str, arg_ctypes):
        """Like elaborate_generic_call but infers the type args from the call
        argument C types (slice 2): `box(42)` with no explicit `[Int64]`."""
        tmpl = extract_fn_source(module_src, fn_name)
        if tmpl is None:
            return None
        type_args = infer_type_args(tmpl, arg_ctypes)
        if type_args is None:
            return None
        return self.elaborate_generic_call(module_src, fn_name, type_args)
