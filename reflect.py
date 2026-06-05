#!/usr/bin/env python3
"""Reflection table emitter — MODULE_CACHE_DESIGN.md stage 4.

Generates the C source for the `__mojo_reflect` table (layout in `reflect.h`)
that each dylib exports. The table lists the dylib's exported symbols with name,
C signature, and address — the unified import interface that the compiler's own
`import` path and any C-ABI consumer (any language) read.

This replaces `module_loader.py`'s line-regex signature extraction with an
AST-driven, ABI-accurate one: signatures come from the same type mapping the
codegen uses, so the declared signature matches the emitted symbol exactly.
"""
import re

from mojo_compiler import tokenize, Parser, FunctionDef, StructDef
from gimple_codegen import _mojo_type


def _c_signature(name: str, return_type, params) -> str:
    """Build the C signature string for an exported function, per ABI.md."""
    cret = _mojo_type(return_type) if return_type else 'void'
    cparams = ', '.join(_mojo_type(t) for _, t in params) if params else 'void'
    return f"{cret} {name} ({cparams})"


def collect_exports(stmts) -> list:
    """Exported symbols of a module: top-level, non-underscore functions (and,
    later, methods/types). Returns dicts {name, signature, kind}."""
    exports = []
    for s in stmts:
        if isinstance(s, FunctionDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _c_signature(s.name, s.return_type, s.params),
                'kind': 0,  # MOJO_SYM_FUNCTION
            })
    return exports


def collect_exports_src(src: str) -> list:
    """Exports of a module's source — minus generic templates. A `fn name[...]`
    is parametric: it has no single concrete symbol to put in the dylib, so it is
    NOT a reflection export. Instead, importers see it as a generic and elaborate
    it on demand (ELABORATION.md). (The parser drops `[...]`, so we detect generics
    from the source text.)"""
    generic = set(re.findall(r'\bfn\s+(\w+)\s*\[', src))
    return [e for e in collect_exports(Parser(tokenize(src)).parse_module())
            if e['name'] not in generic]


def _cstr(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def emit_table_c(exports: list) -> str:
    """Emit the C translation unit defining `__mojo_reflect` for these exports.
    Compiled into the dylib alongside the module objects."""
    L = ['/* Generated reflection table — reflect.py (see reflect.h) */',
         '#include "reflect.h"', '']
    # Forward-declare each function so `&name` resolves at dylib link time.
    seen = set()
    for e in exports:
        if e['name'] not in seen:
            seen.add(e['name'])
            L.append(f"extern {e['signature']};")
    L.append('')
    L.append('static const MojoReflectSym _mojo_syms[] = {')
    for e in exports:
        L.append(f"  {{ {_cstr(e['name'])}, {_cstr(e['signature'])}, "
                 f"(void *){e['name']}, {e['kind']} }},")
    if not exports:
        L.append('  { 0, 0, 0, 0 }')  # avoid a zero-length array
    L.append('};')
    L.append('')
    L.append('const MojoReflectTable __mojo_reflect = {')
    L.append(f'  MOJO_REFLECT_MAGIC, MOJO_REFLECT_VERSION, {len(exports)}, 0, _mojo_syms')
    L.append('};')
    return '\n'.join(L) + '\n'
