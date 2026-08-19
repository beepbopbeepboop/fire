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
from mojo_compiler import py_tokenize, Parser, FunctionDef, StructDef, TraitDef
from gimple_codegen import _mojo_type


class ConformanceError(Exception):
    """A concrete type does not satisfy a generic's trait bound (slice 6).

    Raised when elaborating `f[T]`/`Struct[T]` whose type parameter carries a
    trait bound that the concrete type does not meet (it is missing a required
    method, or its signature differs). The message is the compile error a user
    sees."""

_FN_HEAD = re.compile(r'\b(?:fn|def)\s+(\w+)\s*\[([^\]]*)\]')
# Generalized head matching a `fn` or `struct` template with `[type params]`.
_HEAD = re.compile(r'\b(?:fn|def|struct)\s+(\w+)\s*\[([^\]]*)\]')


def _bracket_depth_by_line(module_src: str) -> list[int]:
    """depths[j] = bracket nesting depth (from `([{`) in effect at the START
    of 0-indexed line `j` of `module_src.splitlines()`. Comment- and
    string-literal-aware (including triple-quoted docstrings and single
    backtick-delimited MLIR literals, e.g. `` `#interp.pointer<0> : ` `` —
    without backtick-awareness a literal `#` inside one of these is
    mistaken for a comment-start, silently swallowing the rest of the line
    including its closing bracket and permanently desyncing depth for the
    rest of the file) so a `[`/`]`/`(`/`)`/`{`/`}` inside a literal or
    comment is never mistaken for a structural bracket.

    Exists because a generic's header (`def name[T, /](args) -> Ret[...]:`)
    may itself span multiple physical lines, with a continuation line — e.g.
    the `]`/`)` that closes the parameter list — starting at column 0. A
    plain "dedent to <= base indentation ends the block" check misreads that
    continuation line as the end of the function/struct, silently truncating
    the extracted template before its real body."""
    depth = 0
    depths = [0]
    in_str = None  # None, or '"', "'", '"""', "'''"
    i, n = 0, len(module_src)
    while i < n:
        c = module_src[i]
        if in_str:
            if in_str in ('"""', "'''"):
                if module_src.startswith(in_str, i):
                    i += 3
                    in_str = None
                    continue
            else:
                if c == '\\':
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            if c == '\n':
                depths.append(depth)
            i += 1
            continue
        if c == '#':
            j = module_src.find('\n', i)
            i = n if j == -1 else j
            continue
        if module_src.startswith('"""', i) or module_src.startswith("'''", i):
            in_str = module_src[i:i + 3]
            i += 3
            continue
        if c in ('"', "'", '`'):
            in_str = c
            i += 1
            continue
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth = max(0, depth - 1)
        if c == '\n':
            depths.append(depth)
        i += 1
    return depths


def _find_block_end(lines: list[str], depths: list[int], start: int, base: int) -> int:
    """First line index after `start` that both dedents to <= `base`
    indentation AND sits at bracket depth 0 — i.e. an ordinary top-level
    statement boundary, not a continuation of a still-open `([{` header."""
    for j in range(start + 1, len(lines)):
        l = lines[j]
        d = depths[j] if j < len(depths) else 0
        if l.strip() and d == 0 and (len(l) - len(l.lstrip())) <= base:
            return j
    return len(lines)


