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
from fire_compiler import py_tokenize, Parser, FunctionDef, StructDef, VarDecl, IdentExpr
from gimple_codegen import _mojo_type, _safe_name, GimpleGen
from mojo.backend_gimple.emit_funcs import dup_def_signature_key
from mojo.middle.types import _c_field_name

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


def _c_signature(name: str, return_type, params, struct_names=frozenset()) -> str:
    """Build the C signature string for an exported function, per ABI.md.

    `struct_names` (a locally-defined struct's bare name) must resolve via
    `_mt`, the SAME helper `collect_exports`'s method/TYPE entries already use
    below — a free function taking/returning a local struct type (e.g.
    `def engine_place_block(world: World, ...)`) otherwise fell through plain
    `_mojo_type`'s int64_t default (unlike methods, which were never affected:
    `self` is a struct pointer by construction). That wrong C type flows into
    `_func_export_csym`'s overload-suffix hash, so the reflection table's
    "expected" mangled symbol silently diverges from what gimple_codegen's
    `_func_csym` (using its own live-inferred `World *` param type) actually
    emits — build_stdlib_dylib.build()'s nm cross-check then can't find the
    expected symbol and drops the export as "stale", even though the real
    compiled function IS present under its own (differently-hashed) name."""
    cret = _mt(return_type, struct_names) if return_type else 'void'
    cparams = ', '.join(_mt(t, struct_names) for _, t in params) if params else 'void'
    return f"{cret} {name} ({cparams})"


def _struct_field_declared_name(field):
    """The name this one `StructDef` field introduces, or None if it has none.

    A struct body reaches here in the two shapes `fire_compiler.Parser` puts in
    `StructDef.fields`, and they carry the name in different places:

      * `VarDecl` — written as an annotation, `x: int`. The name is `.name`.
      * `AssignStmt` — written as a class-level assignment. `x = 1` and
        `__slots__ = (...)` are fields on this path, and so is `x: int = 0`,
        which the parser deliberately keeps as an `AssignStmt` CARRYING
        `type_ann` rather than a `VarDecl` (see the annotated-assignment branch
        in `Parser.parse_stmt` for why switching it would move every
        `isinstance(stmt, AssignStmt)`-keyed piece of machinery). The name is
        `.target.name`, and `.target` is an `IdentExpr` only for a real
        declaration — a class-level `obj.attr = 1` binds none.

    Reading `.name` directly works for the first shape and raises
    `AttributeError` on the second, and that is not a diagnostic but a traceback
    out of a function with no way to name the file: it killed
    `collect_exports_src` — and with it the whole export probe — on
    `gimple_codegen.py` and `fire_compiler.py`, both of which declare dataclass
    fields in the `x: Type = default` shape, so neither module could be built at
    all.

    This is the SAME fact `formal/model.py:struct_field_name` states for the
    formal backends, and it is stated twice because the two cannot import each
    other: `formal/model.py` is deliberately leaf-most (it imports only `os` and
    `fire_compiler`, so the two formal architectures cannot drift), and
    `reflect.py` is the SHARED export rule `formal/build.py` reads — an edge from
    it into `formal/` would make the gimple dylib's reflection table depend on
    the formal backends. The home that would let them share is
    `fire_compiler.py`, beside the `struct_field_*` shims it already declares.
    """
    if isinstance(field, VarDecl):
        return field.name
    target = getattr(field, "target", None)
    if isinstance(target, IdentExpr):
        return target.name
    return None


def _struct_layout_sig(s, struct_names) -> str:
    """Encode a concrete struct's field layout as a C-ABI descriptor string:
    `struct Name { ctype field; ... }`. The importer parses this back into a
    typedef so it can materialize the type without re-reading source — the real
    import boundary is the reflection table, not the .mojo file (ABI.md).

    A field that has a type but no declarator is left OUT rather than emitted as
    a bare `int64_t ;`, which is not a C declaration at all:
    `_register_reflected_struct` parses these pairs back with
    `decl.rsplit(' ', 1)` and keeps only the ones that split into two, so an
    unnameable field is one this consumer already ignores. Omitting it is also
    the only honest option — inventing a declarator would put a field in the
    importer's typedef that the defining module does not have."""
    fields = []
    for f in getattr(s, 'fields', []):
        ann = getattr(f, 'type_ann', None)
        name = _struct_field_declared_name(f)
        if ann is None or not name:
            continue
        fields.append(f"{_mt(ann, struct_names)} {name};")
    return f"struct {s.name} {{ {' '.join(fields)} }}"


