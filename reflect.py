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

import hashlib
from mojo_compiler import py_tokenize, Parser, FunctionDef, StructDef
from gimple_codegen import _mojo_type, _safe_name, GimpleGen

# Free functions whose C symbol the codegen does NOT overload-mangle (must match
# GimpleGen._NO_OVERLOAD_MANGLE).
_NO_MANGLE_FUNCS = frozenset({
    'main', '_toplevel', '_gimple_main', '_lib_main',
    'compile_to_gimple', 'gimple_codegen_compile_to_gimple', 'py_tokenize',
    'int_write', 'int_parse_module', 'jit_compile_and_execute', 'mojo_print',
})


def _sig_param_ctypes(signature: str) -> list:
    """The C parameter-type list from a C function signature string, stripping
    parameter names — must match gimple_codegen's func_param_types so the overload
    suffix computed here equals the one the codegen emits."""
    inner = signature.split('(', 1)[1].rsplit(')', 1)[0].strip() if '(' in signature else ''
    if not inner or inner == 'void':
        return []
    out = []
    for p in inner.split(','):
        toks = p.split()
        if len(toks) >= 2 and toks[-1].isidentifier():
            out.append(' '.join(toks[:-1]))   # drop the trailing param name
        else:
            out.append(p.strip())
    return out


def _func_export_csym(name: str, signature: str, module_prefix: str = '') -> str:
    """The mangled C symbol for a SYM_FUNCTION export — `_safe_name(name)` plus a
    `module_prefix` qualifier plus the same overload suffix gimple_codegen._func_csym
    appends, so the reflection table advertises the symbol the dylib actually
    defines.

    The `module_prefix` qualifier mirrors gimple_codegen.py's _func_qualifier
    (SB-1 fix, doc/STDLIB-BUGS.md): every free function collect_exports sees is,
    by construction, declared directly in the module being reflected (this
    function's own top-level source) — never an inlined import — the same "this
    compile is that function's true home" condition _func_qualifier checks via
    _local_top_level_func_names, just always true here. Without it, two modules'
    same-named overloads that box down to the same C parameter shape (e.g.
    math.abs(SIMD) and complex.abs(Complex), both boxing to a lone int64_t) would
    still hash to the identical suffix and collide at link — qualifying by the
    function's home module (like struct methods already do via
    _struct_method_csym_static) makes them distinct without touching the hash."""
    base = _safe_name(name)
    if name in _NO_MANGLE_FUNCS:
        return base
    qualified_base = f"{module_prefix}_{base}" if module_prefix else base
    return qualified_base + GimpleGen.overload_suffix_for(_sig_param_ctypes(signature))


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


def collect_exports(stmts, module_prefix: str = '') -> list:
    """Exported symbols of a module: top-level non-underscore functions, plus
    concrete (non-generic) struct types and their methods. Returns dicts
    {name, signature, kind}.

    A concrete struct becomes a TYPE entry (its field layout) plus one METHOD
    entry per public method (`Struct.method`, signature with a leading `self`
    pointer). This is what lets the real-stdlib distribution path work: the
    importer reads the layout + method symbols from the table and links the
    method bodies from the dylib — it never re-reads the type's source.

    `module_prefix` (e.g. 'std_utils__ansi', from
    module_loader.module_name_for_path — the SAME value build_stdlib_dylib.py
    passes as GimpleGen's module_name when compiling this same source) must
    be the caller's own module identity, so a METHOD entry's advertised C
    symbol matches what gimple_codegen._gen_struct_method actually emits for
    THIS module (see GimpleGen._struct_method_csym_static). Two modules
    defining a same-named struct with a same-named method now get distinct
    qualified symbols; without this, both modules' reflection entries would
    read identically ('Color_get_alpha'), and after the dylib build's
    _localize_symbols demotes the second module's own definition to
    file-local, that module's reflection entry would silently resolve to the
    FIRST module's implementation instead of its own."""
    struct_names = {s.name for s in stmts if isinstance(s, StructDef)}
    exports = []
    for s in stmts:
        if isinstance(s, FunctionDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _c_signature(s.name, s.return_type, s.params),
                'kind': SYM_FUNCTION,
                # SB-1 fix: this function's home-module qualifier, so
                # export_csym/_func_export_csym can compute the same
                # module-qualified symbol gimple_codegen._func_csym emits for
                # it (see _func_export_csym's docstring).
                'module_prefix': module_prefix,
            })
        elif isinstance(s, StructDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _struct_layout_sig(s, struct_names),
                'kind': SYM_TYPE,
            })
            _moids = GimpleGen._struct_method_overload_ids(s)
            for m, _oid in zip(getattr(s, 'methods', []), _moids):
                # Mangled C symbol matches gimple_codegen's own
                # _struct_method_csym (module-qualifier + Struct_method +
                # overload-hash suffix when overloaded) — self is the first
                # param, passed by pointer.
                msym = GimpleGen._struct_method_csym_static(module_prefix, s.name, m.name, _oid)
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