def extract_fn_source(module_src: str, fn_name: str, arg_count: int | None = None):
    """Pull the source text of a single `fn fn_name[...](...): body` from a
    module, by indentation (the generic template we'll instantiate). None if
    not found.

    A generic name can have multiple same-named definitions distinguished
    only by arity (e.g. `itertools.product` has separate `[IterableTypeA,
    IterableTypeB](a, b)` / `(a, b, c)` / `(a, b, c, d)` overloads — there is
    no separate "generic overload" mechanism the way non-generic overloads
    get one via `extract_overloads`). When `arg_count` is given and more than
    one candidate matches by name, pick the one whose non-self, non-variadic
    parameter count equals it; otherwise fall back to the first match."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*[\[\(]')
    depths = _bracket_depth_by_line(module_src)
    candidates = []
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            end = _find_block_end(lines, depths, i, base)
            candidates.append(''.join(lines[i:end]))
            i = end
        else:
            i += 1
    if not candidates:
        return None
    if arg_count is None or len(candidates) == 1:
        return candidates[0]
    for src in candidates:
        for s in Parser(py_tokenize(src)).parse_module():
            if isinstance(s, FunctionDef) and s.name == fn_name:
                n = len([1 for pn, _ in s.params if pn != 'self' and not pn.startswith('*')])
                if n == arg_count:
                    return src
                break
    return candidates[0]


def extract_overloads(module_src: str, fn_name: str):
    """All non-generic overloads of fn_name: list of (src, [param_mojo_types],
    ret_mojo_type), one per definition, by indentation."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*\(')
    depths = _bracket_depth_by_line(module_src)
    out = []
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            j = _find_block_end(lines, depths, i, base)
            src = ''.join(lines[i:j])
            fn = None
            for s in Parser(py_tokenize(src)).parse_module():
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
    `struct Box[T, U]` -> ['T', 'U']. Skips the bare `/` and `*` separators
    (positional-only / keyword-only markers), which are not parameter names."""
    m = _HEAD.search(template_src)
    if not m:
        return []
    return [p.strip().split(':')[0].strip()
            for p in m.group(2).split(',')
            if p.strip() and p.strip() not in ('/', '*')]


# ── Trait / conformance bound-checking (slice 6) ─────────────────────────
#
# A generic's type parameter may carry a *trait bound*: `fn f[T: Stringable]`
# or `struct Box[T: Stringable]`. The bound names a trait — an abstract set of
# required method signatures. Before instantiating the generic for a concrete
# type, elaboration verifies the type *conforms* (defines every required
# method, with matching parameter/return types). A non-conforming type yields
# a `ConformanceError` rather than a broken instantiation downstream.

# `[T: Trait, U: Other, count: Int]` — capture the bound that follows each
# type-param name. A param with no `: Bound` (or a value param like `count:
# Int`, which we treat as unbounded for our purposes) maps to None.
def parse_bounds(template_src: str):
    """Map each type-parameter name to its trait bound name (or None) from a
    generic's `[...]` head: `fn f[T: Stringable]` -> {'T': 'Stringable'}."""
    m = _HEAD.search(template_src)
    if not m:
        return {}
    bounds = {}
    for p in m.group(2).split(','):
        p = p.strip()
        if not p or p in ('/', '*'):
            continue
        if ':' in p:
            name, bound = p.split(':', 1)
            bounds[name.strip()] = bound.strip() or None
        else:
            bounds[p] = None
    return bounds


def _method_sig(fn: FunctionDef):
    """(name, [param_mojo_types excluding self], ret_mojo_type) of a method."""
    ptypes = [t for n, t in fn.params if n != 'self']
    return (fn.name, ptypes, fn.return_type)


def extract_trait(module_src: str, trait_name: str):
    """The required method signatures of `trait trait_name`, as a list of
    (name, [param_types], ret_type). None if the trait is not defined here."""
    for s in Parser(py_tokenize(module_src)).parse_module():
        if isinstance(s, TraitDef) and s.name == trait_name:
            return [_method_sig(m) for m in s.methods]
    return None


def type_methods(module_src: str, type_name: str):
    """The method signatures a concrete `struct type_name` defines, as a list
    of (name, [param_types], ret_type). None if the type is not a struct here."""
    for s in Parser(py_tokenize(module_src)).parse_module():
        if isinstance(s, StructDef) and s.name == type_name:
            return [_method_sig(m) for m in s.methods]
    return None


def check_conformance(module_src: str, type_name: str, trait_name: str):
    """Does concrete `type_name` satisfy `trait_name`? Returns (ok, missing),
    where `missing` lists human-readable descriptions of unmet requirements.

    A requirement is met when the type defines a method of the same name whose
    (param types, return type) match. If the trait is unknown we cannot check
    it, so we conservatively accept (ok=True) — bounds we don't understand do
    not block instantiation, matching the demand-driven, best-effort style."""
    required = extract_trait(module_src, trait_name)
    if required is None:
        return True, []
    have = type_methods(module_src, type_name)
    if have is None:
        # No struct source to inspect (e.g. a builtin like Int). We cannot
        # verify, so we do not block — keep behaviour additive.
        return True, []
    by_name = {}
    for name, ptypes, ret in have:
        by_name.setdefault(name, []).append((ptypes, ret))
    missing = []
    for name, ptypes, ret in required:
        cands = by_name.get(name)
        if cands is None:
            missing.append(f"missing method '{name}'")
            continue
        if not any(cp == ptypes and cr == ret for cp, cr in cands):
            want = f"({', '.join(ptypes)}) -> {ret}"
            missing.append(f"method '{name}' signature mismatch (want {want})")
    return (not missing), missing


