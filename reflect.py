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


# Symbol kinds — must match reflect.h.
SYM_FUNCTION = 0
SYM_METHOD = 1
SYM_GLOBAL = 2
SYM_TYPE = 3


def _c_signature(name: str, return_type, params) -> str:
    """Build the C signature string for an exported function, per ABI.md."""
    cret = _mojo_type(return_type) if return_type else 'void'
    cparams = ', '.join(_mojo_type(t) for _, t in params) if params else 'void'
    return f"{cret} {name} ({cparams})"


def _struct_layout_sig(s, struct_names) -> str:
    """Encode a concrete struct's field layout as a C-ABI descriptor string:
    `struct Name { ctype field; ... }`. The importer parses this back into a
    typedef so it can materialize the type without re-reading source — the real
    import boundary is the reflection table, not the .mojo file (ABI.md)."""
    fields = []
    for f in getattr(s, 'fields', []):
        ann = getattr(f, 'type_ann', None)
        if ann is None:
            continue
        fields.append(f"{_mt(ann, struct_names)} {f.name};")
    return f"struct {s.name} {{ {' '.join(fields)} }}"


def _mt(ann, struct_names) -> str:
    """C type of a field/method param/return, resolving a local struct type to a
    pointer (the codegen passes/returns aggregates by pointer, per ABI.md)."""
    if ann in struct_names:
        return f"{ann} *"
    return _mojo_type(ann)


def collect_exports(stmts) -> list:
    """Exported symbols of a module: top-level non-underscore functions, plus
    concrete (non-generic) struct types and their methods. Returns dicts
    {name, signature, kind}.

    A concrete struct becomes a TYPE entry (its field layout) plus one METHOD
    entry per public method (`Struct.method`, signature with a leading `self`
    pointer). This is what lets the real-stdlib distribution path work: the
    importer reads the layout + method symbols from the table and links the
    method bodies from the dylib — it never re-reads the type's source."""
    struct_names = {s.name for s in stmts if isinstance(s, StructDef)}
    exports = []
    for s in stmts:
        if isinstance(s, FunctionDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _c_signature(s.name, s.return_type, s.params),
                'kind': SYM_FUNCTION,
            })
        elif isinstance(s, StructDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _struct_layout_sig(s, struct_names),
                'kind': SYM_TYPE,
            })
            for m in getattr(s, 'methods', []):
                # Mangled C symbol is Struct_method (matches gimple_codegen);
                # self is the first param, passed by pointer.
                msym = f"{s.name}_{m.name}"
                cret = _mt(m.return_type, struct_names) if m.return_type else 'void'
                cparams = [f"{s.name} *"] + [
                    _mt(t, struct_names) for n, t in m.params if n != 'self']
                exports.append({
                    'name': f"{s.name}.{m.name}",   # lookup key (method)
                    'signature': f"{cret} {msym} ({', '.join(cparams)})",
                    'kind': SYM_METHOD,
                })
    return exports


# C stdlib symbols that may appear in Mojo modules but are already available
# via dlsym from the system dylibs — no need to advertise them.
_CLIB_SYMS = frozenset({
    'exit', 'abort', 'puts', 'printf', 'fprintf', 'sprintf', 'snprintf',
    'malloc', 'free', 'calloc', 'realloc', 'memcpy', 'memset', 'memmove',
    'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat',
    'strdup', 'strtol', 'strtod', 'atoi', 'atof', 'rand', 'srand', 'time',
    'open', 'close', 'read', 'write', 'fopen', 'fclose', 'fread', 'fwrite',
    'fgets', 'fputs', 'getline', 'setjmp', 'longjmp', 'signal',
})