def _mt(ann, struct_names) -> str:
    """C type of a field/method param/return, resolving a local struct type to a
    pointer (the codegen passes/returns aggregates by pointer, per ABI.md)."""
    if ann in struct_names:
        return f"{ann} *"
    return _mojo_type(ann)


def collect_local_struct_names(stmts) -> set:
    """Bare names of every concrete struct DEFINED directly in `stmts`
    (this one module's own parsed source) — no import-graph walk, just
    this file's own top-level StructDefs. Used by build_stdlib_dylib.py's
    BUG-2026-029 cross-file pre-pass (see `collect_exports`'s
    `known_structs` param) to build a whole-build struct-name index BEFORE
    calling `collect_exports` on any single module, so a module-level
    global whose struct type is defined in a SIBLING file (not the global's
    own file) can still be recognized as struct-typed."""
    return {s.name for s in stmts if isinstance(s, StructDef)}


def collect_local_struct_names_src(src: str) -> set:
    """Source-text convenience wrapper for `collect_local_struct_names` —
    see its docstring."""
    return collect_local_struct_names(Parser(py_tokenize(src)).parse_module())


def collect_exports(stmts, module_prefix: str = '', known_structs=None) -> list:
    """Exported symbols of a module: top-level non-underscore functions, plus
    concrete (non-generic) struct types and their methods. Returns dicts
    {name, signature, kind}.

    A concrete struct becomes a TYPE entry (its field layout) plus one METHOD
    entry per public method (`Struct.method`, signature with a leading `self`
    pointer). This is what lets the real-stdlib distribution path work: the
    importer reads the layout + method symbols from the table and links the
    method bodies from the dylib — it never re-reads the type's source.

    `known_structs` (BUG-2026-029, cross-file follow-up to the same-file-only
    fix): an optional set of bare struct names defined ANYWHERE in the whole
    multi-file compile unit this module is being built alongside (see
    build_stdlib_dylib.build()'s pre-pass, `collect_local_struct_names_src`),
    used ONLY to widen which module-level globals below are recognized as
    struct-typed (and therefore get a SYM_GLOBAL export at all) — never to
    resolve a bare function/struct-method name (that stays module-qualified
    everywhere else in this file and in gimple_gen_resolve.py's consumer;
    see the SYM_GLOBAL branch's own docstring for why this is safe).

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
    # BUG-2026-029 cross-file follow-up: `struct_names` above stays
    # THIS-FILE-ONLY for every OTHER use in this function (function param/
    # return types, struct field layouts, method signatures) — those all
    # need this file's own StructDefs to compute a real field layout / csym,
    # which a cross-file name alone can't provide. `all_struct_names` (used
    # ONLY by the VarDecl/SYM_GLOBAL branch below) additionally recognizes a
    # struct defined in a SIBLING file of the same compile unit, since that
    # branch never needs the struct's layout — only whether the name is a
    # struct at all (the accessor is always advertised/consumed as `void *`
    # either way; see that branch's docstring).
    all_struct_names = struct_names | (known_structs or set())
    # BUG-2026-021 parity: when a module REDEFINES a top-level function
    # (same name, identical signature — the duplicated-tail shape), gen_module's
    # duplicate-def pre-pass emits exactly ONE C definition (the LAST copy,
    # interpreter last-wins semantics). Advertise exactly one entry too — keep
    # the last copy here — so the reflection table never lists two rows for a
    # symbol with a single definition behind it. Genuine overloads (different
    # signatures) are dropped by collect_exports_src's `skip` filter below,
    # exactly like before. dup_def_signature_key is THE shared classifier —
    # both sides must classify a duplicated name identically or the table and
    # the dylib disagree about which names have real symbols.
    _dup_defs: dict = {}
    for _s in stmts:
        if isinstance(_s, FunctionDef):
            _dup_defs.setdefault(_s.name, []).append(_s)
    _dup_drop_ids: set = set()
    for _dup_list in _dup_defs.values():
        if len(_dup_list) >= 2 and \
                len({dup_def_signature_key(_d) for _d in _dup_list}) == 1:
            _dup_drop_ids.update(id(_d) for _d in _dup_list[:-1])
    exports = []
    for s in stmts:
        if id(s) in _dup_drop_ids:
            continue
        if isinstance(s, FunctionDef) and not s.name.startswith('_'):
            exports.append({
                'name': s.name,
                'signature': _c_signature(s.name, s.return_type, s.params, struct_names),
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
        elif (isinstance(s, VarDecl) and s.name and not s.name.startswith('_')
                and getattr(s, 'type_ann', None) in all_struct_names):
            # BUG-2026-029: a module-level global's real storage
            # (`_{module}_globals.field`) is not reachable across a dylib
            # boundary at all — an importer only ever sees the OWNING
            # module's globals struct via an `__attribute__((incomplete))`
            # forward declaration (see gimple_module_gen.py's "extern
            # module globals struct" emission), so a direct field read from
            # outside that translation unit isn't valid C. Every module-
            # level global already gets a real READ accessor function
            # unconditionally (gimple_module_gen.py's per-global
            # `{module}__mojo_global_get_{name}` emission, right after the
            # globals-struct instance) — this reflection entry is what lets
            # an IMPORTER discover and call it, mirroring exactly how a
            # METHOD entry above lets an importer call a struct method
            # without seeing its body. Symbol name mirrors that same
            # emission's naming convention exactly (module-qualified, via
            # `_c_field_name`, so it never collides with an unrelated
            # module's same-named global — see `_register_link_imports`'s
            # own docstring on why a QUALIFIED name, not a bare one, is
            # required here).
            #
            # Originally scoped to `type_ann in struct_names` (a struct type
            # DEFINED IN THIS SAME FILE only): this is a lightweight AST-only
            # pre-pass (module_loader/build_stdlib_dylib call it before
            # GimpleGen ever runs), with no access to the full cross-module
            # struct registry GimpleGen itself builds from every import — a
            # global whose struct type lives in some OTHER imported file
            # could not be reliably resolved to `SomeStruct *` here (`_mt`
            # would fall through to `_mojo_type`'s int64_t default).
            #
            # BUG-2026-029 cross-file follow-up: `all_struct_names` (this
            # branch's condition, above) additionally admits a struct name
            # from ANOTHER file of the same compile unit, via the caller-
            # supplied `known_structs` (build_stdlib_dylib.build()'s own
            # whole-build struct-name pre-pass — see collect_exports's own
            # docstring). This is safe DESPITE not knowing the struct's real
            # field layout, because the consumer of this exact export kind
            # (gimple_gen_resolve.py's `_register_link_imports`, SYM_GLOBAL
            # branch) NEVER uses this advertised return type either way — it
            # always registers the accessor as returning generic `void *`
            # (the importing translation unit has no `struct World {...}`
            # declaration to spell the real type with at all, same-file or
            # not). `_mt(s.type_ann, all_struct_names)` below is therefore
            # only ever used for a HUMAN-readable signature string / the
            # gsym-extraction convenience in `export_csym` — not for any
            # type-correctness-sensitive decode — so advertising `World *`
            # for a cross-file struct (instead of silently misreporting
            # int64_t) is strictly more correct, never less safe. Non-struct
            # globals (int64_t, MojoList*/Dict*/Set*, char *, an
            # UnsafePointer's already-erased pointer, ...) are still skipped
            # for the same reason as before: this export list has no way to
            # know ahead of time which of those get boxed at the C-struct-
            # field level, so it can't advertise a signature guaranteed to
            # match — `known_structs` only ever WIDENS which names count as
            # "a struct", it never changes how a non-struct global is
            # handled.
            gsym = f"{_c_field_name(module_prefix)}__mojo_global_get_{_c_field_name(s.name)}"
            exports.append({
                'name': s.name,
                'signature': f"{_mt(s.type_ann, all_struct_names)} {gsym} (void)",
                'kind': SYM_GLOBAL,
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
    # The two clock counters fire_runtime.h declares so compiled Mojo can TIME
    # itself. They are declared there -- not in <time.h>, which also declares
    # `time`, `strftime`, `localtime`, `gmtime`, `mktime` and `clock_gettime`
    # and would drag every one of them into this comparison against the
    # stdlib's own `external_call` declarations -- but they are LIBSYSTEM's
    # definitions, not the runtime's, so advertising them in the dylib export
    # table is a lie the dylib test reports as
    # "declared with no definition in this dylib". Same rule as every other
    # name above, for the same reason: the C library provides it.
    'clock_gettime_nsec_np', 'mach_absolute_time',
})


# The four rules of doc/ABI.md's public-symbol rule, as names a diagnostic can
# print. `export_exclusions` below reports WHICH one excluded each declaration,
# and a refusal that has to explain itself has to be able to name the rule that
# actually fired — an unexplained "this module exports nothing" sends the next
# reader looking for a construct the file does not contain.
EXCL_PRIVATE = "private"
EXCL_GENERIC = "generic-template"
EXCL_OVERLOADED = "overloaded"
EXCL_CLIB = "c-library-symbol"


def _excluded_name_sets(src: str, parsed) -> tuple:
    """(generic, overloaded): the two name sets `collect_exports_src` skips on.

    Split out of `collect_exports_src` so `export_exclusions` can report the
    same two sets, and so there is exactly one computation of each: the export
    table and the refusal that explains it cannot then disagree about which
    names are templates."""
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
    # BUG-2026-021: computed from the PARSED top-level FunctionDefs with the
    # SAME dup_def_signature_key rule gen_module's duplicate-def pre-pass
    # uses, not a raw def-count regex. The old count treated an accidental
    # duplicated tail (`def main():` twice — identical signature, codegen now
    # keeps the last copy and really emits it) as an overload and dropped the
    # name from the table entirely — zero advertised entries behind a symbol
    # that DID exist. The regex also over-matched same-named METHODS of
    # unrelated structs (a free `add` plus two structs' `add` methods read as
    # "overloaded"), silently un-advertising perfectly concrete free
    # functions. Top-level scope here matches the pre-pass's exactly.
    dup_defs: dict = {}
    for _s in parsed:
        if isinstance(_s, FunctionDef):
            dup_defs.setdefault(_s.name, []).append(_s)
    overloaded = set()
    for _name, _defs in dup_defs.items():
        if len(_defs) >= 2 and \
                len({dup_def_signature_key(_d) for _d in _defs}) != 1:
            overloaded.add(_name)
    return generic, overloaded


def export_exclusions(src: str, parsed=None) -> dict:
    """{declared name: which rule of doc/ABI.md's export rule excluded it}.

    The four rules, in the order they are tested — a name that several exclude
    is reported under the FIRST, so every name in the result has one reason and
    that reason is one the rule really applied to it:

      EXCL_PRIVATE     a leading `_` (checked here rather than in
                       `collect_exports`, which never emits the name at all, so
                       that a diagnostic can still say the file HAS a private
                       declaration it is otherwise about to deny having).
      EXCL_CLIB        a C library symbol this path resolves with `dlsym`.
      EXCL_OVERLOADED  more than one definition of the name.
      EXCL_GENERIC     a template.

    A name absent from the result is exported. This is the ONE place the rule
    is stated, and `collect_exports_src` filters through it — so the exclusion
    table and the export table are two views of one decision rather than two
    implementations that can drift, which is what let a refusal come to name
    "every declaration in it is private" about a file with fifteen public
    functions in it (bugs/FORMAL_known_limits.md §1.3).

    The generic test is `collect_exports_src`'s own, regex over source text and
    keyed by NAME, and it stays that way here: a per-definition test would
    change which names reach a dylib, which is a change to what the compiler
    accepts, and it is not this function's to make. The known imprecision is
    that the regex also matches a NESTED `def name[...]` inside a function body,
    so a name can be filed as a template when the only generic spelling of it is
    a local one. That is recorded rather than fixed, for the reason above."""
    if parsed is None:
        parsed = Parser(py_tokenize(src)).parse_module()
    generic, overloaded = _excluded_name_sets(src, parsed)
    out = {}
    for s in parsed:
        if not isinstance(s, (FunctionDef, StructDef)):
            continue
        name = s.name
        if name.startswith('_'):
            out[name] = EXCL_PRIVATE
        elif name in _CLIB_SYMS:
            out[name] = EXCL_CLIB
        elif name in overloaded:
            out[name] = EXCL_OVERLOADED
        elif name in generic:
            out[name] = EXCL_GENERIC
    return out


def collect_exports_src(src: str, module_prefix: str = '', known_structs=None) -> list:
    """Exports of a module's source — minus generic templates. A `fn name[...]`
    is parametric: it has no single concrete symbol to put in the dylib, so it is
    NOT a reflection export. Instead, importers see it as a generic and elaborate
    it on demand (ELABORATION.md). (The parser drops `[...]`, so we detect generics
    from the source text.) `module_prefix` and `known_structs` are passed straight
    through to collect_exports — see its docstring."""
    _parsed = Parser(py_tokenize(src)).parse_module()
    excluded = export_exclusions(src, _parsed)
    # An export's base name is the symbol before any `.` (a method export is
    # `Struct.method`); a generic struct's TYPE entry *and* all its METHOD
    # entries are skipped together — the parser drops `[T]`, so `collect_exports`
    # cannot tell they are parametric on its own.
    return [e for e in collect_exports(_parsed, module_prefix, known_structs)
            if e['name'].split('.', 1)[0] not in excluded]


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
    trusting the export — see that module's `build()`).

    An entry that carries its OWN `csym` is taken at its word, before any of
    that. A C prototype is not a Mojo function declaration: it has no home
    module to qualify and no overload suffix, because the C compiler already
    gave it its name. `collect_runtime_exports_h` produces those entries and
    is the one that knows this, so it states it there rather than leaving it
    to be inferred here from the ABSENCE of a `module_prefix` — which is also
    what a hand-built `extra_exports` entry looks like."""
    if e.get('csym'):
        return e['csym']
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

# A C prototype: return type, name, parameter list, terminating `;`.
#
# The `\*?` between the return type and the name is load-bearing, and was
# missing until FORMAL.md phase 0's link audit needed this scanner to be
# trustworthy. The return-type group `[\w][\w\s\*]*?` is NON-GREEDY, and the
# separator used to be a bare `\s+`, so a declaration written the way C writes
# a pointer return — `char *mojo_str_new(char *s)`, with the `*` attached to the
# type — could not match at all: the group stopped at `char`, `\s+` ate the
# space, and the next character was `*` where a name was required. Every
# pointer-returning function was therefore dropped from the export list.
#
# Measured on this tree, before the fix: `fire_runtime.h` yielded 260 exports
# of 470 prototypes, `fire_sqlite3.h` 15 of 22, `fire_zlib.h` 2 of 6,
# `fire_ssl.h` 9 of 13, `fire_ncurses.h` 16 of 18, `fire_python.h` 6 of 15.
# Every loss was a pointer return — `mojo_str_new`, `mojo_c_getenv`,
# `mojo_path_join`, `mojo_chr`, `int64_t_basename`, all of `mojo_sqlite3_open`,
# `_query` and `_query_dict`. After the fix: 459, 22, 6, 13, 18, 15, with the
# only remaining gaps being `static inline` helpers (no external symbol, so
# correctly absent) and one name mentioned in a comment.
#
# This mattered beyond the audit: `build_stdlib_dylib.py` builds the stdlib
# dylib's reflection table with this function, so the shipped dylib was
# advertising 260 of its own 459 runtime entry points — a C client resolving
# `mojo_c_getenv` through reflection would have been told it did not exist.
#
# A THIRD defect, found while FORMAL.md phase 2 needed this scanner to be not
# merely complete but ACCURATE, and it is why the pattern is now what it is.
# The fix above made pointer returns MATCH; it did not make them be RECORDED as
# pointers. The separator's `\*?` consumed the very `*` that belongs to the type,
# so `char *mojo_str_new(char *s)` came out of the table as
# `char mojo_str_new (char *s)`, a function returning a string pointer recorded
# as returning a `char` by value. Every one of the 92 `char *` and 39
# `MojoList *` returns in `fire_runtime.h` was misstated that way, so a
# consumer reading the table to decide what a value IS would have been told the
# opposite of the truth. The return type is a group of its own now, so the stars
# are captured rather than skipped.
#
# The parameter group moved from `[^)]*` to `[^;{}]*` for the same reason: a
# `)` inside a parameter list (a cast, or a function-pointer parameter) used to
# end the match early, and neither a `;` nor a brace can appear in one. A
# `static inline` helper's BODY is a separate matter and is handled by
# `_NOT_A_RETURN_TYPE` below.
#
# `base` is at least one identifier and `name` at least one more, and the two
# are separated by a REQUIRED separator — either a `*+` (which is captured, into
# `ptr`) or a `[ \t]+`. C always separates a return type from its declarator
# that way, and requiring it is what stops the two adjacent groups from
# splitting one identifier between them: without it `return` parsed as
# base=`retur` + name=`n`, and every `static inline` body in the runtime
# contributed a garbage export. A bare call statement (`mojo_foo(l, x());`)
# cannot match either — it has ONE identifier before the `(`, a declaration has
# two.
_PROTO_RE = re.compile(
    r'^[ \t]*(?P<base>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*)'
    r'(?:[ \t]*(?P<ptr>\*+)[ \t]*|[ \t]+)'
    r'(?P<name>[A-Za-z_]\w*)[ \t]*\((?P<params>[^;{}]*)\)[ \t]*;', re.MULTILINE)

# Words that cannot begin a return type, so a statement inside a `static inline`
# body is not mistaken for a declaration. `return` is the one that reached the
# table: `mojo_fnptr_call_0`'s body ends `return ((int64_t (*)(void))fp)();`,
# and the cast's parentheses are exactly what the old `[^)]*` could not get
# past — so the scanner read `return mojo_maybe_bound_call_0 (f);`, a statement
# inside a function with no external symbol, as a prototype, and put
# `mojo_fnptr_call_0` … `_4` into the *shipped dylib's* reflection table with
# the address of a `static inline` helper taken. That is the BUG-2026-036 shape
# (`extern void <sym>();` plus `&sym` with nothing defined behind it) reached
# from the other direction. `test_runtime_header_scan.py`'s
# `test_non_exports_stay_excluded` did not catch it because it pins
# `mojo_bound_method_call_0` and not the `mojo_fnptr_call_*` family.
_NOT_A_RETURN_TYPE = ('typedef', 'struct', 'union', 'enum', 'static', 'extern',
                      'inline', 'return', '#')

# Comments, removed before scanning. A regex over raw C text has no notion of a
# comment, and the runtime headers document their return values in prose that
# contains parentheses: `/* … Returns NULL on failure. */ void
# *mojo_sqlite3_query(void *db, const char *sql);` was scanned as
# base=`SQLITE_OK … Returns`, name=`Returns`, parameters=the entire rest of the
# comment AND the real prototype — so the table advertised a symbol named
# `Returns` and lost `mojo_sqlite3_query` itself. The old `[^)]*` parameter group
# happened to stop at the comment's first `)`, which is the only reason this was
# ever right; widening the group to admit a cast in a real parameter list is what
# made it necessary. A blank is left behind rather than nothing, so two
# declarations either side of a comment cannot be glued into one token.
_COMMENT_RE = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)