def check_bounds(module_src: str, template_src: str, targs: dict):
    """Verify each concrete type arg satisfies its parameter's trait bound.
    Raises ConformanceError (a clear compile error) on the first violation."""
    bounds = parse_bounds(template_src)
    for pname, conc in targs.items():
        bound = bounds.get(pname)
        if not bound:
            continue
        ok, missing = check_conformance(module_src, conc, bound)
        if not ok:
            why = '; '.join(missing)
            raise ConformanceError(
                f"type '{conc}' does not conform to trait '{bound}' "
                f"(required by parameter '{pname}'): {why}")


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
    depths = _bracket_depth_by_line(module_src)
    end = _find_block_end(lines, depths, start, base)
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
    for s in Parser(py_tokenize(template_src)).parse_module():
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
    for s in Parser(py_tokenize(concrete_src)).parse_module():
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
    for s in Parser(py_tokenize(concrete_src)).parse_module():
        if isinstance(s, FunctionDef) and s.name == name:
            ret = _mojo_type(s.return_type) if s.return_type else 'void'
            return ret, [_mojo_type(t) for _, t in s.params]
    return 'int64_t', []


class Elaborator:
    """Demand-driven, CAS-backed elaboration service."""

    def __init__(self, gcc=None):
        self.gcc = gcc

    def elaborate_generic_call(self, module_src: str, fn_name: str, type_args, arg_count: int | None = None):
        """Instantiate `fn_name` for `type_args` (a list of concrete type strings)
        via the CAS. Returns a dict {symbol, object, ret, params} or None.

        `arg_count` (the call's actual argument count, when known) disambiguates
        same-named generic overloads distinguished only by arity (e.g.
        itertools.product's 2/3/4-iterable versions) — see extract_fn_source.

        Elaborate-once-ever: the instantiation is content-addressed, so a repeat
        (here or in another program) is a cache hit."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=arg_count if arg_count is not None else len(type_args))
        if tmpl is None:
            return None
        params = type_param_names(tmpl)
        if not params or len(type_args) < len(params):
            return None
        targs = dict(zip(params, type_args[:len(params)]))
        # A variadic type-pack param (`*Ts`) collapses to a single bound type
        # (the first arg's) regardless of how many variadic value-args were
        # actually passed (infer_type_args/zip only ever see one slot for it).
        # Two calls with the same element type but different arities (e.g.
        # `chain(a, b)` vs `chain(a, b, c)`) would otherwise mangle/cache to
        # the identical symbol built for whichever arity compiled first,
        # producing a real argument-count mismatch at the other call site.
        # Fold the call arity into the instantiation identity so each arity
        # gets its own mangled symbol/cache entry.
        if arg_count is not None and any(p.startswith('*') for p in params):
            targs['ArgC'] = arg_count
        # Slice 6: a bounded type parameter must conform before we instantiate.
        check_bounds(module_src, tmpl, targs)

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc)
        _, concrete = mm.monomorphize_source(tmpl, targs)
        ret, ptypes = _signature(concrete, mangled)
        return {'symbol': mangled, 'object': obj, 'cpp_object': cpp_obj,
                'ret': ret, 'params': ptypes}

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
        # Slice 6: a bounded type parameter must conform before we instantiate.
        check_bounds(module_src, tmpl, targs)

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc)
        _, concrete = mm.monomorphize_source(tmpl, targs)
        fields, methods = _struct_layout(concrete, mangled)
        return {'name': mangled, 'fields': fields, 'methods': methods,
                'object': obj, 'cpp_object': cpp_obj}

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
            # No overload matches the argument types — do NOT silently pick the
            # first (review finding #4); let the caller fall through / error.
            return None
        src, ptypes, ret = chosen
        # Sanitize the signature suffix to a valid C identifier (parametric param
        # types like List[Int] contain []/, which are illegal in a C symbol).
        mangled = fn_name + '__' + (mm.safe_suffix('_'.join(ptypes)) if ptypes else 'void')
        renamed = re.sub(rf'\bfn\s+{re.escape(fn_name)}\b', f'fn {mangled}', src, count=1)
        obj, _hit = mm.compile_fn(renamed, gcc=self.gcc)
        return {'symbol': mangled, 'object': obj,
                'ret': _mojo_type(ret) if ret else 'void',
                'params': [_mojo_type(p) for p in ptypes]}

    def elaborate_generic_call_inferred(self, module_src: str, fn_name: str, arg_ctypes):
        """Like elaborate_generic_call but infers the type args from the call
        argument C types (slice 2): `box(42)` with no explicit `[Int64]`."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=len(arg_ctypes))
        if tmpl is None:
            return None
        type_args = infer_type_args(tmpl, arg_ctypes)
        if type_args is None:
            return None
        return self.elaborate_generic_call(module_src, fn_name, type_args, arg_count=len(arg_ctypes))