def collect_exports_src(src: str, module_prefix: str = '') -> list:
    """Exports of a module's source — minus generic templates. A `fn name[...]`
    is parametric: it has no single concrete symbol to put in the dylib, so it is
    NOT a reflection export. Instead, importers see it as a generic and elaborate
    it on demand (ELABORATION.md). (The parser drops `[...]`, so we detect generics
    from the source text.) `module_prefix` is passed straight through to
    collect_exports — see its docstring."""
    # Mojo functions may be declared `fn` or `def` — both forms must be
    # detected here, or an `def`-declared overload/generic slips past this
    # filter as a normal single export while gimple_codegen (whose own
    # equivalent scans use `(?:fn|def)`, e.g. the local-generics regex a few
    # hundred lines into gen_module) silently drops it from the compiled
    # object (overloaded top-level functions aren't emitted — see
    # gen_module's "Overloaded top-level functions ... can't be emitted as
    # distinct C symbols. Drop them here" pass). The mismatch produced a real
    # bug (BUG-2026-036): std/gpu/host/_nvidia_cuda.mojo's two `def CUDA(...)`
    # overloads were still advertised as one export, so the reflection table
    # forward-declared and took the address of a symbol with zero definitions
    # in the dylib — `extern void CUDA_0c85c9();` with nothing behind it —
    # which crashed EVERY interpreter/compiler invocation at dlopen with
    # "symbol not found in flat namespace '_CUDA_0c85c9'" the moment the
    # stdlib dylib (loaded unconditionally by driver.py's compile_program) is
    # bound, regardless of what Mojo file was actually being run.
    generic = set(re.findall(r'\b(?:fn|def)\s+(\w+)\s*\[', src))
    # Generic struct templates (`struct Name[T]`) aren't a concrete type either —
    # they're instantiated per type-args at use sites (ELABORATION.md slice 5),
    # not a single layout in the dylib. Only concrete structs become TYPE entries.
    generic |= set(re.findall(r'\bstruct\s+(\w+)\s*\[', src))
    # Overloaded names (same name, multiple non-generic defs) aren't a single
    # concrete symbol either — they're selected + instantiated per call site.
    counts = {}
    for n in re.findall(r'\b(?:fn|def)\s+(\w+)\s*\(', src):
        counts[n] = counts.get(n, 0) + 1
    overloaded = {n for n, c in counts.items() if c > 1}
    skip = generic | overloaded
    # An export's base name is the symbol before any `.` (a method export is
    # `Struct.method`); skip a generic struct's TYPE entry *and* all its METHOD
    # entries — the parser drops `[T]`, so `collect_exports` cannot tell they are
    # parametric on its own.
    return [e for e in collect_exports(Parser(py_tokenize(src)).parse_module(), module_prefix)
            if e['name'].split('.', 1)[0] not in skip
            and e['name'].split('.', 1)[0] not in _CLIB_SYMS]


def _cstr(s: str) -> str:
    # Collapse internal whitespace runs to single spaces: a signature string
    # parsed from a multi-line C prototype (e.g. mojo_regex_search's wrapped
    # declaration) carries embedded newlines, and a raw newline inside a C
    # string literal is a syntax error ("missing terminating \" character").
    s = ' '.join(s.split())
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def export_csym(e: dict) -> str:
    """The C symbol an export entry's `(void *)` table address points at.
    SYM_FUNCTION free functions are overload-mangled by the codegen; methods
    already carry their mangled name inside the signature. Shared by
    emit_table_c (to forward-declare/address it) and build_stdlib_dylib.py
    (to verify, via `nm`, that the compiled object actually defines it before
    trusting the export — see that module's `build()`)."""
    if e['kind'] == SYM_FUNCTION:
        return _func_export_csym(e['name'], e['signature'], e.get('module_prefix', ''))
    return e['signature'].split('(', 1)[0].strip().split()[-1].lstrip('*')


def emit_table_c(exports: list) -> str:
    """Emit the C translation unit defining `__mojo_reflect` for these exports.
    Compiled into the dylib alongside the module objects."""
    L = ['/* Generated reflection table — reflect.py (see reflect.h) */',
         '#include "reflect.h"', '']
    # NOTE: we deliberately do NOT emit `typedef struct { <fields> } Name;` for the
    # exported concrete types. Their field bodies reference runtime types (MojoList,
    # _DLHandle, …) and other user structs that aren't declared in this TU, which
    # breaks compilation. The reflection table never uses those types as real C
    # types — callables are forward-declared unprototyped (`extern void sym();`) and
    # every signature is stored as a string — so the typedefs were vestigial.
    # Forward-declare each callable so `&symbol` resolves at dylib link time.
    # TYPE entries (kind 3) are layout descriptors with no runtime symbol — they
    # carry a NULL address and are never forward-declared. The C symbol of a
    # METHOD entry is the name inside its signature, not the lookup key
    # (`Struct.method`), so we extract it.
    seen = set()
    for e in exports:
        if e['kind'] == SYM_TYPE:
            continue
        sym = export_csym(e)
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
            sym = export_csym(e)
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