def collect_exports_src(src: str) -> list:
    """Exports of a module's source — minus generic templates. A `fn name[...]`
    is parametric: it has no single concrete symbol to put in the dylib, so it is
    NOT a reflection export. Instead, importers see it as a generic and elaborate
    it on demand (ELABORATION.md). (The parser drops `[...]`, so we detect generics
    from the source text.)"""
    generic = set(re.findall(r'\bfn\s+(\w+)\s*\[', src))
    # Generic struct templates (`struct Name[T]`) aren't a concrete type either —
    # they're instantiated per type-args at use sites (ELABORATION.md slice 5),
    # not a single layout in the dylib. Only concrete structs become TYPE entries.
    generic |= set(re.findall(r'\bstruct\s+(\w+)\s*\[', src))
    # Overloaded names (same name, multiple non-generic defs) aren't a single
    # concrete symbol either — they're selected + instantiated per call site.
    counts = {}
    for n in re.findall(r'\bfn\s+(\w+)\s*\(', src):
        counts[n] = counts.get(n, 0) + 1
    overloaded = {n for n, c in counts.items() if c > 1}
    skip = generic | overloaded
    # An export's base name is the symbol before any `.` (a method export is
    # `Struct.method`); skip a generic struct's TYPE entry *and* all its METHOD
    # entries — the parser drops `[T]`, so `collect_exports` cannot tell they are
    # parametric on its own.
    return [e for e in collect_exports(Parser(tokenize(src)).parse_module())
            if e['name'].split('.', 1)[0] not in skip
            and e['name'].split('.', 1)[0] not in _CLIB_SYMS]


def _cstr(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def emit_table_c(exports: list) -> str:
    """Emit the C translation unit defining `__mojo_reflect` for these exports.
    Compiled into the dylib alongside the module objects."""
    L = ['/* Generated reflection table — reflect.py (see reflect.h) */',
         '#include "reflect.h"', '']
    # Emit a typedef for each exported concrete struct type so the method
    # forward-declarations below (which take `Name *`) type-check.
    for e in exports:
        if e['kind'] == SYM_TYPE:
            body = e['signature'].split('{', 1)[1].rsplit('}', 1)[0].strip()
            L.append(f"typedef struct {{ {body} }} {e['name']};")
    L.append('')
    # Forward-declare each callable so `&symbol` resolves at dylib link time.
    # TYPE entries (kind 3) are layout descriptors with no runtime symbol — they
    # carry a NULL address and are never forward-declared. The C symbol of a
    # METHOD entry is the name inside its signature, not the lookup key
    # (`Struct.method`), so we extract it.
    seen = set()
    for e in exports:
        if e['kind'] == SYM_TYPE:
            continue
        sym = e['signature'].split('(', 1)[0].strip().split()[-1].lstrip('*')
        if sym not in seen:
            seen.add(sym)
            # Unprototyped extern avoids referencing struct types that may not
            # be declared in this TU — we only need the symbol's address.
            L.append(f"extern void {sym}();")
    L.append('')
    L.append('static const MojoReflectSym _mojo_syms[] = {')
    for e in exports:
        if e['kind'] == SYM_TYPE:
            addr = '0'
        else:
            sym = e['signature'].split('(', 1)[0].strip().split()[-1].lstrip('*')
            addr = '(void *)' + sym
        L.append(f"  {{ {_cstr(e['name'])}, {_cstr(e['signature'])}, "
                 f"{addr}, {e['kind']} }},")
    if not exports:
        L.append('  { 0, 0, 0, 0 }')  # avoid a zero-length array
    L.append('};')
    L.append('')
    L.append('const MojoReflectTable __mojo_reflect = {')
    L.append(f'  MOJO_REFLECT_MAGIC, MOJO_REFLECT_VERSION, {len(exports)}, 0, _mojo_syms')
    L.append('};')
    return '\n'.join(L) + '\n'


# ── Runtime header reflection ─────────────────────────────────────────────────

_PROTO_RE = re.compile(
    r'^\s*([\w][\w\s\*]*?)\s+(\w+)\s*\(([^)]*)\)\s*;', re.MULTILINE)

def collect_runtime_exports_h(header_path: str) -> list:
    """Parse a C header for public function prototypes → reflection export entries.
    Used to include mojo_runtime.h symbols in the stdlib dylib's reflection table
    without re-compiling the runtime (it's already linked as a first-class dylib)."""
    exports = []
    seen = set()
    with open(header_path) as f:
        content = f.read()
    for m in _PROTO_RE.finditer(content):
        ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
        if any(kw in ret for kw in ('typedef', 'struct', 'static', '#', 'extern')):
            continue
        if name.startswith('_') or name in seen or name in _CLIB_SYMS:
            continue
        seen.add(name)
        sig = f"{ret} {name} ({params or 'void'})"
        exports.append({'name': name, 'signature': sig, 'kind': SYM_FUNCTION})
    return exports