def collect_runtime_exports_h(header_path: str) -> list:
    """Parse a C header for public function prototypes → reflection export entries.
    Used to include fire_runtime.h symbols in the stdlib dylib's reflection table
    without re-compiling the runtime (it's already linked as a first-class dylib).

    Each entry carries `'ret'` and `'params'` as well as the display
    `'signature'`, so a consumer that needs to know what a value IS — FORMAL.md
    phase 2's word/box decision, which refuses a call by the TYPE it would have
    to move — reads the parsed types rather than re-parsing the signature string
    with a second, drifting grammar. One scan, one set of types."""
    exports = []
    seen = set()
    with open(header_path) as f:
        content = f.read()
    content = _COMMENT_RE.sub(' ', content)
    for m in _PROTO_RE.finditer(content):
        base = ' '.join(m.group('base').split())
        ptr = m.group('ptr')
        ret = f"{base} {ptr}" if ptr else base
        name = m.group('name')
        params = ' '.join(m.group('params').split())
        if any(kw in ret for kw in _NOT_A_RETURN_TYPE):
            continue
        if name.startswith('_') or name in seen or name in _CLIB_SYMS:
            continue
        seen.add(name)
        # The C spelling, `MojoStr *name(...)` — the stars touch the name, which
        # is how the header writes it and how a reader reads it back.
        decl = f"{base} {ptr}{name}" if ptr else f"{base} {name}"
        sig = f"{decl} ({params or 'void'})"
        exports.append({'name': name, 'signature': sig, 'kind': SYM_FUNCTION,
                        'ret': ret, 'params': params,
                        # `csym`: this is a C prototype, so the C symbol IS
                        # `name` — no module qualifier, no overload suffix.
                        # Both are Mojo codegen concepts and applying them to a
                        # C declaration computes a symbol that does not exist,
                        # which is how 429 of fire_runtime.h's entry points
                        # went unadvertised (INTERFACE-REQUESTS.md, [2] -> [3]
                        # section A). Stated HERE because this is the producer
                        # that knows it, not inferred by the consumer from a
                        # missing `module_prefix`.
                        'csym': name})
    return exports
