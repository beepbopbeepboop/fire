"""GIMPLE backend for the Mojo compiler.

Consumes AST produced by mojo_compiler.py and emits C source with
__GIMPLE-annotated functions for gcc-mp-15 -fgimple.
"""
from __future__ import annotations

import os
import re
import sys
import hashlib
import zlib
import dataclasses

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    py_tokenize, Parser,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
from generated_dispatch import (
    _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT,
    _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS,
    _STMT_DISPATCH, _EXPR_DISPATCH,

)
# Module-level (not per-GimpleGen-instance) because a fresh GimpleGen is
# constructed once per file during whole-program/transitive-closure
# flattening (--dump-full, mojo.py build), so an instance attribute would
# reset for every file and never actually dedup anything. Tracks which
# unresolved-import stub/definition C symbol names have already been
# emitted into the CURRENT flattened output, so importing the same
# never-defined name from multiple files (e.g. `from module_loader import
# STDLIB_PATH` in imports.py/version.py/regex_compile.py) only emits ONE
# definition instead of one per importing file - the latter is a hard
# "redefinition of X" GCC error since it's all one translation unit.
_emitted_unresolved_stub_syms: set[str] = set()
# Dedup for the `_mojo_type_name` tag→name table emitted in gen_module's
# preamble: the whole flattened closure is ONE translation unit, so a
# `static char * _mojo_type_name` definition must appear exactly once even
# when several modules' bodies call `type(x).__name__` (gimple_codegen,
# myinterpreter, ...). Cleared per compile_to_gimple call like
# _emitted_unresolved_stub_syms.
# BUG-fix B2: was a set used purely as a boolean flag (`.add(True)`); it is
# now a plain bool with identical reset points (every public compile_* entry).
_emitted_type_name_emitted: bool = False


# ---- constants displaced by the Wave-2 leaf split (restored verbatim) ----


# ---------------------------------------------------------------------------
# Operator tables  (imported from generated_dispatch.py)
# ---------------------------------------------------------------------------

_BIN_OPS  = _GD_BIN_OPS   # Mojo op → C infix op; **, //, @ handled separately
_CMP_OPS  = _GD_CMP_OPS   # operators whose result type is _Bool




# Opaque runtime struct types whose `X *` form is a real, forward-declared C++
# type this compiler emits (so a module-global annotated with one — e.g.
# `x: MojoDict = {}` — can be typed as a pointer to it in a globals struct).
# A `X *` whose basename X is none of these AND not a user-defined mojo `struct`
# (checked against self.struct_field_types at the call site) is an opaque
# Python CLASS used only as a type annotation — emitting `X field;` would be
# an undeclared type — so such globals are forced to `void *`. See
# GimpleGen._cpp_known_ptr_struct.
_CPP_OPAQUE_PTR_STRUCTS = frozenset({
    'MojoList', 'MojoDict', 'MojoSet', 'MojoStr', 'MojoStrIter',
    'MojoListIter', 'MojoDictIter', 'MojoSetIter',
    'MojoGenerator', 'MojoAsync', 'MojoBoundMethod', 'PyObject',
    'MojoCompletedProcess', 'MojoFileHandle',
})




# Fixed-size-array struct-field-annotation shape: `var x: [ElemType; N]`
# (mojo_compiler.py's `_parse_type_ann_inner` LBRACKET branch captures the
# bracket contents verbatim via `_capture_bracketed_text`, which joins
# tokens with single spaces — so `[Block; MAX_BLOCKS]` round-trips as the
# string "[Block ; MAX_BLOCKS]"). `N` may be a decimal-literal size or a
# NAME referencing a module-level `comptime NAME: Int = <int-literal-or-
# foldable-expr>` constant (the common real-world shape, e.g. box.3d/game's
# `comptime MAX_BLOCKS: Int = 4096`) — see GimpleGen._module_const_int.
# See bugs/BUG-2026-008.md (box.3d/game) for the real-world motivating case.
_FIXED_ARRAY_ANN_RE = re.compile(
    r'^\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*([A-Za-z_0-9]+)\s*\]$')



# Runtime-owned, FIXED-layout C structs this codegen itself defines (in
# runtime/mojo_runtime.h or its own emitted preamble), as opposed to a
# struct arising from a user's own `class`/`struct` statement (those are
# never hardcoded here — they're always discovered via StructDef
# processing into `self.struct_field_types`, which is mutable/extensible:
# a not-yet-seen field on a USER struct legitimately grows the struct, see
# `_collect_self_assigns`). A fixed-layout runtime struct has no such
# extensibility (`MojoBoundMethod` is exactly `{ void *fn; void *self; }`,
# hardcoded in mojo_runtime.h, forever) — an attribute name that isn't one
# of its real C fields must route through the same dynamic-attribute
# dispatch (`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr` ->
# `mojo_obj_getattr`/`mojo_setattr`'s real per-object storage, see
# bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md Step 4) instead
# of a direct `->member` access GCC would reject outright ("has no member
# named ..."). Confirmed real instance: `inner.__name__ = 'read_nonlocal'`
# / `f.__name__` on a `MojoBoundMethod` (Tools/scripts/var_access_
# benchmark.py) and `__del__._slotted = True` (Tools/c-analyzer/c_common/
# clsutil.py). `MojoGenerator`/`MojoAsync` are included per the same doc's
# plan even though both are fully opaque (`typedef struct MojoGenerator
# MojoGenerator;`, no C-visible fields at all) and so are not confirmed to
# ever reach this exact path in practice — harmless to list defensively;
# see `_struct_name_owner`'s cross-module collision guard for why a user
# struct can never collide with one of these names.
_FIXED_RUNTIME_STRUCT_NAMES = frozenset({
    'MojoBoundMethod', 'MojoGenerator', 'MojoAsync',
})


_LIST_RETURNING_METHODS = {'split', 'rsplit', 'splitlines'}



# Return types of well-known runtime functions (seeds func_return_types)
_RUNTIME_FUNCS: dict[str, str] = {
    # exceptions (mojo_try_push is a macro, not a function)
    'mojo_exc_pop':               'void',
    'mojo_raise':                 'void',
    'mojo_exc_msg_set':           'void',
    'mojo_exc_msg_get':           'char *',
    # list
    'mojo_list_new':              'MojoList *',
    'mojo_list_len':              'int64_t',
    'mojo_list_get_int':          'int64_t',
    'mojo_list_get_double':       'double',
    'mojo_list_get_str':          'char *',
    'mojo_list_contains_int':     'int',
    'mojo_list_contains_double':  'int',
    'mojo_list_contains_str':     'int',
    'mojo_list_set_int':          'void',
    'mojo_list_set_double':       'void',
    'mojo_list_set_str':          'void',
    'mojo_list_insert_int':       'void',
    'mojo_list_insert_double':    'void',
    'mojo_list_insert_str':       'void',
    'mojo_list_slice':            'MojoList *',
    'mojo_list_concat':           'MojoList *',
    # dict
    'mojo_dict_new':              'MojoDict *',
    'mojo_dict_get_int':          'int64_t',
    'mojo_dict_get_double':       'double',
    'mojo_dict_get_str':          'char *',
    'mojo_dict_contains':         'int',
    'mojo_dict_len':              'int64_t',
    'mojo_dict_iter_new':         'MojoDictIter *',
    'mojo_dict_iter_next':        'int',
    'mojo_dict_iter_key':         'char *',
    'mojo_dict_iter_val_int':     'int64_t',
    'mojo_dict_iter_val_double':  'double',
    'mojo_dict_iter_val_str':     'char *',
    'mojo_dict_iter_free':        'void',
    # set
    'mojo_set_new':               'MojoSet *',
    'mojo_set_contains_int':      'int',
    'mojo_set_contains_str':      'int',
    'mojo_set_len':               'int64_t',
    'mojo_set_iter_new':          'MojoSetIter *',
    'mojo_set_iter_next':         'int',
    'mojo_set_iter_val_int':      'int64_t',
    'mojo_set_iter_val_str':      'char *',
    'mojo_set_iter_free':         'void',
    # string
    'mojo_str_new':               'MojoStr *',
    'mojo_str_concat':            'MojoStr *',
    'mojo_str_len':               'int64_t',
    'mojo_str_data':              'char *',
    'mojo_str_char_at':           'char',
    'mojo_str_eq':                'int',
    'mojo_str_contains':          'int',
    'mojo_str_slice':             'MojoStr *',
    'mojo_cstr_slice':            'char *',
    'mojo_cstr_region_eq':        'int',
    'mojo_str_from_char':         'MojoStr *',
    'mojo_str_repeat':            'MojoStr *',
    'mojo_str_to_int':            'int64_t',
    'mojo_str_to_float':          'double',
    # C-string utilities used by the REPL and string methods
    'input':          'char *',
    'string_lower':   'char *',
    'string_strip':   'char *',
    'string_upper':   'char *',
    'compile_to_gimple': 'char *',
    # Interpreter/bridge functions (provided by runtime or compiled code)
    'py_tokenize':           'MojoList *',
    'Parser':             'Parser *',    # Parser() constructor
    'Interpreter':        'Interpreter *',
}



# Integer scalar C types. GIMPLE rejects ANY implicit conversion between two
# different integer types (not just narrowing): an int64_t ABI-widened
# parameter assigned into a uint8_t local is a "non-trivial conversion in
# 'parm_decl'" (std/builtin/dtype.mojo's `_match(self, mask: UInt8)` — the
# param is physically int64_t while its scalar-newtype semantic type is
# uint8_t), and the reverse (uint8_t -> int64_t) is rejected just as hard.
# The codegen must emit an explicit cast every time the *declared* C type of a
# value differs from the destination's C type.
_SCALAR_INT_TYPES = frozenset({
    'int', 'char', '_Bool',
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
})



# Well-known Python str methods whose return type is unconditionally str/list
# (never bool/int, unlike e.g. find()/startswith()) -- used ONLY to infer a
# struct field's C type from a chained method call in its __init__ assignment
# (`self.field = obj.attr.replace(...)`), where the call's func is a
# MemberExpr (not a bare IdentExpr the generic CallExpr-name dispatch above
# already recognizes) so it fell through to a blind 'int' default otherwise.
_STR_RETURNING_METHODS = {
    'replace', 'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'format',
    'zfill', 'capitalize', 'title', 'join', 'swapcase', 'expandtabs',
    'casefold', 'center', 'ljust', 'rjust', 'removeprefix', 'removesuffix',
}



# ---- Wave-2 leaf extraction re-imports (verbatim moves; see REF.html §6) ----
from gimple_ctypes import (
    TypeLattice, _debug_note, _TYPE_MAP, _FLOAT_TYPES, _split_top_level_commas,
    _class_attr_ctype, _mojo_type, _result_type, _elem_type, _c_id, _c_var_decl,
    _printf_fmt, _strip_mojo_param_modifiers, _walk_type_expr, _param_sig_str,
    _method_overload_id, demangle_overload, _COMMON_METHOD_NAMES, _C_KEYWORDS,
    _CPP_KEYWORD_FIELDS, _C_PARAM_EXTRA_KEYWORDS, _C_MACRO_NAMES,
    _PSEUDO_DUNDER_ATTRS, _safe_field, _C_RESERVED_FUNCS, _FORCE_RENAME_RESERVED,
    _safe_name, _stub_guard_name, _c_field_name, _import_targets, _c_escape,
    _str_literal_value_is_fstring, _extract_init_expr, _module_toplevel_name,
    _module_init_name, _used_idents_node, _CPP_CALLABLE_CTYPE,
    _CPP_CALLABLE_CTYPE_1ARG,
)
from gimple_solvers import (
    _find_idents, _scan_for_escaping, _find_escaping, EscapeAnalyzer,
    LayoutSolver, DispatchTable, DispatchPattern, DispatchSolver,
    FunctionCompilability, TypePromotionSolver, ClosureInfo,
)
from gimple_exprtypes import (
    _walk_ast, _UnsupportedGeneratorShape, _UnsupportedAsyncShape,
    _is_asyncio_sleep_call, _is_asyncio_sock_recv_call, _async_quick_eligible,
    _generator_quick_eligible, _async_gen_quick_eligible, _await_call_ctype,
    _is_async_call_to_known_fn, _local_literal_ctype, _receiver_key,
    _is_known_struct_ptr_ctype, _infer_simple_expr_ctype, _c_to_cpp_scalar_type,
    _yield_from_delegate_ctype, _is_itertools_repeat2_call, _walk_own_body,
    _generator_tuple_yield_slot_ctypes, _generator_yield_ctype, _struct_name_of,
    _struct_type_id, _is_concrete_type_arg, _bracket_param_type_annotations,
    _used_idents_deep,
)


_SELFHOST_DIR = os.path.dirname(os.path.abspath(__file__))

# Function/method C symbols that the self-host forward-decl block
# (gen_module's `_is_selfhost_file` gate) declares explicitly with concrete
# signatures. The lazy auto-stub path (`_lower_named_call`'s `_is_unknown`
# fallback) must NOT also emit a conflicting variadic `(...)` declaration for
# these — two declarations of one symbol in one translation unit is a hard
# GCC "conflicting types" error (confirmed via `make check-selfhost` /
# `make check-runner`: the concrete decl comes from this block, the variadic
# stub from the auto-stub path, and they collide). Keeping this list in sync
# with the `_is_selfhost_file` block below is required for `make check`.
_SELFHOST_HARDCODED_FUNCS = frozenset({
    'Parser_parse_module',
    'Parser___init__',
    'Interpreter___init__',
    'Interpreter_execute',
    'jit_compile_and_execute',
})


# Sentinel stored in GimpleGen._own_imported_func_home when a bare free-
# function name genuinely cannot be resolved to one home module within a
# single compile unit — e.g. one file with two different nested scopes each
# locally importing a same-named function from two DIFFERENT sibling
# modules (see _note_own_func_home / _func_qualifier). Distinguishes "not
# registered at all" (falls through to the next, less-specific tier) from
# "registered, but genuinely ambiguous" (must raise rather than silently
# pick one — see doc/STDLIB-BUGS.md SB-1's per-scope-import residual).
# A string, not object() — a real module-qualifier name is always a valid
# Mojo identifier (module_name_for_path output), and this string can never
# collide with one; object() itself is NOT self-host-safe (make
# check-selfhost's own compile of this file's `_AMBIGUOUS_FUNC_HOME =
# object()` tried to lower it as a call to an undefined C symbol `_object`,
# per this project's "self-host every codegen-affecting change" gate).
_AMBIGUOUS_FUNC_HOME = '\x00__SB1_AMBIGUOUS_FUNC_HOME__\x00'

# Matches a literal `sys.path.insert(<int>, "<string>")` / `(..., '...')` call
# in Mojo source text. This compiler never executes anything, so a runtime
# `sys.path.insert` (the pattern myinterpreter.py's actual interpretation of
# it honors — see BUG-2026-014) can only be honored by statically recognizing
# this exact literal-argument shape and treating it as an extra module search
# directory, same priority as the real interpreter gives it (checked first).
_SYS_PATH_INSERT_RE = re.compile(
    r'sys\s*\.\s*path\s*\.\s*insert\s*\(\s*\d+\s*,\s*["\']([^"\']+)["\']\s*\)')

# The other common real-world shape: `sys.path.insert(0,
# os.path.join(os.path.dirname(__file__), "<relative>"))` — "insert my own
# directory (or a path relative to it)", computed rather than a literal
# string. `__file__` at compile time is exactly the currently-compiled
# file's own path, so `os.path.dirname(__file__)` is resolvable statically
# too — see _record_sys_path_inserts, which treats a bare "." result (empty
# capture) as `base_dir` itself. Found via mojolib BUG-2026-032:
# transpiler.mojo's `import os; sys.path.insert(0,
# os.path.join(os.path.dirname(__file__), ".."))` inside a function body,
# to reach its sibling parser_core.mojo/lexer.mojo/arena.mojo one directory
# up — invisible to the plain-literal regex above.
_SYS_PATH_INSERT_DIRNAME_RE = re.compile(
    r'sys\s*\.\s*path\s*\.\s*insert\s*\(\s*\d+\s*,\s*os\s*\.\s*path\s*\.\s*join\s*\(\s*'
    r'os\s*\.\s*path\s*\.\s*dirname\s*\(\s*__file__\s*\)\s*'
    r'(?:,\s*["\']([^"\']*)["\']\s*)?\)\s*\)')

# _slit_ numbering starts here to avoid collisions with the mojo compiler's
# own string-literal numbering when modules are linked together.
STRING_POOL_BASE = 10000

# ---------------------------------------------------------------------------
# Type system helpers
# ---------------------------------------------------------------------------

def _merge_struct_inheritance(all_struct_defs):
    """`struct Child(Base1, Base2):` — Python-style class inheritance.
    Mutates each StructDef with `.bases` in place so `.fields`/`.methods`
    become the fully-merged view (base fields/methods first, in declaration
    order — later bases override earlier ones, own members override every
    base, matching Python's left-to-right MRO for non-diamond hierarchies),
    once, up front. Every other struct_field_types/method-registration/
    self.x-scanning site in this file just reads `.fields`/`.methods`
    directly, so doing the merge here — rather than teaching each of those
    ~15 call sites about inheritance individually — means they transparently
    see the merged view for free. Mirrors myinterpreter.py's
    execute_StructDef, which does the same merge for the interpreted path."""
    by_name = {s.name: s for s in all_struct_defs if isinstance(s, StructDef)}
    resolved = set()

    def resolve(s):
        if s.name in resolved:
            return
        resolved.add(s.name)  # mark first: guards against an inheritance cycle
        if not getattr(s, 'bases', None):
            return
        merged_fields = []
        merged_methods = {}
        for base_name in s.bases:
            base = by_name.get(base_name)
            if base is None:
                continue
            resolve(base)
            merged_fields.extend(base.fields)
            for m in base.methods:
                merged_methods[m.name] = m
        own_names = {m.name for m in s.methods}
        inherited = [m for name, m in merged_methods.items() if name not in own_names]
        s.fields = merged_fields + s.fields
        s.methods = inherited + s.methods

    for s in all_struct_defs:
        if isinstance(s, StructDef):
            resolve(s)


def _compute_exc_descendants(all_struct_defs):
    """For each struct name, the set of all struct names that transitively
    inherit from it (including itself) — used so a compiled `except
    BaseError:` handler matches any raised subclass of BaseError, not just
    an exact type-tag match (see _gen_stmt_TryStmt's typed-dispatch loop).
    The interpreter gets the equivalent behavior by walking a MojoClass's
    `.bases` chain at catch time (myinterpreter.py's _matches_exc_type);
    the compiled path has no such runtime walk available (dispatch is
    static int comparisons against a fixed tag), so this precomputes the
    same answer once, at compile time, instead."""
    by_name = {s.name: s for s in all_struct_defs if isinstance(s, StructDef)}
    descendants = {name: {name} for name in by_name}
    for name, s in by_name.items():
        stack = list(getattr(s, 'bases', None) or [])
        seen = set()
        while stack:
            base_name = stack.pop()
            if base_name in seen:
                continue
            seen.add(base_name)
            if base_name in by_name:
                descendants.setdefault(base_name, {base_name}).add(name)
                stack.extend(getattr(by_name[base_name], 'bases', None) or [])
    return descendants


_BRACKET_HEAD_RE = re.compile(r'\b(?:fn|def)\s+(\w+)\s*\[([^\]]*)\]')


def _declared_vars_body(stmts) -> set:
    """Variables declared in a statement list (does not cross FunctionDef boundaries)."""
    result: set = set()
    for node in stmts:
        if isinstance(node, VarDecl):
            result.add(node.name)
        elif isinstance(node, ForStmt):
            tgt = node.target
            name = tgt if isinstance(tgt, str) else getattr(tgt, 'name', '')
            if isinstance(name, str) and name.startswith('(') and name.endswith(')'):
                # tuple target `for a, b in ...`: each unpacked name is declared
                for part in name[1:-1].split(','):
                    p = part.strip()
                    if p:
                        result.add(p)
            elif name:
                result.add(name)
            result |= _declared_vars_body(node.body)
        elif isinstance(node, IfStmt):
            result |= _declared_vars_body(node.then_body)
            for _, eb in node.elifs: result |= _declared_vars_body(eb)
            if node.else_body: result |= _declared_vars_body(node.else_body)
        elif isinstance(node, (WhileStmt, WithStmt)):
            result |= _declared_vars_body(node.body)
        elif isinstance(node, TryStmt):
            result |= _declared_vars_body(node.body)
            for h in node.handlers:
                if h.name: result.add(h.name)
                result |= _declared_vars_body(h.body)
            if node.else_body:    result |= _declared_vars_body(node.else_body)
            if node.finally_body: result |= _declared_vars_body(node.finally_body)
    return result
_HELPERS = """\
static int64_t __mojo_floordiv (int64_t a, int64_t b)
{
  int64_t q = a / b;
  return q - (a % b != 0 && (a ^ b) < 0);
}
"""

# Byte size of each scalar ctype this codegen's `{mut}`-capture-spec
# heap-boxing (see GimpleGen._seed_mut_captured_local_types) can encounter
# as a captured local's ctype -- `-fgimple` rejects `sizeof(int64_t)` as an
# inline expression, so the box's `malloc(...)` call needs a literal byte
# count instead (see _gen_stmt_VarDecl's own comment on that repro).
_SCALAR_CTYPE_SIZE: dict = {
    'int': 4, 'int64_t': 8, 'uint64_t': 8, 'double': 8, 'float': 4,
    '_Bool': 1, 'char': 1,
}

# ---------------------------------------------------------------------------
# String constants for GIMPLE-compatible emit patterns
# (defined at module level to avoid compiler optimizing them to globals)
# ---------------------------------------------------------------------------

_COMMENT_WALRUS_UNSUPPORTED = "  /* walrus: unsupported LHS */"
_COMMENT_IN_RANGE_TODO = "  /* TODO: in range(a, b, step) */"
_COMMENT_COMPLEX_CALL = "  /* TODO: complex call expression */"
_COMMENT_COMP_NO_GEN = "  /* TODO: Comprehension with no generators */"
_COMMENT_RANGE_UNEXPECTED = "  /* TODO: range() unexpected arg count */"
_COMMENT_COMPLEX_ASSIGN = "  /* TODO: complex assignment target */"
_COMMENT_COMPLEX_AUG = "  /* TODO: complex aug-assign target */"
_COMMENT_BREAK_OUTSIDE = "  /* TODO: break outside loop */"
_COMMENT_CONTINUE_OUTSIDE = "  /* TODO: continue outside loop */"
_COMMENT_COMPTIME_FOR = "  /* comptime for: iterable not constant — skipped */"
_COMMENT_RANGE_UNEXPECTED2 = "  /* TODO: range() with unexpected argument count */"
_RETURN = "  return;"

# ---------------------------------------------------------------------------
# GimpleGen
# ---------------------------------------------------------------------------

import gimple_gen_methods as gmp
import gimple_module_gen as gmg
import gimple_gen_calls as ggc
import gimple_gen_stmts as gst
import gimple_gen_loops as glo
import gimple_gen_funcs as gfn
import gimple_cpp_async as gca
import gimple_cpp_core as gcc_
import gimple_gen_exprs as gex
import gimple_gen_infra as ginf
import gimple_gen_resolve as grsl
class GimpleGen:
    # Map Python builtin names to their C/runtime equivalents when used as values
    BUILTIN_VALUE_MAP = {
        'print': 'mojo_print',
        'len': 'mojo_len',
        'range': 'mojo_range',
        'str': 'mojo_str',
        'int': 'mojo_make_int',
        'float': 'mojo_make_float',
        'bool': 'mojo_make_bool',
        'list': 'mojo_make_list',
        'dict': 'mojo_make_dict',
        'set': 'mojo_make_set',
        'tuple': 'mojo_make_tuple',
        'open': 'mojo_open_file',
        'enumerate': 'mojo_enumerate',
        'zip': 'mojo_zip',
        'map': 'mojo_map',
        'filter': 'mojo_filter',
        'isinstance': 'mojo_isinstance',
        'hasattr': 'mojo_hasattr',
        'getattr': 'mojo_getattr',
        'setattr': 'mojo_setattr',
        'delattr': 'mojo_delattr',
        'type': 'mojo_type',
        'max': 'mojo_max',
        'min': 'mojo_min',
        'sum': 'mojo_sum',
        # std.builtin.coroutine's `_coro_resume_fn`/`_coro_destroy_fn` —
        # real Mojo implements these via raw `__mlir_op.co.resume`/
        # `co.destroy` ops this codegen has no general lowering for (see
        # coroutine.mojo's own compiled output, which reduces them to inert
        # "deferred: coroutine lowering not modeled" stubs). Used ONLY as
        # bare VALUES (function-pointer arguments to `external_call[
        # "AsyncRT_DeviceContext_enqueueHostFunction(Range)", ...]` in
        # device_context.mojo — never actually invoked as ordinary Mojo
        # calls anywhere in this codebase) — substituted for this
        # codegen's OWN generic resume/destroy pair instead, which operate
        # on the SAME plain-int64_t coroutine-handle representation this
        # codegen's own `_take_handle()` lowering produces (see runtime/
        # mojo_async_runtime.h's own docstring on `mojo_coro_resume_generic`/
        # `mojo_coro_destroy_generic` for why one generic pair suffices for
        # every compiled coroutine, and _lower_method_call's `_take_handle`
        # special case).
        '_coro_resume_fn': 'mojo_coro_resume_generic',
        '_coro_destroy_fn': 'mojo_coro_destroy_generic',
        'sorted': 'mojo_sorted',
        'reversed': 'mojo_reversed',
        '__builtins__': '0',
        'eval':         'mojo_eval',
        'hex': 'mojo_hex',
        'oct': 'mojo_oct',
        'bin': 'mojo_bin',
        'divmod': 'mojo_divmod',
    }

    def __init__(self, do_imports: bool = False, emit_str_pool: bool = True, emit_struct_defs: bool = True,
                 emit_entry_points: bool = True, module_name: str = "", link_imports: bool = False,
                 no_mangle=(), relaxed_imports: bool = False):
        # Function names that must NOT be overload-mangled in this TU — e.g. a
        # generic instantiation's own symbol, which is already uniquely named by
        # its type args and is referenced by that exact name from call sites.
        self._extra_no_mangle: set = set(no_mangle)
        # Milestone B (C++20-coroutine generator codegen): name -> FunctionDef
        # for every top-level generator in THIS module that gen_module's
        # pre-pass found to match the narrow supported shape (see
        # _generator_quick_eligible / _gen_cpp_generator_unit). Populated by
        # gen_module before Phase 2a's body-gen loop runs, so that loop (and
        # the free-function forward-decl loop, and call-site/iteration
        # lowering in _lower_call/_gen_for_iter/_lower_comprehension) can all
        # key off it consistently instead of re-deriving "is this a
        # supported generator" in four different places.
        self._supported_generators: dict[str, FunctionDef] = {}
        # Name of every top-level generator/async function that FAILED to
        # translate (raised _UnsupportedGeneratorShape after exhausting all
        # retry passes) and was therefore stub-declared instead, under
        # relaxed_imports (see gen_module's "leftover generators" handling).
        # Phase 2a's ordinary body-gen loop must skip these names too, not
        # just the successful ones in _supported_generators/_supported_async/
        # _supported_async_gen — otherwise it falls through and compiles the
        # SAME FunctionDef a second time as an ordinary (non-generator-aware)
        # function, producing a real C definition that conflicts with the
        # stub's own `int64_t NAME (...);` declaration ("conflicting types
        # for 'NAME'; have 'void(void)'" — gen_func has no yield-statement
        # handling, so the bogus ordinary compile silently drops every
        # `yield` and infers void/no-params from whatever's left). Found via
        # Modules/_decimal/tests/randfloat.py's test_boundaries (augmented
        # assignment to a non-simple target — genuinely unsupported, not a
        # retry-timing issue): reproduces even compiling that file alone,
        # with no import chain involved at all.
        self._unsupported_generator_names: set[str] = set()
        # name -> {'base': <mangled C symbol prefix>, 'value_ctype': <str>}
        # for every entry in _supported_generators — the exact extern "C" API
        # names/types the .c side forward-declares and calls into.
        self._generator_api: dict[str, dict] = {}
        # Default empty; gen_module overwrites this with the module's real
        # set once it's scanned (see that assignment's own docstring) —
        # this fallback just keeps `_cpp_for_generator_delegate`'s caller
        # safe for any code path that reaches `_cpp_for_stmt` without going
        # through gen_module first.
        self._all_generator_names: set = set()
        # Side channel: _gen_cpp_generator_unit/_gen_cpp_async_generator_unit
        # stash their just-computed _generator_tuple_yield_slot_ctypes
        # result here (list[str] for a tuple-yielding generator, None for
        # every other kind) right before their own `finally` clears
        # per-compile state (declared/self_fields, needed to compute it,
        # go out of scope there) — read immediately after by their own
        # caller (gen_module's generator-registration loops) to populate
        # the new 'tuple_slot_ctypes' key in _generator_api/_generator_
        # method_api/_async_gen_api. Not a per-generator dict keyed by
        # name (like _generator_api itself) because it only ever needs to
        # survive the few lines between one unit's compile finishing and
        # its caller reading it — reset to None at the top of each unit's
        # own compile attempt so a stale prior generator's value can never
        # leak into this one's registration on any early-exception path.
        self._cpp_last_tuple_slot_ctypes: list | None = None
        # Pre-body-emission companion of the stash above: a generator
        # unit's OWN preliminary `_generator_tuple_yield_slot_ctypes`
        # result (computed from just its params' types, before body
        # emission fills `declared`), stashed so `_cpp_yield_tuple` —
        # which runs DURING body emission, strictly before the
        # post-emission computation that fills _cpp_last_tuple_slot_
        # ctypes — can box every tuple-yield site out to the UNIFIED
        # arity (padding shorter sites with zero/empty values) whenever
        # the sites disagree on element count. None for every
        # non-tuple-yielding or type-unresolvable generator; cleared in
        # each unit's `finally` alongside the other per-compile state.
        self._cpp_pending_tuple_slots: list | None = None
        # THIS instance's own Phase 1.7 conclusions for its OWN top-level
        # globals (bare name -> semantic ctype), recorded at write time
        # alongside the whole-program-shared _global_var_types entry. The
        # shared flat dict is keyed by bare name alone, so any
        # later-processed module declaring the same bare name overwrites
        # it (io.py/inspect.py/tokenize.py's `__author__`, token.py/
        # tarfile.py's `ENCODING`) — an assignment emitted after that
        # overwrite would coerce its RHS to ANOTHER module's type.
        # Consumers use `_global_dst_ctype`, which trusts this overlay for
        # scalar conclusions and falls back to the shared dicts otherwise.
        self._own_global_var_types: dict = {}
        # cpp_text fragments from _gen_cpp_generator_unit, one per supported
        # generator, concatenated into self.generated_cpp at the end of
        # gen_module once the common preamble is known.
        self._generator_cpp_units: list[str] = []
        # C temp-var name (as returned by _lower_call's `<base>_start ()`
        # construction) -> that generator's _generator_api entry — lets any
        # later consumer of the resulting 'MojoGenerator *' value (a `for`
        # loop, list()/other iteration-lowering primitive) recover which
        # extern "C" resume/value/destroy functions to call without having
        # to re-derive it from the (long gone, by then) original CallExpr.
        self._generator_var_api: dict[str, dict] = {}
        # Step I (create_task/Task/TaskGroup/RaisingTask project): mirrors
        # self._generator_var_api exactly, but for a `MojoAsync *` value
        # produced by `create_task(...)`/`create_raising_task(...)` and held
        # in a real Mojo variable across statements (`var task =
        # create_task(f()); ...; task.wait()`) -- lets `.wait()` (and any
        # later `await task`) recover which extern "C" _start/_is_done/
        # _value/_destroy/_translate_pending_exc API and value_ctype this
        # particular handle uses, without re-deriving it from the (long
        # gone, by then) original create_task(...) CallExpr.
        self._async_var_api: dict[str, dict] = {}
        # See `TaskGroup()`'s construction-interception docstring in
        # `_lower_call`: name -> {'base', 'value_ctype'} for every Mojo
        # variable holding a `TaskGroup` (represented as a plain `MojoList
        # *` of int64_t-cast `MojoAsync *` handles) -- mirrors `self.
        # _async_var_api`'s identical name-keyed side-table pattern.
        self._taskgroup_var_api: dict[str, dict] = {}
        # Concatenated .cpp text (one C++20 translation unit) for every
        # supported generator in this module, or '' if none. Set at the very
        # end of gen_module, once the API is fully known — the caller
        # (mojo.py / build_stdlib_dylib.py) reads this attribute off the
        # GimpleGen instance after calling gen_module to decide whether a
        # second (g++-compiled) object file needs linking in alongside the
        # ordinary -fgimple .o. Deliberately NOT threaded through
        # compile_to_gimple's return value — that 3-arg function's ABI is
        # pinned (the self-hosted bootstrap forward-declares it), so this
        # rides along as an attribute instead; see compile_to_gimple_with_cpp.
        self.generated_cpp: str = ''
        # Milestone C step 3 (generator METHODS on structs): the method
        # analogues of _supported_generators/_generator_api just above, keyed
        # by (struct_name, method_name) rather than by bare name — a struct
        # method's name is only unique WITHIN its own struct (two different
        # structs may each define a same-named generator method), unlike a
        # module-level free function's name, so the free-function dicts'
        # bare-string keys would be genuinely ambiguous here.
        self._supported_generator_methods: dict[tuple[str, str], FunctionDef] = {}
        self._generator_method_api: dict[tuple[str, str], dict] = {}
        # Set (and always cleared in a finally) by _gen_cpp_generator_unit
        # around ONE generator method's translation: the enclosing struct's
        # name, and that struct's own field->ctype map — read by _cpp_expr's
        # `self.<field>` case and by the self_fields threaded into
        # _infer_simple_expr_ctype/_generator_yield_ctype. None whenever the
        # generator currently being translated is an ordinary free function.
        self._cpp_gen_self_struct: str | None = None
        self._cpp_gen_self_fields: dict | None = None
        # The generator/async body's `declared` local-type map, threaded to
        # _cpp_expr (which takes no `declared` parameter) so a SubscriptExpr
        # can distinguish a char* string subscript (→ mojo_cstr_slice) from
        # a MojoList*/MojoDict* container subscript (→ raw `obj[idx]`).
        self._cpp_declared: dict | None = None
        # Transient hint for `_cpp_expr`'s LambdaExpr case: when a
        # single-parameter lambda is being lowered as a `sorted(iterable,
        # key=...)` call's `key=` argument (see the CallExpr/`sorted`
        # handling below) and the iterable's element type is statically
        # known to be a struct pointer (e.g. `self.<field>` of a
        # `list[Struct]`-typed field, via `_field_elem_types`), this carries
        # that struct-pointer ctype so the lambda's own parameter can be
        # declared with the REAL struct type instead of the generic
        # `int64_t` fallback -- letting `m.<field>` member reads inside the
        # lambda body resolve through the ordinary struct-field lowering
        # rather than refusing. Set immediately before lowering the
        # LambdaExpr argument, consumed (and cleared) by the LambdaExpr case
        # itself; None everywhere else, giving every other 1-arg lambda
        # (parameter type genuinely unknown/scalar) the safe `int64_t`
        # default. See bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
        self._cpp_pending_lambda_param_ctype: str | None = None
        # Per-coroutine (generator/async) list of declarations hoisted to that
        # unit's function scope. Filled by the AssignStmt handler in
        # `_cpp_stmt` whenever a local is first-assigned; emitted at the top
        # of the coroutine's `impl` body (just after the `{`) BEFORE any
        # `body_lines`. Hoisting to function scope lets a local first
        # assigned inside a `try:`/`for:` body be read in a sibling `else:`/
        # post-loop block (C++ coroutine frames outlive every block, and
        # Python itself scopes locals to the whole function). None outside a
        # coroutine-body compile. See `_gen_cpp_generator_unit` /
        # `_gen_cpp_async_unit` for init/clear.
        self._cpp_func_scope_decls: list[str] | None = None
        # Per-coroutine-unit element ctype of LIST locals built by
        # `xs = [...]` literal assignment + `xs.append(v)` calls in a
        # compiled generator body (gimple_cpp_core.py's AssignStmt
        # container branch + `.append` call case, which write it; the
        # for-over-list indexed loop and SubscriptExpr read sites read
        # it to pick mojo_list_get_str/_double/_int). Keyed by local
        # name; init/cleared per coroutine unit alongside
        # _cpp_func_scope_decls.
        self._cpp_list_local_elem_types: dict[str, str] = {}
        # Module-level symbols (globals + functions) referenced by compiled
        # generator/async bodies, so the .cpp preamble can declare them
        # extern (a generator body calling tokenize.py's `detect_encoding`
        # or reading os.py's `sys` needs the mangled C symbol / globals
        # struct field declared in its own TU). Keys: (module, global name)
        # for globals; bare function names for functions.
        self._cpp_module_global_refs: set[tuple[str, str]] = set()
        self._cpp_module_func_refs: set[str] = set()
        # Class-level-attribute globals (the `self._class_attrs[struct][
        # attr] -> mangled global` redirect target) read via `cls.<attr>`
        # from a compiled @classmethod generator body (`_cpp_expr`'s
        # MemberExpr `cls.<attr>` case) — the SAME "this .cpp TU is
        # compiled standalone, so it needs its own extern declaration for
        # any C symbol defined in the .c/.ci side" story as `_cpp_module_
        # global_refs` above, just for a class attribute instead of a
        # plain module global. Holds the mangled global NAME (each one is
        # already globally unique — `_classattr_{struct}__{attr}` — so a
        # flat set of names is enough, no (module, name) pairing needed).
        self._cpp_class_attr_refs: set[str] = set()
        # struct name -> set of that struct's OWN method names that are
        # generators (`FunctionDef.is_generator`). See its own population
        # site's docstring (the "Collect class-level attributes" pre-pass)
        # for why this is needed as a SEPARATE registry from `self.
        # _classmethod_names`/`self.func_return_types`.
        self._struct_generator_method_names: dict[str, set[str]] = {}
        # Struct methods called from a compiled generator/async body on
        # EITHER `self` or a non-self struct-pointer-typed local/parameter
        # (see bugs/hard/CODEGEN_generator_struct_typed_param_refused.md).
        # This codegen's structs are plain C structs (no real C++ member
        # functions) — a method call must go through the method's own
        # mangled C symbol (`obj_ptr, args...`), exactly like an ordinary
        # (non-generator) compiled method call already does on the GIMPLE
        # side, NOT `obj->method(args)`/`obj.method(args)` C++ member-call
        # syntax (which doesn't compile against a plain struct at all).
        # Keys: (struct_name, method_name). Declared extern "C" in the
        # .cpp preamble alongside _cpp_module_func_refs, using the same
        # func_return_types/func_param_types lookup _struct_method_csym's
        # mangled key already populates.
        self._cpp_struct_method_refs: set[tuple[str, str]] = set()
        # Struct names accepted as a compiled generator/async function's OWN
        # struct-typed PARAMETER (not via `self` on a generator method —
        # that case already has _supported_generator_methods for the same
        # purpose). The .cpp preamble needs this struct's layout typedef
        # visible for the parameter's own pointer type and any `param.field`
        # access, exactly like _supported_generator_methods already provides
        # for `self`. See bugs/hard/CODEGEN_generator_struct_typed_param_
        # refused.md.
        self._cpp_param_struct_names: set[str] = set()
        # Struct names actually CONSTRUCTED (`StructName(args)`) inside a
        # compiled generator/async body, first-assigned to a plain local
        # (test_doctest.py's `hook = TestHook(pathdir)` inside
        # `test_hook`'s `@contextlib.contextmanager` body — see
        # bugs/CODEGEN_generator_function_Lib_test_test_doctest_test_
        # doctest.md). Distinct from `_cpp_param_struct_names` (a struct
        # arriving as a PARAMETER, never allocated in this TU) because the
        # .cpp preamble also needs an `extern "C" {Struct} * _alloc_
        # {Struct}(void);` declaration for these — the ordinary GIMPLE
        # path's own `_alloc_{struct}` helper (see `_lower_struct_
        # constructor`/`_struct_allocs_needed`), reused rather than
        # reinvented so the .c/.ci-emitted allocator and this .cpp TU
        # agree on the exact same allocation. Still needs the struct's
        # layout typedef visible too, so gen_module's typedef-emission
        # loop treats this set the same as `_cpp_param_struct_names`.
        self._cpp_ctor_struct_names: set[str] = set()
        # Struct names a compiled generator/async unit's own PROMISE VALUE
        # TYPE resolves to (struct-pointer-yield support — see
        # _infer_simple_expr_ctype's docstring): e.g. `def gen(self): yield
        # self.map.get(k)` where `map`'s dict value type is `Flag *` needs
        # `Flag`'s layout typedef visible in THIS unit's .cpp text even
        # though `Flag` is never `self`, a parameter, or constructed inline
        # here — just the promise's `current_value`/`yield_value`/`{base}_
        # value` return type. Same typedef-visibility need as
        # `_cpp_param_struct_names`/`_cpp_ctor_struct_names`, just triggered
        # by the YIELDED value's type instead of a parameter/constructor —
        # merged into the same typedef-emission loop (gen_module) rather
        # than a separate one. See CODEGEN_generator_function_Lib_enum.md's
        # 2026-08-20 update.
        self._cpp_value_struct_names: set[str] = set()
        # Module-level function names (for variadic-unmangled calls like os.py's
        # fspath) and the set of names needing a variadic extern in the .cpp.
        self._cpp_module_fn_names: set[str] = set()
        self._cpp_module_variadic_func_refs: set[str] = set()
        # Module-level global names collected by the lightweight pre-scan
        # before the generator compile loop (Pass 1.3d-gen) — populated
        # BEFORE _global_var_types (Phase 1.7), which runs later.
        self._cpp_early_global_names: set[str] = set()
        # See _gen_cpp_async_unit's `enclosing_scope` param docstring: the
        # enclosing top-level function name for a bracket-parametrized
        # nested async def currently being compiled, so `_cpp_expr`'s
        # AwaitExpr composition case can key into self._async_closure_api
        # the same way gen_module's discovery pass does. None outside that
        # narrow context.
        self._cpp_async_enclosing_scope: str | None = None
        # See _gen_cpp_async_unit's `mut_capture_names` param docstring:
        # names of captured free variables the coroutine body currently
        # being compiled REASSIGNS (threaded through as pointer parameters,
        # dereferenced on every read/write) -- empty outside that context.
        self._cpp_mut_capture_names: frozenset = frozenset()
        # Python param name -> escaped C++ identifier, for a generator/
        # async coroutine unit currently being compiled whose parameter
        # list contains a name that's a valid Python identifier but a
        # reserved C/C++ keyword (e.g. `default`, `new`, `class` — the
        # GIMPLE (.c) path already renames these via _declare_var's own
        # `_C_KEYWORDS`/`_c_names` mechanism, but the coroutine (.cpp)
        # emitter is a wholly separate translation with no equivalent).
        # Set by _gen_cpp_generator_unit/_gen_cpp_async_unit around their
        # own param-list construction, consulted by `cpp_sig`'s emission
        # AND by _cpp_expr's IdentExpr fallback (so every reference to
        # that parameter inside the body agrees with the signature) —
        # `declared`/`param_ctypes` themselves stay keyed by the ORIGINAL
        # Python name throughout (only used for type lookups, never
        # emitted as C++ text directly), so this is the one place the
        # rename needs to be threaded through. Empty outside that
        # context, mirroring `_cpp_mut_capture_names`'s identical scoped-
        # state convention. See COMPILE_FAIL_Tools_c-analyzer_c_common_
        # tables.md.
        self._cpp_kw_param_renames: dict = {}
        # struct_name -> verbatim "typedef struct Name { ... } Name;" text,
        # captured (not re-derived) from whichever of the two existing
        # struct-typedef emission sites (struct_field_types-based, or
        # StructDef-AST-based) actually emits it into the main .c/.ci output
        # — reused byte-for-byte in the .cpp preamble for any struct a
        # compiled generator METHOD needs visibility into, so gcc and g++
        # compile an identical, ABI-compatible view of that struct's layout
        # rather than two independently-derived (and potentially divergent)
        # ones. See the two capture sites in gen_module and the
        # generated_cpp assembly that consumes this dict.
        self._struct_typedef_texts: dict[str, str] = {}
        # Step B (compiled-path async/await codegen, async_runtime.h Step A's
        # sibling): name -> FunctionDef for every top-level `async def` in
        # THIS module that gen_module's pre-pass found to match the narrow
        # supported shape for this step (no parameters, no `await`, a single
        # scalar `return <expr>` — see _async_quick_eligible/
        # _gen_cpp_async_unit). Mirrors _supported_generators/_generator_api/
        # _generator_cpp_units exactly, kept as separate dicts (not folded
        # into the generator ones) since an async function's extern "C" API
        # shape differs (_start/_is_done/_value/_destroy, no _resume, no
        # yield_value) and a name could in principle appear in only one of
        # the two categories (never both — is_generator-and-is_async is its
        # own "async generator" refusal category, see gen_module).
        self._supported_async: dict[str, FunctionDef] = {}
        self._async_api: dict[str, dict] = {}
        # (outer_ctx, inner_name) -> FunctionDef / API dict for an async
        # closure NESTED INSIDE A METHOD (device_context.mojo's `async def
        # wrapper(...) capturing -> None:` shape — see gen_module's
        # dedicated discovery pass). Kept separate from _supported_async/
        # _async_api (which are keyed by bare top-level function name only)
        # since a nested closure's name is only unique within its enclosing
        # method's own scope, not module-wide — `outer_ctx` is
        # `f"{struct_name}_{method_name}{overload_id}"`, matching
        # _all_closures'/self.current_func_name's own convention exactly, so
        # a call site compiling that same method's ordinary body can look
        # this up via `(self.current_func_name, name)`.
        self._supported_async_closures: dict[tuple, FunctionDef] = {}
        self._async_closure_api: dict[tuple, dict] = {}
        # Step I (create_task/Task/TaskGroup/RaisingTask project): async
        # functions nested INSIDE an ordinary top-level function's own body
        # (e.g. a local `@parameter async def wrapper(): ...` helper
        # private to one `def test_xxx():`) — compiled by gen_module's own
        # dedicated nested-async pass (see _compile_nested_async_functions),
        # keyed by the QUALIFIED name `f"{enclosing_name}::{nested_name}"`
        # (never by bare name — two different enclosing functions may each
        # define their own same-named nested helper, e.g. two different
        # tests each with their own local `wrapper()`, and this dict must
        # keep them distinct). This is NOT the dict any call-site lowering
        # consults directly: gen_module's main per-statement loop instead
        # temporarily copies each entry belonging to the function currently
        # being compiled into self._async_api under its BARE name (a scoped
        # push), lowers that one function's body (so create_task(wrapper())
        # resolves it exactly like a top-level async function would), then
        # pops it back out — real lexical scoping on top of self._async_api's
        # flat, bare-name-keyed shape, without changing that shape or any of
        # its existing bare-name consumers (create_task, await composition,
        # asyncio.run).
        #
        # Distinct from _async_closure_api (struct-method-nested closures,
        # above): that mechanism handles a nested `async def` whose PARENT is
        # a struct method's body; this one handles a nested `async def`
        # whose PARENT is an ordinary top-level function's body. The two
        # discovery passes scan disjoint parent-container shapes and never
        # register the same FunctionDef twice.
        self._nested_async_api: dict[str, dict] = {}
        # Per-struct-field element type tracking: struct_name -> field_name -> elem_type.
        # Populated in _gen_stmt_AssignStmt during __init__, consulted by
        # _lower_MemberExpr at field read sites.  NOT reset per function in
        # _reset_func because a struct compiled in __init__ must be visible
        # to code in _toplevel or any other function.
        self._field_elem_types: dict[str, dict[str, str]] = {}
        self._field_dict_val_types: dict[str, dict[str, str]] = {}
        # Function names whose `func_param_types` entry was set by this
        # file's own "self-host hardcoded struct tables" block (below, e.g.
        # `Scope___init__`) and must NOT be silently overwritten by the
        # later, general per-struct-method signature-inference pass ("Pass
        # 1.3c: Populate func_param_types for all user functions"), which
        # runs unconditionally for every struct method and would otherwise
        # clobber a deliberately-hardcoded entry with its own weaker
        # inferred guess (e.g. `Scope.__init__`'s unannotated `parent`
        # param has no type signal from its own trivial `self.parent =
        # parent` body, so Pass 1.3c always re-infers int64_t, silently
        # reintroducing the exact "pointer boxed as int64_t losing type
        # info" bug the hardcode exists to prevent — undetected for years
        # because a `__GIMPLE`-tagged caller's raw pre-lowered GIMPLE body
        # bypasses gcc's normal call-argument type checking; only surfaced
        # once a real, unrelated fix made some caller of `Scope(...)`
        # legitimately non-`__GIMPLE`. See bugs/hard/CODEGEN_dynamic_
        # attribute_on_generic_object.md's "Segfault root-caused" section).
        # Whole-program, not reset per function.
        self._selfhost_locked_param_types: set = set()
        # Attribute names written as a `char *` (string) value onto an
        # except-as-bound exception object (`err.filename = some_str`) —
        # whole-program, like _field_dict_val_types above, NOT reset per
        # function, since the write and a later read can be in different
        # functions/modules. `mojo_setattr`'s storage always boxes as a
        # generic int64_t (see bugs/hard/CODEGEN_dynamic_attribute_on_
        # generic_object.md's Step 0 notes on why there's no per-value type
        # tag), so a read-back through `_mojo_dispatch_getattr` alone can't
        # recover the real C type — this mirrors `_known_field_type`'s own
        # whole-program field-name→type convention, scoped to this narrow
        # except-as case, letting `err.filename` used as a plain expression
        # (e.g. `print(err.filename)`) cast the boxed result back to `char *`
        # instead of printing raw pointer bits as a number. Confirmed
        # real-world need: Lib/pathlib/_os.py's `err.filename`/`err.filename2`
        # are always strings.
        self._except_attr_str_fields: set[str] = set()
        # Fixed-size-array struct fields (`var x: [ElemType; N]`, mojo_compiler.py's
        # `_parse_type_ann_inner` LBRACKET-annotation shape): struct_name ->
        # field_name -> (elem_ctype, N). The field's C type in struct_field_types
        # is the marker string f"{elem_ctype}[{N}]" (distinguishable from every
        # other ctype shape this codegen produces — never ends in ' *', never a
        # bare _TYPE_MAP/struct name) so struct-typedef emission (gen_module's
        # "Struct typedefs" sections) can special-case it into a REAL embedded C
        # array field (`ElemType name[N];`) instead of the usual `ctype name;`,
        # and _lower_subscript/_array_field_elem_ptr can special-case
        # `obj.field[i]` on such a field into real C array indexing
        # (`&obj->field[i]` via array-decay + `_mojo_at_` helper) instead of
        # falling through to the MojoList*/generic-pointer paths, neither of
        # which understands this shape. See bugs/BUG-2026-008.md (box.3d/game).
        self._array_field_sizes: dict[str, dict[str, tuple[str, int]]] = {}
        # Module-level GLOBAL container element/value types: global_name ->
        # elem/value C type. Populated once by gen_module's Phase 1.7
        # pre-scan (_phase17_infer_global_type), consulted by _reset_func
        # to re-seed the per-function _elem_types/_dict_val_types tables at
        # the start of EVERY function (see _reset_func's own comment) --
        # NOT reset per function itself, for the same reason
        # _field_elem_types isn't: a global's element type means the same
        # thing in every function that reads it, unlike a recycled temp
        # name. See bugs/hard/CODEGEN_reset_func_wipes_global_container_
        # type_inference.md.
        self._global_elem_types: dict[str, str] = {}
        self._global_dict_val_types: dict[str, str] = {}
        self._struct_field_owners: dict[str, list[tuple[str, str]]] = {}
        self._return_elem_types: dict[str, str] = {}
        # dict.items()/values() result temp -> the dict's VALUE type. The
        # runtime stores item pairs as [char* key, boxed value] (append_str +
        # append_int — see mojo_dict_items), so the for-loop tuple branch needs
        # the value slot's real type to pick get_str vs get_int; the key slot
        # is always a string. Side-table pattern, like _generator_var_api.
        self._dict_items_val_elems: dict[str, str] = {}
        # `for item in <d.items()>:` — a SINGLE loop var bound to a whole
        # dict-item PAIR (as opposed to the `for k, v in ...` tuple-target
        # shape, which _gen_for_list unpacks slot-by-slot). Maps the loop
        # VARIABLE name -> that dict's value type, so `_lower_MemberExpr`
        # can answer `item.key` / `item.value` by reading pair slot 0 / 1
        # with the right accessor. Without it, `.key`/`.value` fell through
        # to the generic dynamic-getattr path, which has no notion of a pair
        # and resolved them to 0/identity — so `-item.value` negated the
        # pair handle or a char* key ("wrong type argument to unary minus" /
        # a build2 ICE). Scoped to the loop body: saved/restored around it,
        # exactly like _regex_match_vars and _dataclass_fields_vars.
        self._dict_item_pair_vars: dict[str, str] = {}
        # Pass 2c (container-return-elem pre-pass) scratch state: per-function
        # local container-element map + the struct whose methods are being
        # scanned (so `self.foo` resolves to the right {struct}_{method} key).
        self._prepass_local_elems: dict[str, str] = {}
        self._prepass_struct: str | None = None
        # Per-slot element types of a HETEROGENEOUS tuple literal temp (recorded
        # when _lower_tuple_literal stores elements by their own type, e.g.
        # `(name, func)` → [char*, void*]). Propagated to lists of such tuples
        # so a `for name, func in funcs:` tuple-target loop reads each slot with
        # the right accessor (get_str vs get_int) instead of the joined elem
        # type ('char *') reading a boxed function pointer as a string.
        self._tuple_slot_types: dict[str, list] = {}
        # Loop VARIABLES holding a dict-item PAIR (`for item in d.items():`
        # / the runtime-dispatch list branch) — `.key`/`.value` on such a var
        # reads pair element 0/1, not an identity/field lookup.
        self._dict_items_pairs: set = set()        # Final step of the async/await codegen project: combined async
        # generators (`async def f(): ... yield ... ...` — is_async AND
        # is_generator both true). A THIRD, distinct promise type
        # (_gen_cpp_async_generator_unit) is used rather than reusing either
        # existing one — see that method's own docstring for the GCC-15
        # frame-corruption risk this project has hit before (Milestone D)
        # and the hand-written repro that confirmed this combination (no
        # parameters -- this step's whole scope, matching every other
        # step's own "narrowest shape first" precedent) is safe. Mirrors
        # _supported_async/_async_api exactly.
        self._supported_async_gen: dict[str, FunctionDef] = {}
        self._async_gen_api: dict[str, dict] = {}
        # Set (and always cleared in a finally) by _gen_cpp_async_unit for
        # the duration of ONE async function's body translation — lets the
        # SHARED _cpp_stmt/_cpp_expr whitelist emitter (reused from the
        # generator path almost verbatim) tell "translating a generator
        # body" apart from "translating an async body" for the handful of
        # places the two truly differ (a bare `return <value>` ends the
        # coroutine with a value in async mode via `co_return <expr>;`,
        # instead of being refused as it is for a generator; `yield`/`yield
        # from` are refused in async mode instead of being the whole point).
        self._cpp_emit_kind: str = 'generator'
        self.do_imports = do_imports
        self.emit_str_pool = emit_str_pool      # only main module emits string pool; imported modules skip it
        self.emit_struct_defs = emit_struct_defs  # only main module emits struct typedefs; imported modules skip it
        self.emit_entry_points = emit_entry_points  # False for imported modules; suppress main/_gimple_main
        self.module_name = module_name  # used to name _{module_name}_toplevel
        self.relaxed_imports = relaxed_imports  # when True, skip unsupported generator/async fns instead of failing
        self.func_return_types: dict[str, str] = {}
        self.struct_field_types: dict[str, dict[str, str]] = {}
        # Lazily-created container attributes used across gen_module/body
        # generation (each was previously created via `if not hasattr(...)` /
        # `getattr(self, '_X', ...)` at first USE — a pattern the self-hosted
        # compiler can't type, so the struct field was inferred as `int` and
        # held a garbage/truncated pointer until the first lazy init ran;
        # compiling hello.mojo natively read those garbage pointers and
        # crashed / skipped whole preamble sections. Initializing every one
        # here with a literal container gives _collect_self_assigns the real
        # C type AND guarantees the field is valid from construction.
        self._comptime_vals: dict = {}
        # `comptime NAME = [T(...), T(...), ...]` — the raw ListExpr AST,
        # recorded regardless of whether _eval_const can fold it (it can't:
        # a Tuple(...) constructor call isn't a foldable scalar). Lets
        # `for a, b in materialize[NAME]():` (real, in stdlib's own
        # test_atof.mojo) be lowered by UNROLLING over the literal elements
        # at compile time instead of needing a real runtime value for NAME —
        # see _gen_for_iter's materialize[...] special case.
        self._comptime_list_asts: dict = {}
        self._cb_statics: dict = {}
        self._cpp_reraise_stack: list = []
        self._class_attrs: dict = {}
        self._func_attrs: dict = {}
        self._emitted_funcattr_decls: set = set()
        self._class_attr_inits: list = []
        # Set when a `type(x).__name__` call was actually lowered (see
        # _lower_MemberExpr) — gates emitting the `_mojo_type_name` tag→name
        # table in the preamble. Only the self-hosted compiler's own bodies
        # (gen_stmt/_EXPR_DISPATCH/interpreter dispatch) use it; an ordinary
        # program's generated C never calls it, and emitting the ~46-entry
        # table unconditionally bloated every client object past
        # test_module_cache's "<8KB" size gate.
        self._needs_type_name_table: bool = False
        # Logical struct/class name -> C-safe name, for structs named after a C
        # keyword (`auto` from enum.auto being the important one — inlined into
        # every module that imports enum). The struct is renamed to the safe
        # name at gen_module's top pre-pass so it registers/emits uniformly
        # under that name (no emit-vs-bookkeeping split); name→struct LOOKUP
        # sites map through this dict. Shared across the nested GimpleGen
        # instances that recursive import-inlining creates (like
        # struct_field_types), so a struct defined in one module and used in
        # another agree on the renamed name. Only ever contains names that
        # were ACTUALLY defined as a struct, so builtins like int()/float()
        # (also C keywords) are never affected.
        self._c_kw_struct_renames: dict[str, str] = {}
        # struct name -> field names whose Python annotation is `object`/`Any`
        # (or a Union naming a real class) — these collapse to ctype int64_t
        # like a plain int field, but at runtime hold None(0)/int/boxed-pointer
        # interchangeably, so generic repr() must disambiguate via
        # _mojo_generic_elem_repr instead of printing the raw int64_t. See
        # gen_module's field-type-inference scan and the per-struct
        # _mojo_repr_<sn> codegen.
        self.struct_boxed_fields: dict[str, set[str]] = {}
        # struct name -> field names whose Python annotation is `bool` — these
        # collapse to ctype 'int' (not '_Bool', see _TYPE_MAP), so generic
        # repr() must still render them as "True"/"False" like real Python
        # bools instead of falling into the plain-int branch and printing 0/1.
        self.struct_bool_fields: dict[str, set[str]] = {}
        # struct name -> field names declared `object = None` (or bare
        # `object`, no default_factory) in the real dataclass but hardcoded
        # here to a concrete 'MojoList *'/'MojoDict *' ctype anyway (e.g.
        # IfStmt.else_body, ImportStmt.extra, SubscriptExpr.attrs) — unlike a
        # `: list = field(default_factory=list)` field (ALWAYS a real,
        # possibly-empty list, never a genuine Python None), these can
        # legitimately BE None. A NULL pointer is how that None is
        # represented at the C level, but the generic 'MojoList *' repr
        # branch (mirroring _mojo_repr_list's NULL-safe "[]"/"()"  for the
        # boxed/ambiguous-type dispatch path, where NULL always means "empty
        # container") can't tell that apart from a real empty list — so
        # `else_body=None` (no else clause) was dumping as `else_body=[]`,
        # a real, verify-visible divergence from Python's own dataclass
        # repr(). Fields registered here get a NULL check printing "None"
        # instead. See gen_module's per-struct hardcoded registration.
        self.struct_nullable_container_fields: dict[str, set[str]] = {}
        # struct name -> id() of the first StructDef AST node whose fields were
        # merged into struct_field_types[name] — see gen_module's struct-field
        # scan. Must be shared across every temp_gen sub-compile the same way
        # struct_field_types itself is (do_imports's per-module recursion),
        # not just local to one gen_module call: two unrelated same-named
        # classes reached via *different* modules (mojo_compiler.py's
        # FunctionDef vs ast_nodes.py's own FunctionDef, both present once
        # myinterpreter.py — which imports ast_nodes purely for method-
        # signature type annotations — is compiled) are scanned by two
        # different temp_gen instances, each of which would otherwise start
        # from a fresh, empty "have I seen this name" view and merge its own
        # fields in regardless of what an earlier temp_gen already decided.
        self._struct_name_owner: dict[str, int] = {}
        # struct name -> [base class names]; populated per gen_module call
        # (see the struct-bases scan below). Default empty here so any method
        # lookup that runs before that scan (or on a GimpleGen instance that
        # never reaches it, e.g. a temp_gen used only for signature probing)
        # sees "no bases" instead of raising AttributeError.
        self._struct_bases: dict[str, list] = {}
        # struct name → {alias_name: value AST}; expanded at member access.
        self._struct_comptime_aliases: dict[str, dict] = {}
        # Bare names of user free functions whose C symbol is overload-mangled by
        # parameter types (so same-named functions in different modules don't
        # collide at link). Populated for local defs and imported Mojo functions;
        # every emission site routes the name through _func_csym for consistency.
        self._mangled_funcs: set[str] = set()
        self.imported_symbols: dict[str, tuple] = {}  # symbol_name -> (module, orig_name, type)
        # Names imported (under their alias, if any) from a module
        # load_module() couldn't resolve (e.g. real Python's `os`/`sys`, or
        # any external/relative package outside this compiler's own tracked
        # Mojo stdlib/test set) -- tracked ONLY so the aliased-`main` guards
        # below know "this name really was imported from somewhere, even if
        # unresolved" and skip redirecting its call to the synthesized entry
        # point. Deliberately kept separate from `imported_symbols` itself
        # (see gen_module's FromImportStmt except-handler for why).
        self._unresolved_import_aliases: set[str] = set()
        # Persists across every gen_module() call for this instance (once per
        # file during whole-program/transitive-closure flattening) so an
        # unresolved-import stub/definition for a given C symbol name is only
        # ever emitted once, even when multiple modules independently import
        # the same never-defined name (e.g. `from module_loader import
        # STDLIB_PATH` in imports.py/version.py/regex_compile.py) - each
        # re-encounters it as "unresolved" in its own imported_symbols pass,
        # and without this guard each emits its own definition into the SAME
        # flattened translation unit, a hard "redefinition of X" GCC error
        # (the #ifndef {safe} wrapper around these does NOT guard against
        # this: it only suppresses a collision with an actual #define'd C
        # macro like SEEK_END, since a function/variable *definition* never
        # #defines anything for a later #ifndef to see). This is intentionally
        # a MODULE-LEVEL set (see its definition near _overload_hash_registry
        # above), not an instance attribute: recursive import-inlining
        # constructs nested GimpleGen instances (e.g. `temp_gen = GimpleGen(...)`
        # elsewhere in this file) for imported modules, so a plain instance
        # attribute here would reset per nested instance and never actually
        # dedup across the files that make up one flattened program.
        self._all_closures: dict = {}   # populated by gen_module pre-pass
        self._lambda_outer_closures: dict = {}  # set during lambda body codegen
        self._self_ctor_stubs: set = set()  # struct names needing `Name___new` stubs (see _lower_self_ctor)
        self._renamed_builtin_calls: dict = {}  # renamed C-reserved builtin -> ret type (see _lower_call)
        self._ptr_helpers_needed: set[str] = set()   # elem C types needing _mojo_at_ helpers
        self._emitted_ptr_helpers: set[str] = set()  # elem C types already emitted (shared)
        self.func_param_types: dict[str, list[str]] = {}  # func_name → [param_ctype, ...]
        self._global_inline_defs: set[str] = set()   # all func names with inline definitions (shared)
        self._struct_allocs_needed: set[str] = set() # struct names needing _alloc_ helpers
        self._emitted_allocs: set[str] = set()       # struct names for which _alloc_ was already emitted
        self._compiled_modules: set[str] = set()     # modules already compiled to avoid duplicates
        # Absolute file paths currently being compiled anywhere in this whole-
        # program flattening (root file plus every transitively-imported
        # module), keyed by PATH rather than module NAME — a real self-
        # shadowing import (e.g. `Lib/importlib/abc.py` doing a bare `import
        # abc`, which real Python resolves to the DIFFERENT top-level
        # `Lib/abc.py`) resolves under a name (`abc`) that is NOT yet claimed
        # in `_compiled_modules` at the time it's looked up (only actually-
        # imported module names get registered there, and the ROOT file being
        # compiled never registers under its own basename), so name-based
        # dedup alone doesn't catch it. `_compile_imported_module`'s own
        # search-path order (importer_dir before any more-specific/absolute
        # resolution — itself deliberate, see BUG-2026-014's comment on that
        # function) then matches the FILE ITSELF as the first existing
        # candidate for a same-basename bare import, so without this guard
        # the whole module gets parsed and gen_module'd a second time under a
        # second module_name, and every one of its top-level structs/
        # functions is emitted twice into the one flattened translation unit
        # — a hard "redefinition of X" GCC error for every single symbol in
        # the file (see bugs/hard/
        # CODEGEN_multiple_inheritance_duplicate_method_symbols.md, whose
        # original multiple-inheritance/struct-merge hypothesis this
        # superseded: the real, confirmed cause is this self-shadowing
        # import, not the inheritance-merge machinery — `python3 mojo.py
        # build Lib/importlib/abc.py` produced a genuinely WHOLE-FILE
        # duplicate `#line 1 ".../abc.py"` section, not merely inflated
        # per-class method lists). Shared by direct object reference across
        # every nested temp_gen the same way `_compiled_modules` is (see
        # `_compile_imported_module`'s sharing block) so a deeper indirect
        # cycle (A imports B, B imports A) is caught too, not just a literal
        # direct self-import. The root file's own path is seeded into this
        # set by every root entry point (`compile_to_gimple`,
        # `compile_to_gimple_with_cpp`, `compile_linked`) right where each
        # already sets `gen._current_filename`.
        self._compiling_file_paths: set[str] = set()
        # Non-empty iff SOME call site anywhere in the whole-program closure
        # (root module or any transitively-imported one, all sharing this
        # same set by reference exactly like `_emitted_ptr_helpers`/
        # `_funcptr_builtins_needed` below already do) actually lowered an
        # `obj.__dict__`/`vars(obj)` expression (see `_lower_MemberExpr`'s
        # `__dict__` case and `_lower_call`'s `vars` case — Step 0 of
        # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md). Gates
        # whether `_mojo_dispatch_asdict`/the per-struct `_mojo_asdict_<sn>`
        # helpers get emitted at all: unlike `_mojo_dispatch_getattr`/
        # `_mojo_dispatch_setattr`/`_mojo_dispatch_fields`/`_mojo_dispatch_
        # is_dataclass` (unconditionally emitted into every compile, however
        # trivial, since ANY module in a whole-program closure might call
        # plain `getattr()`/`setattr()`/`dataclasses.fields()` on some other
        # module's struct with no local trace of that call), `__dict__`/
        # `vars()` are rare enough in practice, and this dispatcher new
        # enough, that emitting it into a client whose own compile never
        # once uses it just to keep it "unconditional like its siblings"
        # regressed test_module_cache.py's real tiny-client-object byte
        # budget (a link-mode client whose whole architectural point is
        # staying tiny because bodies live in the shared dylib) — confirmed
        # by removing this gate and watching that exact test fail. Real
        # per-compile-unit gating, not a blanket "always emit", is the
        # correct fix for a helper this genuinely optional.
        self._asdict_dispatch_needed: set = set()
        self._module_stmts: dict[str, list] = {}    # module_name → parsed stmts (shared across all gens)
        # Flattened, incrementally-maintained mirror of the UNION of every
        # list ever stored into `self._module_stmts` (see bugs/hard/
        # PERF_nested_module_compile_walk_ast_quadratic_rescan.md, Phase 1)
        # — shared by reference into every nested temp_gen exactly like
        # `_module_stmts` itself (see `_compile_imported_module`'s sharing
        # block). Appended to ONCE per statement, ever, right where
        # `_module_stmts[module_name] = stmts` is set — so `gen_module`'s
        # own Phase-0 reconciliation loop (which needs "every transitively
        # compiled module's stmts not already in THIS level's local
        # `imported_stmts`") can do a single incremental pass over this
        # pre-flattened list instead of re-flattening the whole (by then
        # much larger) `_module_stmts` dict from scratch at EVERY one of
        # the N nesting levels in a transitive-import tree — that repeated
        # O(current total tree size) re-flattening, happening once per
        # level, is what the doc profiles as an O(N^2) `_walk_ast` blowup
        # (4.47M calls for a 36-module graph in Lib/contextlib.py).
        self._all_transitive_stmts_ordered: list = []
        self._all_transitive_stmts_ids: set = set()
        # Phase 2 (same doc as above): per-top-level-statement memoization
        # of the two `_walk_ast` sub-scans inside `_scan_body_for_local_
        # field_access` (gen_module's 4th struct-field completeness pass).
        # Keyed by id(stmt); shared by reference into every temp_gen the
        # same way `_all_transitive_stmts_ordered` is, so a given top-level
        # statement's own subtree is only ever walked once, tree-wide, no
        # matter how many levels' (ever-growing) `imported_stmts` include
        # it. See `_scan_stmt_var_candidates`/`_scan_stmt_member_candidates`
        # for why the CACHED values are unfiltered syntactic candidates,
        # not final filtered results.
        self._field_scan_var_cache: dict = {}
        self._field_scan_member_cache: dict = {}
        # Phase 3 (same doc, same pattern): per-function/method memoization
        # of `_infer_param_types`'s own expensive per-parameter AST scan
        # (`analyze_param_usage`, gen_module's Pass 1.3 unannotated-parameter
        # type inference). `all_functions`/`all_structs_for_methods` grow to
        # O(total transitive tree size) at every nesting level exactly like
        # `imported_stmts` does, so a function/method object already visited
        # by an earlier (ancestor or sibling) level was having its ENTIRE
        # body re-walked from scratch again at every subsequent level —
        # O(N^2) tree-wide, same shape as the Phase 2 bug. Keyed by
        # id(func); shared by reference into every temp_gen the same way
        # `_field_scan_var_cache` is. See `_infer_param_types` for why only
        # the raw per-parameter USAGE SIGNALS are cached here, not the
        # final inferred C type (which additionally depends on
        # `self.struct_field_types`, grown monotonically during
        # compilation — the same time-dependent-filter trap as Phase 2).
        self._param_usage_scan_cache: dict = {}
        # Phase 4 (same doc, same pattern): per-top-level-statement
        # memoization of `_calls_in_stmts`' pure CallExpr-collection walk
        # (gen_module's ctor-literal scan plus its Pass 1.3d/2c caller-body
        # scans — the latter re-collects every caller body 4 more times
        # inside its own fixpoint loop). Keyed by id(stmt); shared by
        # reference into every temp_gen like the caches above. Safe to
        # cache whole because the traversal reads no mutable gen state and
        # every consumer only READS the collected nodes; see
        # gimple_gen_resolve._calls_in_stmts.
        self._calls_in_stmts_cache: dict = {}
        self._emitted_structs: set[str] = set()      # struct names already emitted (dedup across modules)
        self._str_pool: dict[str, str] = {}          # escaped string → _slit_N (shared across imports)
        # Compile-time-known regex support (see regex_compile.py, BACKLOG-CODEGEN.md §4f):
        self._regex_patterns: dict[str, str] = {}    # `X = re.compile("...")` var name → pattern source
        self._regex_progs: dict[str, dict] = {}      # pattern source → regex_compile.compile_pattern(...) result
        self._regex_progs_defined: set = set()       # pattern source → already emitted its C decl (avoid duplicate `static const ARRAY[] = {...}` across submodules)
        self._find_generic_visited: set = set()      # (module, name, kind) already visited by _find_generic_source (breaks import cycles)
        self._scalar_annotated_locals: set = set()   # per-function allow-list for _emit_call's BUG-2026-016 auto-address coercion (reseeded by gen_func)
        self._struct_home_cache: dict = {}           # (module, name) -> defining-module ref | None, memo for _find_struct_home_module (breaks re-export cycles)
        self._regex_match_vars: dict[str, dict] = {} # for-loop var name → live match context (set/cleared per loop)
        self._dataclass_fields_vars: set = set()     # for-loop vars bound from dataclasses.fields(x) — f.name is f itself (set/cleared per loop)
        self._const_str_locals: dict[tuple, str] = {}  # (func_name, var_name) → compile-time-folded string constant
        self._struct_has_init: set[str] = set()      # structs that have __init__ methods
        self._struct_method_names: dict[str, set[str]] = {}  # struct name -> {real method names}, see its own population site's docstring
        self._static_methods: set[str] = set()       # mangled names of @staticmethod methods
        self._classmethod_names: set[str] = set()     # mangled `Struct_method` names of REAL classmethods
        # (explicit @classmethod, plus the two dunders Python treats as
        # implicit classmethods without requiring the decorator:
        # __init_subclass__/__class_getitem__) — see _lower_method_call's
        # `ov == 'cls'` heuristic, which consults this to avoid misattributing
        # an ordinary parameter/local that merely happens to be NAMED `cls`
        # (e.g. the descriptor-protocol `__get__(self, instance, cls=None)`
        # third parameter, whose real type is whatever class object touched
        # the descriptor at the call site, not the struct __get__ happens to
        # be defined on) to the struct enclosing the CURRENT method.
        self._struct_init_params: dict[str, list[str]] = {}  # struct -> __init__ param names (excl self)
        self._struct_init_defaults: dict[str, dict] = {}  # struct -> __init__ param name -> default expr AST node (excl self)
        self._func_param_defaults: dict[str, list] = {}  # mangled free-fn name -> [(param_name, default_ast), ...]
        # free-fn name (both mangled and plain) -> index of its `**kwargs`
        # parameter in the C signature. A `**kwargs` param is declared a real
        # `MojoDict *` (see gen_func's param loop), so a call site passing
        # LITERAL keyword arguments has to PACK them into a dict. Without this
        # the padding loop in _lower_named_call just popped the first keyword
        # argument's lowered VALUE into that slot and cast it — emitting
        # `_t32 = (MojoDict *)_t31;` for `h(1, x=7, y=8)`, i.e. the integer 7
        # reinterpreted as a dict pointer, which segfaults on first use.
        self._func_kwargs_slot: dict[str, int] = {}
        # free-fn name (both mangled and plain) -> whether a real `*args`
        # parameter precedes its `**kwargs` (as opposed to `**kwargs` being
        # the function's ONLY vararg-style parameter, e.g. `def f(**kwargs)`
        # with no `*args` at all). `_signature_ctypes` (the DEF side) only
        # ever emits a `MojoList *` C param for `*args` when `**kwargs` is
        # ALSO present ("the forwarding pattern f(self, *args, **kwargs)") —
        # a kwargs-ONLY function gets exactly ONE C param (`MojoDict *`), not
        # two. The call-site packing keyed off `_func_kwargs_slot` (see
        # `_lower_named_call`) used to assume the forwarding pattern
        # unconditionally, always building BOTH a `MojoList *` (for a
        # nonexistent `*args`) and a `MojoDict *` and passing both — for a
        # kwargs-only callee that's 2 arguments against a 1-parameter C
        # declaration ("too many arguments to function"). Found via
        # Lib/importlib/metadata/__init__.py's `def distributions(**kwargs):`
        # called as plain `distributions()`.
        self._func_kwargs_has_vararg: dict[str, bool] = {}
        # A free function's own sentinel-preserving param C-type list, for
        # the `(fixed, *args, trailing_kwonly=default, ...)` shape (no
        # `**kwargs`) — populated ONCE at registration time so a call site
        # compiled LATER still sees the packing sentinel, mirroring why
        # `_mangled_signature_ctypes` exists for struct methods (see that
        # dict's own docstring: `func_param_types[name]`'s sentinel gets
        # overwritten with the concrete real signature once the function's
        # forward declaration is finalized, so any call site compiled
        # afterwards sees a signature with no `'...'` at all). Unlike
        # `_mangled_signature_ctypes`, which is only ever populated for
        # struct methods, this covers plain free functions — see
        # `_lower_call`'s own trailing-keyword-only-param packing fix and
        # bugs/COMPILE_FAIL_importlib__bootstrap.md's `_verbose_message`
        # instance.
        self._vararg_trailing_param_types: dict[str, list] = {}
        # (struct_name, method_name) -> list of candidate overloads, each a dict:
        #   {'overload_id', 'param_names', 'param_ctypes' (excl self), 'min_arity', 'max_arity'}.
        # Populated from the CURRENT file's own AST only (same-file resolution);
        # a struct imported from elsewhere without local source has no entry here.
        self._struct_method_signatures: dict[tuple, list] = {}
        # mangled C symbol -> full param C-type list (incl. self), for a
        # not-yet-emitted overload's forward-referenced call to be coerced
        # correctly by _emit_call. Deliberately kept separate from the shared
        # func_param_types dict: writing this same info into func_param_types
        # early (before the overload's own definition is emitted) was tried
        # and reverted — confirmed it changes codegen elsewhere in ways not
        # limited to _emit_call's coercion (broke std/python/python.mojo's
        # Python.dict(Span[Tuple[K,V]]) overload's own Span-subscript
        # lowering, for reasons not fully isolated). This dict is read ONLY
        # by _emit_call as a fallback, so it can't have that kind of reach.
        self._mangled_signature_ctypes: dict[str, list] = {}
        self._actual_types: dict[str, str] = {}      # var_name -> actual type (for int64_t-stored pointers)
        self._python_api_needed: bool = False         # set when any mojo_python_* function is referenced
        self._sub_toplevels: list[str] = []  # ordered list of sub-module toplevel fn names (shared)
        self._has_toplevel_code: bool = False  # set per-module; whether root has top-level statements
        self._module_globals: dict[str, list[tuple[str, str, str]]] = {}  # module_name -> [(name, c_type, mojo_type), ...] (shared)
        self._module_global_inits: dict[str, dict[str, str]] = {}  # module_name -> {name -> init_code} (shared)
        self._global_to_module: dict[str, str] = {}  # global_name -> module_name (shared)
        self._current_module_ctx: str = ""  # current module name for global field access
        self._global_var_types: dict[str, str] = {}  # module-level global name -> C type (persists across functions)
        self._global_c_decl_types: dict[str, str] = {}  # global name -> actual C declaration type (int64_t or pointer)
        # Phase C: Dispatch solver for static dispatch table planning
        self._dispatch_solver: DispatchSolver | None = None  # Instantiated in gen_module Phase 1.5
        self._dispatch_tables: dict = {}  # dispatch_table_name → DispatchTable (from _dispatch_solver)
        self._emitted_dispatch_typedefs: set[str] = set()  # Track typedef names already emitted
        self._emitted_dispatch_tables: set[str] = set()    # Track table names already emitted
        self._funcptr_builtins_needed: set[str] = set()    # builtin C names needing static void* vars
        # Tracks which of the above have already had their `static void *
        # _funcptr_X = (void *)X;` declaration emitted SOMEWHERE in the final
        # .ci — shared with every _compile_imported_module temp_gen (see
        # there) the same way _emitted_ptr_helpers/_emitted_structs/etc.
        # already are. Without this, each imported module compiles through
        # its OWN throwaway GimpleGen instance with its own unshared
        # _funcptr_builtins_needed set; if two different modules' source each
        # independently use the same builtin name as a bare value (e.g. both
        # reference plain `dict`/`list`/`set`, not called), each module's own
        # emitted code carries its own top-level `static void *
        # _funcptr_mojo_make_dict = ...` declaration, and since all modules'
        # generated code is textually concatenated into one translation unit
        # for the self-hosted build, gcc rejects the duplicate top-level
        # static as a redefinition. See
        # bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md's quality-gate
        # notes: fixing set()/list() to actually walk their iterable argument
        # (reusing the comprehension iteration machinery) let previously
        # mid-lowering-abandoned functions in myinterpreter.py/
        # build_stdlib_dylib.py compile all the way through for the first
        # time, which is what newly exposed this latent cross-module
        # collision (only regex_compile.py used to reach a bare `dict`
        # reference at all).
        self._emitted_funcptr_builtins: set[str] = set()
        self._auto_stubbed: set[str] = set()               # function names auto-stubbed in _emit_call
        self._current_filename: str = ""  # filename for #line directives
        self._emitted_line_pairs: set[tuple[str, int]] = set()  # (filename, line) pairs already emitted
        # external_call["name", Ret](args) targets → (ret_ctype, [arg_ctypes]); first use wins.
        # Shared across imported modules so the root preamble can emit one extern proto each.
        self._external_protos: dict[str, tuple[str, list[str]]] = {}
        # Track method overloads: {struct_name.method_name} → [(param_count, param_types), ...]
        # Used to assign unique IDs to each overload in C code generation
        self._method_signatures: dict[str, list[tuple[int, tuple]]] = {}
        # Link mode (MODULE_CACHE_DESIGN.md stage 1): emit `extern` decls for
        # imported symbols instead of inlining their bodies; the bodies come from a
        # separately-built artifact (object / stdlib dylib). Off by default so the
        # existing inline `do_imports` path and all suites are unaffected.
        self.link_imports: bool = link_imports
        self._link_import_decl_list: list = []
        # Dylibs the program must link, recorded by `import` as it resolves each
        # module to its dylib (the loader binds the symbols at load). Deduped.
        self._link_dylibs: list = []
        # Object files the program must link, recorded by elaboration as it
        # instantiates generics on demand (ELABORATION.md). Deduped.
        self._link_objects: list = []
        # True once ANY object added to `_link_objects` was compiled from
        # C++ (a generic instantiation whose body needed a real coroutine
        # translation unit — monomorphize.instantiate's `cpp_object`, e.g.
        # test_tracing.mojo's `test_tracing[level, enabled]()` containing a
        # nested `async def`) OR this module's own top-level `generated_
        # cpp` is non-empty. The final link driver must be C++-aware
        # (g++, not gcc) whenever this is True — see driver.py's own
        # `compile_program`/`_build`, which reads this via `compile_
        # linked`'s return tuple.
        self._link_needs_cxx: bool = False
        # Shared (by-reference, single-element-list) mirror of `_link_needs_
        # cxx` -- see `_compile_imported_module`'s sharing block, which
        # threads THIS SAME list object down through every nested temp_gen
        # a do_imports=True recursion spins up (parser.py -> parsing.py ->
        # lexer.py, etc.). `_link_needs_cxx` itself is a plain per-instance
        # bool: setting it on a deeply-nested temp_gen (e.g. the one
        # actually compiling lexer.py, several `_compile_imported_module`
        # levels below the link_imports=True ROOT `compile_linked` reads
        # from) never reached the root's own attribute, so a coroutine unit
        # discovered only that deep silently never flipped the root's
        # `needs_cxx` -- confirmed by the SAME repro this list was added to
        # fix (bugs/COMPILE_FAIL_Tools_cases_generator_parser.md's lexer.py/
        # tokenize()): the root's own top-level `import lexer as lx` never
        # appears in parser.py itself, only transitively (parsing.py's own
        # `import lexer as lx`, itself reached through parser.py's `from
        # parsing import (...)`), so by the time lexer.py's own generator is
        # discovered, `self` several frames down is a `do_imports=True`-only
        # (not `link_imports=True`) temp_gen -- exactly the case a plain
        # per-instance bool can't bridge. A single-element list is the
        # standard Python idiom for a primitive value multiple objects need
        # to share and mutate in place (a bare bool re-assignment always
        # rebinds the local attribute instead of mutating shared state).
        # `compile_linked` ORs this into its own `needs_cxx` alongside the
        # plain `_link_needs_cxx` attribute (kept for the existing call
        # sites, unchanged) rather than replacing it, so a shallow (root-
        # level) `_link_needs_cxx = True` write keeps working exactly as
        # before even though it doesn't ALSO reach through this list.
        self._link_needs_cxx_box: list = [False]
        # Modules imported (for a plain, non-generic struct) in link mode that
        # couldn't be resolved via imports.py's MOJO_PATH-based dylib resolver
        # or module_loader's std/test-only loader — e.g. an ordinary sibling
        # .mojo file in a project that isn't itself laid out under
        # MOJO_PATH/PYTHONPATH/the stdlib root (mojolib's cpp_parser/, which
        # has no dylib-building infrastructure of its own; BUG-2026-032).
        # _register_link_imports records the module name here; gen_module
        # then runs the same _compile_imported_module pass a do_imports=True
        # build already uses (real body generation, not just field-type
        # registration), since there's no dylib to link its methods from.
        self._link_inline_modules: set = set()
        # Imported names that are generic templates (not concrete exports):
        # name -> the module source path, used to instantiate at call sites.
        self._imported_generics: dict = {}
        # (struct_name, method_name) -> {overload_id: ordered list of
        # comptime bracket parameter names that are BOTH function-typed (per
        # _bracket_param_type_annotations) AND actually referenced somewhere
        # in the method's own body (directly or via a nested closure — per
        # _used_idents_deep)}. These are threaded through as ordinary
        # trailing C parameters (opaque function pointers) instead of being
        # silently dropped at the call site — see bugs/CODEGEN_device_
        # context_captured_function_parameter_closures_broken.md's Repro 1
        # and _gen_struct_method/_lower_call's "obj.method[...]" branch.
        # Keyed by (struct_name, method_name) THEN by overload_id (matching
        # _struct_method_overload_ids' own convention) — required because
        # (a) two DIFFERENT structs can define a same-named method where only
        # one needs threading (e.g. std/builtin/variadics.mojo's
        # `VariadicList.consume_elements` — an ORDINARY `elt_handler`
        # parameter, no brackets at all — vs. the unrelated
        # `VariadicPack.consume_elements[elt_handler: def[idx: Int](...)]` —
        # a struct-name-blind key wrongly threaded VariadicPack's decision
        # onto VariadicList's method too, duplicating its already-ordinary
        # `elt_handler` parameter) and (b) two sibling overloads of the same
        # method name ON THE SAME STRUCT can also have completely different
        # bracket-parameter shapes (e.g. std/memory/span.mojo's
        # `binary_search_by[func: def(Self.T) -> Int](self)` vs. the sibling
        # `binary_search_by[FuncType: def(Self.T) -> Int](self, func:
        # FuncType)`).
        self._method_threaded_comptime_params: dict = {}
        # (struct_name, method_name) -> {overload_id: the method's FULL
        # comptime_params list, in bracket declaration order} (parallel to
        # _method_threaded_comptime_params, which is a FILTERED subset) —
        # lets the call site map each bracket argument expression back to its
        # parameter by position, once an overload is identified.
        self._method_comptime_param_order: dict = {}
        # Imported function name -> module source path, for comptime evaluation
        # (run the function at compile time via comptime.evaluate; slice 3).
        self._imported_fn_sources: dict = {}
        # Bare-imported module-scope `var` global name -> (c_return_type,
        # accessor_c_symbol). Populated by `_emit_imported_global_accessors`
        # (see its own docstring — BUG-2026-009) from module_loader's
        # 'kind': 'global_var' export entries. Consulted by `_lower_
        # IdentExpr` to route a bare read of the imported name through a
        # real cross-translation-unit call into the DEFINING module's own
        # accessor function, instead of the "unknown identifier" zero/NULL
        # placeholder a per-module-independent `mojo dylib` compile
        # previously fell through to for this shape.
        self._imported_global_accessors: dict = {}
        # Concrete imported structs used as parameter types here: their StructDefs
        # (so the layout typedef is emitted in dylib mode) and their names (so only
        # these — not local structs — get the authoritative struct-pointer param
        # typing, keeping the blast radius tight).
        self._imported_typedef_structs: list = []
        self._imported_struct_names: set = set()
        # Imported struct local name -> its home module's C-symbol qualifier
        # (e.g. 'std_utils__ansi'), so a call site on that struct computes the
        # SAME module-qualified method symbol its home module actually
        # exports (see _struct_method_qualifier / _struct_method_csym).
        # Populated by _register_imported_structs (source-visible imports,
        # via module_loader.module_name_for_path on the resolved file) and by
        # _register_reflected_struct (dylib-reflection-only imports, by
        # extracting the qualifier already baked into the dylib's advertised
        # symbol string — there's no local source file to derive it from).
        self._imported_struct_home: dict = {}
        # Imported free-function bare name -> its home module's C-symbol
        # qualifier — the free-function analog of _imported_struct_home
        # above, added to fix SB-1 (doc/STDLIB-BUGS.md): two modules' same-
        # named free-function overloads that box down to the same C parameter
        # shape (e.g. math.abs(SIMD) and complex.abs(Complex), both boxing to
        # a lone int64_t) hashed to the identical overload_suffix_for(...)
        # suffix and collided at link. Prefixing every genuinely LOCAL
        # definition with its owning module's name (see _func_qualifier)
        # makes the two collide-prone symbols distinct without touching
        # overload_suffix_for's hashing at all — but an IMPORTING module's
        # call site must independently derive the exact same qualifier the
        # defining module used, which is what this dict records (mirroring
        # _imported_struct_home's own comment above almost verbatim).
        # Populated ONLY by gen_module's do_imports inline-compile loop, keyed
        # by an inlined module's OWN top-level FunctionDef names -> ITS OWN
        # module_name — see that loop's own comment. SHARED (by object
        # identity) across every nested temp_gen a do_imports=True build
        # spins up (_compile_imported_module below), which makes it at best a
        # cross-module FALLBACK, never authoritative for a specific call
        # site: _func_qualifier consults _own_imported_func_home (below)
        # FIRST, precisely because this dict cannot disambiguate "two sibling
        # modules define the same bare function name" — whichever inlined
        # module is processed first claims the bare-name key via setdefault
        # and every other module's OWN local definition of that same bare
        # name would otherwise silently inherit the first one's qualifier.
        self._imported_func_home: dict = {}
        # Imported free-function bare name -> its home module's qualifier,
        # populated ONLY from the CURRENT gen_module call's own top-level
        # FromImportStmt scan (_emit_stdlib_import_externs /
        # _register_link_imports, both of which operate on `stmts` — this
        # instance's own compile unit — never a nested/sibling module's).
        # Deliberately NOT shared across nested temp_gens (contrast
        # _imported_func_home above): a real bug (found via `mojo.py build`
        # on two sibling modules that each define a same-named free function
        # and are each wrapped by their OWN importer module — e.g.
        # alpha_wrapper.mojo doing `from alpha_module import f` and
        # beta_wrapper.mojo doing `from beta_module import f`, both
        # transitively pulled into one program) showed that when
        # _imported_func_home is consulted first, beta_wrapper's own,
        # correctly-resolved registration of `f -> beta_module` is a
        # setdefault no-op (alpha_module already claimed the bare key `f` in
        # the SHARED dict via the do_imports Phase-0 loop, which runs before
        # any wrapper module's own imports are even scanned) — so
        # beta_wrapper's call site silently called alpha_module's `f`
        # instead of beta_module's: a real, silent miscompile, not a build
        # failure. Every module that actually REFERENCES an imported name
        # necessarily has that name's own FromImportStmt somewhere in ITS
        # OWN top-level stmts (Mojo/Python scoping requires it), so this
        # per-instance dict is always authoritative for any name looked up
        # while compiling THIS module's own body — no sharing needed, and
        # sharing is exactly what caused the bug.
        self._own_imported_func_home: dict = {}
        # Per-lexical-scope import tracking: a stack of {bare_name ->
        # module_qualifier} dicts, innermost scope LAST. Frame 0 is this
        # gen_module call's own module scope, populated (in statement order,
        # so a later top-level `from X import name` shadows an earlier
        # same-name import — Python/Mojo semantics) from this module's own
        # top-level FromImportStmts. Every function/method body pushes its own
        # frame, populated from that body's own local imports, so a
        # function-body import shadows a module-level one and two sibling
        # functions' local imports of same-named functions from two different
        # modules never conflict. `_func_qualifier` consults this stack
        # innermost-first to resolve a bare-name reference whose flat
        # `_own_imported_func_home` entry is `_AMBIGUOUS_FUNC_HOME` — the
        # SB-1 residual in doc/STDLIB-BUGS.md (two NESTED scopes each
        # importing a same-named free function from two sibling modules) and
        # std/memory/__init__.mojo's two top-level imports of `alloc`
        # (std.memory.alloc + std.memory.unsafe_pointer) — using whichever
        # module the LEXICALLY-CLOSEST enclosing import statement bound the
        # name to, the same shadowing the interpreter gives (myinterpreter.py
        # Scope.define). NOT shared across nested temp_gens (each module
        # compile has its own scope stack), exactly like
        # _own_imported_func_home.
        self._import_scope_stack: list = []
        # (sanitized_home_qualifier, as_referenced_name) -> [ctype, ...]:
        # the parameter ctypes a name's HOME MODULE says it has, snapshotted
        # at FromImportStmt registration time (gimple_module_gen's
        # _register_sym path, right beside the matching
        # _note_own_func_home call). BUG-2026-024: the SHARED
        # func_param_types[bare] slot this used to be read from is
        # overwritten once per sibling module whose inline compile
        # registers a same-named function of its own
        # (mod.computer.computer_case.get_energy(c: ComputerCase) vs
        # mod.computer.network.get_energy(n: ComputerNetwork), one import
        # aliased, one not), so an importer's call sites hashed whichever
        # sibling registered LAST and emitted call symbols whose overload
        # suffix matched no definition ("implicit declaration of function
        # ..._77b31a; did you mean ..._0ed997?"). Keying by home module
        # makes same-named siblings land under different keys — nothing to
        # fight over. Lookup goes through gimple_gen_funcs._imported_def_pts,
        # which mirrors _func_qualifier's tier order (scope stack, then
        # _own_imported_func_home, then the shared _imported_func_home) so
        # the suffix and the qualifier halves of one mangled symbol can
        # never disagree about which entry they mean.
        self._imported_home_param_types: dict = {}
        # module name -> (path, source_text, parsed stmts), parsed once.
        self._imported_src_cache: dict = {}
        # Directories added via a literal `sys.path.insert(N, "literal")` seen
        # anywhere in the transitive closure's source text — statically
        # scanned (this compiler never executes anything), not interpreted.
        # Checked with highest priority in _compile_imported_module: the user
        # wrote this to say "look here first", same as myinterpreter.py
        # actually mutating real sys.path at run time (see BUG-2026-014).
        self._extra_search_paths: list = []
        # Imported generic struct name -> module source path (slice 5).
        self._imported_generic_structs: dict = {}
        # Imported overloaded function name -> module source path (slice 4).
        self._imported_overloads: dict = {}
        # typedefs for elaborated (monomorphized) structs, emitted in the preamble.
        self._elaborated_typedefs: list = []
        # extern decls for symbols elaboration produced at call sites (generic
        # instantiations); emitted in the preamble like import extern decls.
        self._elaborated_externs: list = []
        # Lambda lifting: anonymous functions generated on-the-fly from LambdaExpr.
        # These are accumulated during gen_func and flushed into func_parts by
        # gen_module after the surrounding function body is emitted.
        self._lambda_counter: int = 0
        self._lambda_parts: list[str] = []   # lifted C function bodies, in emission order
        # Exception class name -> stable small int tag, shared for the whole
        # compile so a `raise Foo(...)` site and an `except Foo:` handler
        # anywhere else in the program agree on the same id. 0 is reserved
        # for "untyped" (a bare `raise` re-raising the live exception, or an
        # exception object with no statically-known class name).
        self._exc_type_ids: dict[str, int] = {}
        self._exc_descendants: dict = {}
        self._reset_func()

    # Builtin exception names (mirrors myinterpreter.py's _setup_builtins plus
    # the other common Python builtins) — used to tell `raise SomeClass` (tag
    # it) apart from `raise e` re-raising a bound variable (leave the type tag
    # from when `e` was first raised alone; retagging with a fresh id for the
    # variable name `e` would be wrong).
    _KNOWN_EXCEPTION_NAMES = frozenset({
        'Exception', 'BaseException', 'KeyboardInterrupt', 'EOFError',
        'ValueError', 'TypeError', 'RuntimeError', 'StopIteration',
        'KeyError', 'IndexError', 'NameError', 'AttributeError',
        'FileNotFoundError', 'NotImplementedError', 'ZeroDivisionError',
        'OverflowError', 'ImportError', 'ModuleNotFoundError',
        'StopAsyncIteration', 'GeneratorExit', 'SystemExit',
        'ArithmeticError', 'LookupError', 'OSError', 'IOError',
        'UnicodeDecodeError', 'UnicodeEncodeError', 'AssertionError',
        # A standard Python builtin exception, missing from this table:
        # `raise SyntaxError` (test_deque.py's own `fail()` generator)
        # was NOT recognized as an exception class at all — the ordinary
        # path emitted "ct param or undeclared: SyntaxError" and the
        # coroutine path emitted the raw name as a C++ expression
        # ("'SyntaxError' was not declared in this scope").
        'SyntaxError',
    })

    # Known runtime function signatures: fname -> (ret_type, [arg_types])
    # Used by _emit_call to ensure GIMPLE-valid argument types.
    _KNOWN_SIGS: dict = {
        'mojo_bound_method_new':    ('MojoBoundMethod *', ['void *', 'void *']),
        'mojo_bound_method_call_0': ('int64_t', ['MojoBoundMethod *']),
        'mojo_bound_method_call_1': ('int64_t', ['MojoBoundMethod *', 'int64_t']),
        'mojo_bound_method_call_2': ('int64_t', ['MojoBoundMethod *', 'int64_t', 'int64_t']),
        'mojo_bound_method_call_3': ('int64_t', ['MojoBoundMethod *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_bound_method_call_4': ('int64_t', ['MojoBoundMethod *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'conforms_to':           ('_Bool',      ['int64_t', 'int64_t']),
        'llabs':                 ('int64_t',   ['int64_t']),
        'labs':                  ('int64_t',   ['int64_t']),
        'mojo_str_split':        ('MojoList *', ['char *', 'char *']),
        'mojo_str_rjust':        ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_ljust':        ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_center':       ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_splitlines':   ('MojoList *', ['char *']),
        'mojo_str_count':        ('int64_t',    ['char *', 'char *']),
        'mojo_str_rsplit':       ('MojoList *', ['char *', 'char *', 'int64_t']),
        'mojo_str_partition':    ('MojoList *', ['char *', 'char *']),
        'mojo_str_rpartition':   ('MojoList *', ['char *', 'char *']),
        'mojo_c_getenv':         ('char *',     ['char *']),
        'mojo_char_to_str':      ('char *',     ['char']),
        'mojo_ord':              ('int64_t',    ['char *']),
        'mojo_chr':              ('char *',     ['int64_t']),
        'mojo_read_type_tag':    ('int64_t',    ['int64_t']),
        'mojo_read_type_tag_safe': ('int64_t',  ['int64_t']),
        '_mojo_dispatch_getattr':    ('int64_t',   ['void *', 'char *']),
        '_mojo_dispatch_setattr':    ('void',      ['void *', 'char *', 'int64_t']),
        '_mojo_dispatch_fields':     ('MojoList *', ['void *']),
        '_mojo_dispatch_asdict':     ('MojoDict *', ['void *']),
        '_mojo_dispatch_is_dataclass': ('int',     ['void *']),
        '_mojo_dispatch_repr':       ('char *',    ['void *']),
        '_mojo_repr_list':           ('char *',    ['MojoList *']),
        'mojo_repr_list_doubles':    ('char *',    ['MojoList *']),
        'mojo_repr_list_ints':       ('char *',    ['MojoList *']),
        '_mojo_repr_dict':           ('char *',    ['MojoDict *']),
        # Python binding layer (mojo_python.h)
        'mojo_python_init':      ('void',       []),
        'mojo_python_fini':      ('void',       []),
        'mojo_python_import':    ('void *',     ['char *']),
        'mojo_python_getattr':   ('void *',     ['void *', 'char *']),
        'mojo_python_call':      ('void *',     ['void *', 'void *']),
        'mojo_python_call_func': ('void *',     ['char *', 'char *', 'int64_t']),
        'mojo_python_tuple_new': ('void *',     ['int64_t']),
        'mojo_python_tuple_set': ('void',       ['void *', 'int64_t', 'void *']),
        'mojo_python_from_int':  ('void *',     ['int64_t']),
        'mojo_python_from_double': ('void *',   ['double']),
        'mojo_python_from_str':  ('void *',     ['char *']),
        'mojo_python_to_int':    ('int64_t',    ['void *']),
        'mojo_python_to_double': ('double',     ['void *']),
        'mojo_python_to_str':    ('char *',     ['void *']),
        'mojo_python_exception': ('char *',     []),
        # SQLite3 binding (mojo_sqlite3.h)
        'mojo_sqlite3_open':      ('void *',     ['char *']),
        'mojo_sqlite3_close':     ('void',       ['void *']),
        'mojo_sqlite3_errmsg':    ('char *',     ['void *']),
        'mojo_sqlite3_exec':      ('int64_t',    ['void *', 'char *']),
        'mojo_sqlite3_query':     ('void *',     ['void *', 'char *']),
        'mojo_sqlite3_query_dict':('void *',     ['void *', 'char *']),
        'mojo_sqlite3_prepare':   ('void *',     ['void *', 'char *']),
        'mojo_sqlite3_step':      ('int64_t',    ['void *']),
        'mojo_sqlite3_finalize':  ('void',       ['void *']),
        'mojo_sqlite3_bind_int':  ('void',       ['void *', 'int64_t', 'int64_t']),
        'mojo_sqlite3_bind_double': ('void',     ['void *', 'int64_t', 'double']),
        'mojo_sqlite3_bind_text': ('void',       ['void *', 'int64_t', 'char *']),
        'mojo_sqlite3_bind_null': ('void',       ['void *', 'int64_t']),
        'mojo_sqlite3_column_count': ('int64_t', ['void *']),
        'mojo_sqlite3_column_type':  ('int64_t', ['void *', 'int64_t']),
        'mojo_sqlite3_column_name':  ('char *',  ['void *', 'int64_t']),
        'mojo_sqlite3_column_int':   ('int64_t', ['void *', 'int64_t']),
        'mojo_sqlite3_column_double':('double',  ['void *', 'int64_t']),
        'mojo_sqlite3_column_text':  ('char *',  ['void *', 'int64_t']),
        'mojo_sqlite3_column_bytes': ('int64_t', ['void *', 'int64_t']),
        'mojo_sqlite3_last_insert_rowid': ('int64_t', ['void *']),
        'mojo_sqlite3_changes':   ('int64_t',    ['void *']),
        'mojo_stdin_read':       ('char *',     []),
        'mojo_platform_system':  ('char *',     []),
        'mojo_print_stderr':     ('void',       ['char *']),
        'mojo_strlen':           ('int64_t',    ['char *']),
        'mojo_utf8_codepoint_index': ('int64_t', ['char *', 'int64_t']),
        'mojo_platform_machine': ('char *',     []),
        'mojo_subprocess_run':        ('MojoCompletedProcess *', ['MojoList *', 'int64_t']),
        'mojo_subprocess_returncode': ('int64_t', ['MojoCompletedProcess *']),
        'mojo_subprocess_stdout':     ('char *',  ['MojoCompletedProcess *']),
        'mojo_subprocess_stderr':     ('char *',  ['MojoCompletedProcess *']),
        'mojo_str_find':         ('int64_t',   ['char *', 'char *']),
        'mojo_str_find_from':    ('int64_t',   ['char *', 'char *', 'int64_t']),
        'mojo_str_cat':          ('char *',    ['char *', 'char *']),
        'mojo_str':              ('char *',    ['void *']),
        # mojo_map/mojo_filter (runtime/mojo_runtime.{h,c}): `void *mojo_map(void
        # *func, void *iterable)` is a pointer-returning passthrough shim (it
        # just hands back `iterable` today — no actual per-element mapping is
        # performed at the runtime-helper level). Without this entry, the temp
        # holding the call result defaulted to int64_t (this dict's absence is
        # exactly what BUG-2026 CODEGEN_map_over_untyped_param_arg's "assignment
        # ... from void * makes integer from pointer" GCC error came from) —
        # see bugs/CODEGEN_map_over_untyped_param_arg.md.
        'mojo_map':              ('void *',    ['void *', 'void *']),
        'mojo_filter':           ('void *',    ['void *', 'void *']),
        'mojo_shlex_join':       ('char *',    ['MojoList *']),
        'mojo_str_isalnum':      ('int',       ['char *']),
        'mojo_str_isdigit':      ('int',       ['char *']),
        'mojo_str_isalpha':      ('int',       ['char *']),
        'mojo_str_isspace':      ('int',       ['char *']),
        # zlib binding (mojo_zlib.h)
        'mojo_zlib_compress':      ('void *',    ['char *', 'int64_t', 'int64_t']),
        'mojo_zlib_decompress':    ('void *',    ['char *', 'int64_t']),
        'mojo_zlib_gzip_compress': ('void *',    ['char *', 'int64_t', 'int64_t']),
        'mojo_zlib_gzip_decompress':('void *',   ['char *', 'int64_t']),
        'mojo_zlib_crc32':         ('int64_t',   ['int64_t', 'char *', 'int64_t']),
        'mojo_zlib_adler32':       ('int64_t',   ['int64_t', 'char *', 'int64_t']),
        # SSL binding (mojo_ssl.h)
        'mojo_ssl_context_new':      ('void *',   []),
        'mojo_ssl_context_free':     ('void',     ['void *']),
        'mojo_ssl_new':              ('void *',   ['void *', 'int64_t']),
        'mojo_ssl_free':             ('void',     ['void *']),
        'mojo_ssl_connect':          ('int64_t',  ['void *']),
        'mojo_ssl_accept':           ('int64_t',  ['void *']),
        'mojo_ssl_read':             ('int64_t',  ['void *', 'char *', 'int64_t']),
        'mojo_ssl_write':            ('int64_t',  ['void *', 'char *', 'int64_t']),
        'mojo_ssl_error':            ('char *',   ['void *']),
        'mojo_ssl_version':          ('char *',   []),
        'mojo_ssl_set_verify_none':  ('int64_t',  ['void *']),
        'mojo_ssl_set_verify_peer':  ('int64_t',  ['void *']),
        'mojo_ssl_set_hostname':     ('int64_t',  ['void *', 'char *']),
        # ncurses binding (mojo_ncurses.h)
        'mojo_ncurses_init':         ('void *',   []),
        'mojo_ncurses_end':          ('void',     ['void *']),
        'mojo_ncurses_refresh':      ('void',     ['void *']),
        'mojo_ncurses_move':         ('void',     ['void *', 'int64_t', 'int64_t']),
        'mojo_ncurses_addstr':       ('void',     ['void *', 'char *']),
        'mojo_ncurses_mvaddstr':     ('void',     ['void *', 'int64_t', 'int64_t', 'char *']),
        'mojo_ncurses_clear':        ('void',     ['void *']),
        'mojo_ncurses_getch':        ('int64_t',  ['void *']),
        'mojo_ncurses_attron':       ('void',     ['void *', 'int64_t']),
        'mojo_ncurses_attroff':      ('void',     ['void *', 'int64_t']),
        'mojo_ncurses_has_colors':   ('int64_t',  []),
        'mojo_ncurses_start_color':  ('int64_t',  []),
        'mojo_ncurses_init_pair':    ('int64_t',  ['int64_t', 'int64_t', 'int64_t']),
        'mojo_ncurses_color_set':    ('void',     ['void *', 'int64_t']),
        'mojo_ncurses_getmaxy':      ('int64_t',  ['void *']),
        'mojo_ncurses_getmaxx':      ('int64_t',  ['void *']),
        'mojo_ncurses_subwin':       ('void *',   ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_ncurses_delwin':       ('void',     ['void *']),
        'mojo_str_isupper':      ('int',       ['char *']),
        'mojo_str_islower':      ('int',       ['char *']),
        'mojo_bool_to_str':      ('char *',    ['int']),
        'mojo_repr_int':         ('char *',    ['int64_t']),
        'mojo_repr_str':         ('char *',    ['char *']),
        'mojo_repr_obj':         ('char *',    ['int64_t']),
        'mojo_repr_float':       ('char *',    ['double']),
        'mojo_print':            ('void',      ['char *']),
        'mojo_open_file':        ('int64_t',   ['char *']),  # Added: returns handle, takes path
        'mojo_close':            ('void',      ['void *']),
        'mojo_write':            ('int64_t',   ['void *', 'char *', 'int64_t']),
        'mojo_read':             ('int64_t',   ['void *', 'char *', 'int64_t']),
        'int64_t_basename':      ('char *',    ['char *']),  # os.path.basename(path)
        'int64_t_splitext':      ('char *',    ['char *']),  # os.path.splitext(path)
        'int64_t_expanduser':    ('char *',    ['char *']),  # os.path.expanduser(path)
        'mojo_make_int':         ('int64_t',    ['char *']),
        'mojo_make_float':       ('double',     ['char *']),
        'mojo_make_bool':        ('int',        ['int']),   # runtime: int mojo_make_bool(int)
        'mojo_list_new':         ('MojoList *', []),
        'mojo_list_append_int':  ('void',      ['MojoList *', 'int64_t']),
        'mojo_list_append_str':  ('void',      ['MojoList *', 'char *']),
        'mojo_list_append_obj':  ('void',      ['MojoList *', 'void *']),
        'mojo_list_get_int':     ('int64_t',   ['MojoList *', 'int64_t']),
        'mojo_list_get_str':     ('char *',    ['MojoList *', 'int64_t']),
        'mojo_list_len':         ('int64_t',   ['MojoList *']),
        'mojo_dict_len':         ('int64_t',   ['MojoDict *']),
        'mojo_set_len':          ('int64_t',   ['MojoSet *']),
        'mojo_truthy_cstr':      ('int',       ['char *']),
        'mojo_div_double':       ('double',    ['double', 'double']),
        'mojo_div_float':        ('float',     ['float', 'float']),
        'mojo_str_from_int':     ('char *',    ['int64_t']),
        'mojo_dict_new':         ('MojoDict *', []),
        'mojo_dict_set_str': ('void',      ['MojoDict *', 'char *', 'char *']),
        'mojo_dict_set_int': ('void',      ['MojoDict *', 'char *', 'int64_t']),
        'mojo_dict_get_str':     ('char *',    ['MojoDict *', 'char *']),
        'mojo_dict_get_int':     ('int64_t',   ['MojoDict *', 'char *']),
        'mojo_dict_contains':    ('int',       ['MojoDict *', 'char *']),
        'mojo_replace_argv':   ('void',    ['MojoList *']),
        'mojo_is_registered_list': ('int',     ['int64_t']),
        'mojo_is_registered_dict': ('int',     ['int64_t']),
        'mojo_set_new':          ('MojoSet *', []),
        'mojo_set_add_str':      ('void',      ['MojoSet *', 'char *']),
        'mojo_set_add_int':      ('void',      ['MojoSet *', 'int64_t']),
        'mojo_set_contains_str': ('int',       ['MojoSet *', 'char *']),
        'mojo_set_clear':        ('void',      ['MojoSet *']),
        'mojo_set_contains_int': ('int',       ['MojoSet *', 'int64_t']),
        'mojo_hasattr':          ('int',        ['int', 'char *']),
        'mojo_obj_getattr':      ('int64_t',   ['void *', 'char *']),
        'mojo_unsupported_iter': ('void',      ['char *']),
        'mojo_regex_search':     ('int', ['const ReNode *', 'const ReRange *', 'const ReClassInfo *',
                                           'int', 'int', 'char *', 'int64_t', 'int64_t',
                                           'int64_t *', 'int64_t *', 'int64_t *', 'int64_t *']),
        'mojo_regex_lastgroup':  ('char *', ['const char * *', 'int', 'int64_t *']),
        'mojo_regex_substr':     ('char *', ['char *', 'int64_t', 'int64_t']),
        # Matches runtime/mojo_runtime.h's own declaration exactly
        # (`int mojo_getattr(int obj, char *attr)` — the honest
        # always-return-0 stub). The old entry here claimed
        # ('int64_t', ['void *', 'char *']), so every call site coerced
        # its object argument to `void *` and passed it to a function
        # whose real first parameter is `int` — "passing argument 1 of
        # 'mojo_getattr' makes integer from pointer without a cast"
        # (Lib/test/support/__init__.py's bare-statement
        # `getattr(object_to_patch, attr_name)`).
        'mojo_getattr':          ('int',        ['int', 'char *']),
        'mojo_setattr':          ('void',      ['void *', 'char *', 'int64_t']),
        'mojo_delattr':          ('void',      ['void *', 'char *']),
        'mojo_re_sub_fn':        ('char *',    ['char *', 'void *', 'void *', 'char *']),
        'mojo_re_sub_str':       ('char *',    ['char *', 'char *', 'char *']),
        'mojo_regex_sub_fn':     ('char *',    ['const ReNode *', 'const ReRange *', 'const ReClassInfo *',
                                                 'int', 'int', 'void *', 'void *', 'char *']),
        'mojo_regex_sub_str':    ('char *',    ['const ReNode *', 'const ReRange *', 'const ReClassInfo *',
                                                 'int', 'int', 'char *', 'char *']),
        'mojo_set_union':        ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_difference':   ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_discard':      ('void',      ['MojoSet *', 'int64_t']),
        'mojo_str_startswith':   ('int',       ['char *', 'char *']),
        'mojo_str_endswith':     ('int',       ['char *', 'char *']),
        'mojo_str_startswith_char': ('int',    ['char *', 'char']),
        'mojo_str_endswith_char':   ('int',    ['char *', 'char']),
        'strcmp':                ('int',       ['char *', 'char *']),
        'mojo_cstr_cmp':         ('int',       ['char *', 'char *']),
        'snprintf':              ('int',       ['char *', 'int64_t', 'char *']),
        'strlen':                ('int64_t',   ['char *']),
        'strcat':                ('char *',    ['char *', 'char *']),
        'mojo_str_cat':          ('char *',    ['char *', 'char *']),
        'mojo_str_format':       ('char *',    ['char *']),
        'int_load_module':       ('int',       ['ModuleLoader *', 'char *']),
        'int_get_symbol_type':   ('char *',    ['ModuleLoader *', 'char *', 'char *']),
        'int_import_module':     ('int',       ['int', 'char *']),
        'int_group':             ('char *',    ['char *', 'int']),
        '_scan_for_escaping':    ('void',      ['MojoList *', 'MojoSet *', 'MojoSet *']),
        'int_analyze':           ('int',       ['int', 'int', 'MojoDict *']),
        'int_abspath':           ('int64_t',   ['int64_t', 'int64_t']),
        'int_dirname':           ('int64_t',   ['int64_t', 'int64_t']),
        'int_join':              ('int64_t',   ['int64_t', 'int64_t', 'int64_t']),
        'int_join_list':         ('int64_t',   ['int64_t', 'int64_t']),
        'int_exists':            ('int',       ['int64_t', 'int64_t']),
        'mojo_set_intersection': ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_update':       ('void',      ['MojoSet *', 'MojoSet *']),
        'mojo_dict_copy':        ('MojoDict *', ['MojoDict *']),
        'mojo_dict_from_pairs':  ('MojoDict *', ['MojoList *']),
        'mojo_dict_update':      ('void',      ['MojoDict *', 'MojoDict *']),
        'mojo_dict_free':        ('void',      ['MojoDict *']),
        'mojo_dict_clear':       ('void',      ['MojoDict *']),
        'mojo_dict_keys':        ('MojoList *', ['MojoDict *']),
        'mojo_dict_values':      ('MojoList *', ['MojoDict *']),
        'mojo_dict_items':       ('MojoList *', ['MojoDict *']),
        'mojo_sorted':           ('MojoList *', ['void *']),
        'mojo_list_sorted_str':  ('MojoList *', ['MojoList *']),
        'mojo_set_sorted':       ('MojoList *', ['MojoSet *']),
        'mojo_dict_sorted_keys': ('MojoList *', ['MojoDict *']),
        'mojo_dict_items_sorted': ('MojoList *', ['MojoDict *']),
        'mojo_reversed':         ('void *',     ['void *']),
        # POSIX / C stdlib functions with non-int64_t returns (util stubs table)
        # NOTE: bare `isdir` (as opposed to `int_isdir`, the real os.path.isdir
        # runtime helper just below) is intentionally NOT listed here — see
        # bugs/COMPILE_FAIL_Modules_getpath.md. Being "known" here forced
        # `_lower_named_call`'s `_is_unknown` check permanently False for the
        # literal name `isdir`, which skipped the safe, lazy, per-file weak-
        # stub fallback every other CPython-getpath.c-injected-and-never-
        # defined name (abspath/isfile/joinpath/...) already gets, so a file
        # that references bare `isdir` without ever locally defining or
        # importing it (getpath.py's own shape) compiled clean but then hit
        # "Undefined symbols ... _isdir" at link time — nothing anywhere in
        # this compiler's runtime supplies a body for the literal C symbol
        # `isdir`. Real Mojo code (std/os/path/path.mojo's own `def isdir`,
        # or any file importing it) is entirely unaffected by this removal:
        # `func_return_types`/`func_param_types` (populated by Pass 1/2's
        # own registration of that real definition/import) already supply
        # the correct return/param types directly, independent of this
        # table — this entry's `ret_type`/`expected_params` overrides in
        # `_lower_named_call` only ever mattered as a fallback for names
        # NOT already resolved that way, i.e. only for the broken case this
        # removal fixes.
        'int_isdir':             ('int',         ['int64_t', 'int64_t']),  # os.path.isdir(path)
        'isatty':                ('int',         ['int']),
        'getpid':                ('int',         []),
        'getppid':               ('int',         []),
        'getuid':                ('unsigned int', []),
        'getgid':                ('unsigned int', []),
        'sysconf':               ('long',        ['int']),
        # Python's hex()/oct()/bin() builtins -- real implementations in
        # runtime/mojo_runtime.c, routed here via BUILTIN_VALUE_MAP. (The
        # bare 'hex' name used to be declared as if it were a real libc
        # function via _LIBC_DECLARED/_NEEDS_SELF_EXTERN -- no such libc
        # function exists, so every caller of Python's hex() got an
        # "undefined symbol 'hex'" LINK failure, not a compile error.)
        'mojo_hex':              ('char *',      ['int64_t']),
        'mojo_oct':              ('char *',      ['int64_t']),
        'mojo_bin':              ('char *',      ['int64_t']),
        'mojo_divmod':           ('MojoList *',  ['int64_t', 'int64_t']),
        'serialize':             ('void',        []),
        'mojo_enumerate':        ('MojoList *', ['void *']),
        'mojo_zip':              ('void *',     ['void *', 'void *']),
        'mojo_list_all':         ('int',        ['MojoList *']),
        'mojo_list_any':         ('int',        ['MojoList *']),
        'mojo_list_copy':        ('MojoList *', ['MojoList *']),
        'mojo_list_extend':      ('void',       ['MojoList *', 'MojoList *']),
        'mojo_list_pop':         ('int64_t',    ['MojoList *']),
        'mojo_list_pop_at':      ('int64_t',    ['MojoList *', 'int64_t']),
        'mojo_list_clear':       ('void',       ['MojoList *']),
        'mojo_list_reverse':     ('void',       ['MojoList *']),
        'mojo_list_remove_at':   ('void',       ['MojoList *', 'int64_t']),
        'mojo_list_remove_str':  ('void',       ['MojoList *', 'char *']),
        'mojo_list_remove_int':  ('void',       ['MojoList *', 'int64_t']),
        'mojo_list_index_str':   ('int64_t',    ['MojoList *', 'char *']),
        'mojo_list_index_int':   ('int64_t',    ['MojoList *', 'int64_t']),
        'MojoList_index':        ('int64_t',    ['MojoList *', 'int']),
        # Scope methods — name is always char*, value is boxed int
        'Scope_define':          ('void',       ['Scope *', 'char *', 'int']),
        'Scope_get':             ('int',        ['Scope *', 'char *']),
        'Scope_set':             ('void',       ['Scope *', 'char *', 'int']),
        'Scope___init__':        ('void',       ['Scope *', 'Scope *']),
        'py_tokenize':              ('MojoList *', ['char *']),
        'Parser_parse_module':   ('MojoList *', ['Parser *']),
        'mojo_eval':             ('int',         ['int', 'MojoDict *', 'MojoDict *']),
        'interpret_and_execute': ('void',        ['char *', 'int']),
        # C math functions with non-int64_t return types — temps must be float/double
        'fma':          ('double', ['double', 'double', 'double']),
        'fmaf':         ('float',  ['float', 'float', 'float']),
        'nextafter':    ('double', ['double', 'double']),
        'nextafterf':   ('float',  ['float', 'float']),
        'modf':         ('double', ['double', 'double *']),
        'modff':        ('float',  ['float', 'float *']),
        'frexp':        ('double', ['double', 'int *']),
        'frexpf':       ('float',  ['float', 'int *']),
        'ldexp':        ('double', ['double', 'int']),
        'ldexpf':       ('float',  ['float', 'int']),
        'hypot':        ('double', ['double', 'double']),
        'hypotf':       ('float',  ['float', 'float']),
        'remainder':    ('double', ['double', 'double']),
        'remainderf':   ('float',  ['float', 'float']),
        'copysign':     ('double', ['double', 'double']),
        'copysignf':    ('float',  ['float', 'float']),
        'nan':          ('double', ['char *']),
        'nanf':         ('float',  ['char *']),
        'scalb':        ('double', ['double', 'double']),
        'scalbf':       ('float',  ['float', 'float']),
        'scalbn':       ('double', ['double', 'int']),
        'scalbnf':      ('float',  ['float', 'int']),
        'logb':         ('double', ['double']),
        'logbf':        ('float',  ['float']),
        'j0':           ('double', ['double']),
        'j1':           ('double', ['double']),
        'y0':           ('double', ['double']),
        'y1':           ('double', ['double']),
        # C math — float variants (f-suffix) return float, not double
        'cosf':         ('float',  ['float']),
        'sinf':         ('float',  ['float']),
        'tanf':         ('float',  ['float']),
        'acosf':        ('float',  ['float']),
        'asinf':        ('float',  ['float']),
        'atanf':        ('float',  ['float']),
        'atan2f':       ('float',  ['float', 'float']),
        'ceilf':        ('float',  ['float']),
        'floorf':       ('float',  ['float']),
        'roundf':       ('float',  ['float']),
        'truncf':       ('float',  ['float']),
        'sqrtf':        ('float',  ['float']),
        'cbrtf':        ('float',  ['float']),
        'powf':         ('float',  ['float', 'float']),
        'expf':         ('float',  ['float']),
        'exp2f':        ('float',  ['float']),
        'logf':         ('float',  ['float']),
        'log2f':        ('float',  ['float']),
        'log10f':       ('float',  ['float']),
        'fabsf':        ('float',  ['float']),
        'fmodf':        ('float',  ['float', 'float']),
        'erff':         ('float',  ['float']),
        'erfcf':        ('float',  ['float']),
        'sinhf':        ('float',  ['float']),
        'coshf':        ('float',  ['float']),
        'tanhf':        ('float',  ['float']),
        'asinhf':       ('float',  ['float']),
        'acoshf':       ('float',  ['float']),
        'atanhf':       ('float',  ['float']),
        'cbrtf':        ('float',  ['float']),
        # C math — double variants
        'cos':          ('double', ['double']),
        'sin':          ('double', ['double']),
        'tan':          ('double', ['double']),
        'ceil':         ('double', ['double']),
        'floor':        ('double', ['double']),
        'sqrt':         ('double', ['double']),
        'exp':          ('double', ['double']),
        'log':          ('double', ['double']),
        'pow':          ('double', ['double', 'double']),
        'fabs':         ('double', ['double']),
        'erf':          ('double', ['double']),
        'erfc':         ('double', ['double']),
        'exp2':         ('double', ['double']),
        'log2':         ('double', ['double']),
        'log10':        ('double', ['double']),
        'cbrt':         ('double', ['double']),
        'round':        ('double', ['double']),
        'trunc':        ('double', ['double']),
        'acos':         ('double', ['double']),
        'asin':         ('double', ['double']),
        'atan':         ('double', ['double']),
        'atan2':        ('double', ['double', 'double']),
        'sinh':         ('double', ['double']),
        'cosh':         ('double', ['double']),
        'tanh':         ('double', ['double']),
        'tanhf':        ('float',  ['float']),
        'asinh':        ('double', ['double']),
        'acosh':        ('double', ['double']),
        'atanh':        ('double', ['double']),
        'asinhf':       ('float',  ['float']),
        'acoshf':       ('float',  ['float']),
        'atanhf':       ('float',  ['float']),
        'expm1':        ('double', ['double']),
        'expm1f':       ('float',  ['float']),
        'log1p':        ('double', ['double']),
        'log1pf':       ('float',  ['float']),
        'fmod':         ('double', ['double', 'double']),
        'tgamma':       ('double', ['double']),
        'lgamma':       ('double', ['double']),
        # C string/conversion functions with non-int64_t return
        'atof':         ('double', ['char *']),
        'strtod':       ('double', ['char *', 'char **']),
        'strtof':       ('float',  ['char *', 'char **']),
        # C string functions returning char* or int
        # getenv → always renamed to mojo_getenv (force rename), so no KNOWN_SIG needed
        'realpath':     ('char *', ['char *', 'char *']),
        'strcpy':       ('char *', ['char *', 'char *']),
        'strncpy':      ('char *', ['char *', 'char *', 'int']),
        'strchr':       ('char *', ['char *', 'int']),
        'strrchr':      ('char *', ['char *', 'int']),
        'strstr':       ('char *', ['char *', 'char *']),
        'strtok':       ('char *', ['char *', 'char *']),
        'strdup':       ('char *', ['char *']),
        'strndup':      ('char *', ['char *', 'int64_t']),
        'strerror':     ('char *', ['int']),
        'tmpnam':       ('char *', ['char *']),
        # String functions returning int (not int64_t)
        'strcmp':       ('int', ['char *', 'char *']),
        'strncmp':      ('int', ['char *', 'char *', 'int64_t']),
        'memcmp':       ('int', ['void *', 'void *', 'int64_t']),
        'snprintf':     ('int', ['char *', 'int64_t', 'char *']),
        'printf':       ('int', ['char *']),
        'fprintf':      ('int', ['void *', 'char *']),
        'sprintf':      ('int', ['char *', 'char *']),
        'fputs':        ('int', ['char *', 'void *']),
        'fputc':        ('int', ['int', 'void *']),
        'putchar':      ('int', ['int']),
        'fgetc':        ('int', ['void *']),
        'getchar':      ('int', []),
        'feof':         ('int', ['void *']),
        'ferror':       ('int', ['void *']),
        'fclose':       ('int', ['void *']),
        'fflush':       ('int', ['void *']),
        'fseek':        ('int', ['void *', 'int64_t', 'int']),
        'ftell':        ('int64_t', ['void *']),
        'remove':       ('int', ['char *']),
        'rename':       ('int', ['char *', 'char *']),
        'access':       ('int', ['char *', 'int']),
        # I/O functions returning pointers
        'popen':        ('void *', ['char *', 'char *']),
        'fdopen':       ('void *', ['int', 'char *']),
        'fopen':        ('void *', ['char *', 'char *']),
        'tmpfile':      ('void *', []),
        'fgets':        ('char *', ['char *', 'int', 'void *']),
        # void-returning functions (calling with result assignment is an error)
        'int64_t_init_pointee_move': ('void', []),
        'int64_t_init_pointee_copy': ('void', []),
        'int64_t_destroy_pointee':   ('void', []),
        # Memory functions returning pointer
        'malloc':       ('void *', ['int64_t']),
        'calloc':       ('void *', ['int64_t', 'int64_t']),
        'realloc':      ('void *', ['void *', 'int64_t']),
        'memcpy':       ('void *', ['void *', 'void *', 'int64_t']),
        'memmove':      ('void *', ['void *', 'void *', 'int64_t']),
        'memchr':       ('void *', ['void *', 'int', 'int64_t']),
        # getdelim/getline take char**+size_t* — use _mojo_* wrappers that accept void*
        '_mojo_getdelim': ('int64_t', ['void *', 'void *', 'int', 'void *']),
        '_mojo_getline':  ('int64_t', ['void *', 'void *', 'void *']),
        # vprintf takes (char*, va_list) — wrap to avoid va_list in GIMPLE
        '_mojo_vprintf':  ('int', ['char *', 'void *']),
        # mojo_memcpy: UnsafePointer params lower to int64_t (byte-based _memcpy_impl)
        'mojo_memcpy':  ('void', ['int64_t', 'int64_t', 'int64_t']),
        # mojo_memmove: UnsafePointer params lower to int64_t* (element-based memmove)
        'mojo_memmove': ('void', ['int64_t *', 'int64_t *', 'int64_t']),
        # char_replace is a macro in mojo_runtime.h — suppress conflicting stub declaration
        'char_replace':  ('int64_t', ['int64_t', 'int64_t', 'int64_t']),
        # Call the real function directly rather than through the char_replace
        # macro — some self-hosted call sites triggered a GCC -fgimple parse
        # error ("expected expression before '(' token" inside the macro
        # body) that couldn't be reproduced in isolation; calling the
        # underlying function avoids the macro's cast-wrapping entirely.
        '_char_replace_impl': ('int64_t', ['int64_t', 'int64_t', 'int64_t']),
        # id() is emitted as a static helper in _MOJO_UNIMPL_STUBS — suppress variadic stub
        'id':            ('int64_t', ['int64_t']),
        # POSIX process functions — pad Mojo's 2-arg waitpid(pid, options)
        # to the real 3-arg C signature (pid, &status, options); and pad
        # execv to its 2-arg C signature so types coerce correctly.
        'waitpid':       ('int', ['int', 'int *', 'int']),
        'execv':         ('int', ['char *', 'char *']),
        'execve':        ('int', ['char *', 'char *', 'char *']),
    }

    # Rename these C stdlib functions to mojo_* wrappers at call sites.
    _CALL_RENAMES = {
        'getdelim': '_mojo_getdelim',
        'getline':  '_mojo_getline',
        'vprintf':  '_mojo_vprintf',
    }

    def _coerce(self, src: str, dst: str, val: str) -> str:
        return TypeLattice.coerce(src, dst, val)

    # ── Type-inference pre-pass helpers ──────────────────────────────────

    # ── Pass 2c: container-return-element-type inference ──────────────────
    # Populates self._return_elem_types to a fixpoint BEFORE any body is
    # emitted. The emission-time recording in _gen_stmt_ReturnStmt only fires
    # when a callee's own body is lowered, so a call site emitted earlier (the
    # common self-host order: lower_expr at the top dispatches to the _lower_*
    # helpers defined after it) never saw the callee's return element type and
    # unpacked its (ctype, cval) tuple via mojo_list_get_int — reading the
    # char* pair as decimal pointers. This scan is deliberately syntactic
    # (mirrors _infer_return_type's approach) so it can run before emission.

    # ── Expression lowering ───────────────────────────────────────────────

    # ── Expression handlers (one per AST node type) ───────────────────────

    # ── Binary operator lowering ──────────────────────────────────────────

    # ── Operator helpers ──────────────────────────────────────────────────

    # ── Method call lowering ──────────────────────────────────────────────

    _RUNTIME_PTRS = frozenset({'MojoList *', 'MojoStr *', 'MojoDict *', 'MojoSet *',
                                'MojoDictIter *', 'MojoSetIter *'})

    # ── Method call sub-dispatchers ───────────────────────────────────────

    # ── Call expression lowering ──────────────────────────────────────────

    # libc functions already prototyped by our standard includes; re-declaring them
    # (often as variadic, e.g. printf) would clash, so we never emit our own extern.
    # Symbols that are in _LIBC_DECLARED (so we normally defer to a system header)
    # but whose declaring header is NOT in our prelude (stdio/stdlib/string/math/
    # setjmp/dlfcn). For these, external_call must emit its own prototype from the
    # call's known signature, or the call is an implicit declaration. POSIX file
    # ops live in <unistd.h>/<sys/stat.h> (not included); scalb/scalbf are obsolete
    # and absent from modern <math.h>. Excludes names that also have an unrenamed
    # Mojo wrapper definition (which would collide with the extern).
    _NEEDS_SELF_EXTERN = frozenset({
        'stat', 'lstat', 'fstat', 'access', 'unlink', 'rmdir', 'mkdir',
        'symlink', 'readlink', 'link', 'chmod', 'chown', 'getcwd',
        'scalbf',
        # POSIX fd/process calls our prelude headers don't pull in → emit the
        # extern ourselves (using the _LIBC_SIGS prototype) to avoid implicit decls.
        # fcntl confirmed missing here 2026-07-15: a generic (e.g. a comptime
        # fcntl[Int]/fcntl[Int64] instantiation via monomorphize.py) compiled
        # in isolation has no <fcntl.h> in its preamble and no other call
        # site to inherit an extern from, so it hit "implicit declaration of
        # function 'fcntl'" on every cold-CAS-cache stdlib build.
        'dup', 'pipe', 'fcntl',
        # fork/waitpid/execv: headers (<unistd.h>/<sys/wait.h>) not in our prelude,
        # so _emit_stdlib_import_externs must not skip them (the new
        # _LIBC_DECLARED check would otherwise suppress them).
        'fork', 'waitpid', 'execv',
    })
    _LIBC_DECLARED = {
        'printf', 'fprintf', 'snprintf', 'sprintf', 'puts', 'putchar', 'fputs',
        'malloc', 'calloc', 'realloc', 'free', 'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
        'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat', 'abort',
        'strchr', 'strrchr', 'strstr', 'strtok', 'strerror',
        'exit', 'atoi', 'atoll', 'atof', 'atol',
        'strtol', 'strtoll', 'strtoul', 'strtoull', 'strtod', 'strtof', 'strtold',
        'setvbuf', 'setbuf', 'setbuffer', 'setlinebuf',
        'remainderf', 'remainderl',
        'posix_spawn', 'posix_spawnp',
        'index', 'rindex',
        # Math functions (from <math.h>)
        'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf',
        'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f',
        'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf',
        'sqrt', 'sqrtf', 'cbrt', 'cbrtf',
        'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f',
        'fabs', 'fabsf', 'fmod', 'fmodf',
        'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma',
        'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff',
        'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf',
        'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf',
        'nextafter', 'nextafterf', 'copysign', 'copysignf',
        'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder',
        'expm1', 'expm1f', 'log1p', 'log1pf',
        'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf',
        'j0', 'j1', 'y0', 'y1',
        # Environment and system functions
        'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath',
        # Dynamic library functions
        'dlopen', 'dlsym', 'dlclose', 'dlerror',
        # File I/O (from <stdio.h>)
        'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush',
        'fgets', 'fputs', 'feof', 'ferror', 'clearerr', 'fileno',
        'getline', 'getdelim',
        'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf',
        'fdopen', 'popen', 'pclose',
        # stdio streams (not functions, but imported as symbols — skip our extern)
        'stderr', 'stdout', 'stdin',
        # Unix file/process functions (from <unistd.h>, <sys/stat.h>)
        'remove', 'rename', 'access', 'stat', 'lstat', 'fstat', 'unlink', 'rmdir',
        'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown',
        'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork',
        'ioctl', 'fcntl', 'dup', 'dup2', 'pipe',
        # Random functions
        'rand', 'srand', 'random', 'srandom',
        # Standard library utility
        'qsort', 'bsearch', 'abs', 'labs', 'llabs',
        # Character/string classification (ctype.h)
        'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower',
        'toupper', 'tolower',
        # Math classification macros (<math.h>) — declared as macros, not functions
        'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit',
        'fpclassify', 'isunordered', 'isgreater', 'isgreaterequal',
        'isless', 'islessequal', 'islessgreater',
        # POSIX/BSD string extras
        'strdup', 'strndup', 'strtok_r',
        # Time functions
        'time', 'clock', 'difftime', 'mktime', 'strftime',
        'gmtime', 'localtime', 'asctime', 'ctime',
        # Signal
        'signal', 'raise',
        # Wide char (wchar.h)
        'wcslen', 'wcscmp', 'wcscat',
        # runtime/mojo_async_runtime.h — already declared there (included in
        # any module's preamble with a supported async function/closure —
        # see gen_module), with real function-POINTER-typed parameters
        # (resume_fn/destroy_fn); external_call["AsyncRT_DeviceContext_
        # enqueueHostFunction(Range)", ...] (device_context.mojo's own call
        # shape) must defer to that real declaration rather than auto-
        # generating a conflicting one inferred from the (scalar-looking,
        # `void *`-typed) lowered argument values — see _LIBC_SIGS's own
        # entries for these two names, which pin the real parameter types
        # for arg-count padding/coercion purposes.
        'AsyncRT_DeviceContext_enqueueHostFunction',
        'AsyncRT_DeviceContext_enqueueHostFunctionRange',
    }

    # Correct signatures for C standard library functions to prevent conflicts
    _LIBC_SIGS: dict[str, tuple[str, list[str]]] = {
        # runtime/mojo_async_runtime.h's own honest-synchronous-simplification
        # stubs (see _LIBC_DECLARED's matching entries above) — real
        # function-pointer parameter types, matching the header exactly, so
        # external_call's own arg-count padding/coercion logic (which reads
        # this table) agrees with what's already declared instead of
        # inferring a conflicting `void *`-typed prototype from the lowered
        # argument values (_coro_resume_fn/_coro_destroy_fn lower to `void
        # *`, via BUILTIN_VALUE_MAP — see _lower_IdentExpr's "C function
        # name used as a value" case).
        'AsyncRT_DeviceContext_enqueueHostFunction':
            ('char *', ['int64_t', 'void (*)(int64_t)', 'void (*)(int64_t)', 'int64_t']),
        'AsyncRT_DeviceContext_enqueueHostFunctionRange':
            ('char *', ['int64_t', 'void (*)(int64_t)', 'void (*)(int64_t)',
                        'const int64_t *', 'int64_t']),
        'memcmp': ('int', ['char *', 'char *', 'int']),
        'strlen': ('int', ['char *']),
        'strcmp': ('int', ['char *', 'char *']),
        'strncmp': ('int', ['char *', 'char *', 'int']),
        'strcpy': ('char *', ['char *', 'char *']),
        'strncpy': ('char *', ['char *', 'char *', 'int']),
        'strcat': ('char *', ['char *', 'char *']),
        'getenv': ('char *', ['char *']),
        'setenv': ('int', ['char *', 'char *', 'int']),
        'realpath': ('char *', ['char *', 'char *']),
        'cos': ('double', ['double']),
        'sin': ('double', ['double']),
        'tan': ('double', ['double']),
        'ceil': ('double', ['double']),
        'floor': ('double', ['double']),
        'sqrt': ('double', ['double']),
        'exp': ('double', ['double']),
        'log': ('double', ['double']),
        'pow': ('double', ['double', 'double']),
        'fabs': ('double', ['double']),
        'erf': ('double', ['double']),
        'erfc': ('double', ['double']),
        'rand': ('int', []),
        'remove': ('int', ['char *']),
        'dlclose': ('int', ['void *']),
        # stdio FILE*-taking calls: FILE* modeled as void* so int64_t-lowered
        # pointer args coerce cleanly (void*→FILE* is implicit in C).
        'pclose': ('int', ['void *']),
        'fclose': ('int', ['void *']),
        'fflush': ('int', ['void *']),
        'popen': ('void *', ['char *', 'char *']),
        'fdopen': ('void *', ['int', 'char *']),
        'setvbuf': ('int', ['void *', 'char *', 'int', 'int64_t']),
        # Dynamic-linker + POSIX process/fd calls: pin the C signatures so int64_t-
        # lowered handle/string/array args coerce to the pointer types the system
        # headers declare (dlfcn.h, sys/wait.h, unistd.h) instead of clashing.
        'dlopen': ('void *', ['char *', 'int']),
        'dlsym': ('void *', ['void *', 'char *']),
        'waitpid': ('int', ['int', 'int *', 'int']),
        'fork': ('int', []),
        'execv': ('int', ['char *', 'char *']),
        'dup': ('int', ['int']),
        'dup2': ('int', ['int', 'int']),
        'pipe': ('int', ['int *']),
        'fcntl': ('int', ['int', 'int', 'int64_t']),
    }

    # ── _lower_call sub-handlers ──────────────────────────────────────────

    # ── Overload resolution (struct methods and constructors) ─────────────

    # ── Struct constructor lowering (data layout solver decision) ─────────

    # ── Subscript lowering ────────────────────────────────────────────────

    # ── Slice lowering ────────────────────────────────────────────────────

    # ── Collection literal lowering ───────────────────────────────────────

    # ── Comprehension lowering ────────────────────────────────────────────

    # ── Print helper ───────────────────────────────────────────────────────

    # ── Compile-time constant evaluators (for comptime) ───────────────────

    # ── Statement generation ───────────────────────────────────────────────

    # Statement kinds whose handler recurses into gen_stmt for a nested body
    # (their own nested statements already get their own correct #line via
    # that recursive call) — excluded from the re-stamping below, which would
    # otherwise overwrite a nested statement's correct line with the outer
    # compound statement's line.
    _COMPOUND_STMT_KINDS = frozenset((
        'IfStmt', 'WhileStmt', 'ForStmt', 'TryStmt', 'WithStmt',
        'FunctionDef', 'ComptimeIfStmt', 'ComptimeForStmt', 'MatchStmt',
    ))

    # ── Statement handlers (one per AST node type) ────────────────────────

    # Python truthiness for a container checks length, not reference identity
    # (`if []:` is False even though the list object itself is a real,
    # non-null pointer) — found via a real crash: `if line_nums:` guarding
    # `line_nums[-1]` was compiled as a pointer-null check, so an allocated-
    # but-empty list was still "truthy" and the guard never actually fired.
    _CONTAINER_LEN_FN = {
        'MojoList *': 'mojo_list_len',
        'MojoDict *': 'mojo_dict_len',
        'MojoSet *':  'mojo_set_len',
    }

    # ── for-range lowering ────────────────────────────────────────────────

    # ── for-iter lowering (non-range) ─────────────────────────────────────

    # ── Function generation ───────────────────────────────────────────────

    # ── Closure lifting ───────────────────────────────────────────────────

    # ── Struct iterator protocol (for x in obj where obj has __iter__) ────

    # Entry points, the toplevel initializer, and the bootstrap/self-host ABI
    # functions keep fixed C names (they are referenced by fixed name from
    # hardcoded preamble decls and external harnesses).
    _NO_OVERLOAD_MANGLE = frozenset({
        'main', '_toplevel', '_gimple_main', '_lib_main',
        'compile_to_gimple', 'gimple_codegen_compile_to_gimple', 'py_tokenize',
        'int_write', 'int_parse_module', 'jit_compile_and_execute', 'mojo_print',
    })

    # ── Struct method generation ──────────────────────────────────────────

    # Collection-like / pointer-like type base names: these have their own
    # runtime representation (MojoDict*/MojoList*/…) or special handling, so
    # they must never be treated as an ordinary imported struct (registering
    # them as plain structs breaks that special handling). Shared between
    # _register_imported_structs' direct-import scan and
    # _resolve_sibling_param_ctype's function-parameter scan below, so the
    # two sources of "is this name a struct we should materialize" agree.
    _IMPORTED_STRUCT_SKIP_BASENAMES = frozenset({
        'Dict', 'List', 'Set', 'Array', 'Map', 'Kwargs', 'Tuple', 'Span',
        'Optional', 'Pointer', 'StringSlice', 'UnsafePointer', 'OwnedPointer',
        'ArcPointer', 'MojoList', 'MojoDict', 'MojoSet',
    })

    # Generic free functions available without an explicit import — real Mojo
    # has an implicit prelude this codegen doesn't otherwise model (mirrors the
    # existing _FORCE_RENAME_RESERVED comment: "these are prelude symbols, and
    # we don't model implicit prelude imports"). Without this, a file that uses
    # e.g. `alloc[T](...)` without `from std.memory import alloc` never
    # registers it in _imported_generics, so the call silently stubs to 0.
    _PRELUDE_GENERICS = {'alloc': 'std.memory.unsafe_pointer'}

    # ── Generator codegen (Milestone B: narrow C++20-coroutine path) ───────
    #
    # Everything below is a SEPARATE, self-contained expression/statement-to-
    # C++-text emitter for the one narrow generator shape gen_module's
    # pre-pass allows onto this path (see _generator_quick_eligible /
    # _UnsupportedGeneratorShape) — deliberately NOT routed through
    # lower_expr/gen_stmt's GIMPLE machinery (self.decls/body_lines/bb
    # labels/var_types/...), because that machinery exists to satisfy
    # -fgimple's restricted single-static-assignment-ish subset of C, which
    # doesn't apply to the plain, ordinary-control-flow C++20 this method
    # emits into its own translation unit. Reuses this file's op tables
    # (_GD_BIN_OPS) so operator spelling agrees with the GIMPLE path, but
    # writes its own tiny recursive text emitter for the rest, restricted to
    # exactly the node kinds the target shape needs — anything else raises
    # _UnsupportedGeneratorShape, which gen_module's pre-pass catches to fall
    # back to the existing honest whole-module refusal.

    _cpp_kwfwd_counter: int = 0

    _cpp_fresh_name_counter: int = 0

    # Struct types this codegen recognizes as a compiler INTRINSIC scoped
    # lock guard inside an async coroutine body (test_locks.mojo gap (2))
    # rather than genuinely compiling the real struct's `__init__`/
    # `__enter__`/`__exit__` bodies -- see `_cpp_with_stmt`'s own docstring
    # for why eliding it entirely is provably safe in THIS runtime, not a
    # shortcut. Mirrors `TaskGroup`/`create_task` already being
    # reinterpreted as compiler intrinsics rather than real compiled
    # structs, for the same "the real struct is deep external_call/Atomic-
    # backed machinery entirely outside this narrow scalar-only async
    # codegen's model" reason:
    #  - `BlockingScopedLock` (std/utils/lock.mojo): a scoped MUTUAL-
    #    EXCLUSION lock guard, safe to elide because this runtime is
    #    genuinely single-threaded/cooperative (see this method's own
    #    docstring) -- there's no other coroutine that could ever actually
    #    contend for the lock mid-body.
    #  - `Trace` (std/runtime/tracing.mojo, called bracket-parametrized —
    #    `Trace[level](s1, s2)`, test_tracing.mojo's real shape): a
    #    PROFILING/observability guard, safe to elide for a completely
    #    DIFFERENT reason -- its `__enter__`/`__exit__` write to a side
    #    channel (MODULAR_PROFILE_FILENAME), never to any value the
    #    program's own computation observes, so skipping it changes
    #    nothing about the program's actual computed results (only whether
    #    profiling events get emitted, which this codegen doesn't support
    #    at all regardless).
    _ASYNC_NOOP_LOCK_GUARD_TYPES = frozenset({'BlockingScopedLock', 'Trace'})

    # ── Module generation ─────────────────────────────────────────────────

    def gen_module(self, stmts: list) -> str:
        # Ensure _actual_types knows stmts is MojoList* so for-loop dispatch
        # works when this method is compiled by the self-hosted backend.
        return gmg.gen_module_impl(self, stmts)

    # ---- function-extraction delegates (bodies live in gimple_gen_methods.py) ----
    def _lower_bound_method_value(self, struct_name: str, method: str, self_type: str, self_val: str) -> tuple[str, str]:
        return gmp._lower_bound_method_value(self, struct_name, method, self_type, self_val)
    def _lower_bound_method_call(self, fname_raw: str, node: CallExpr, stored_ctype: str='MojoBoundMethod *') -> tuple[str, str]:
        return gmp._lower_bound_method_call(self, fname_raw, node, stored_ctype)
    def _lower_bound_method_call_value(self, bm: str, node: CallExpr, ret_type: str='int64_t') -> tuple[str, str]:
        return gmp._lower_bound_method_call_value(self, bm, node, ret_type)
    def _lower_method_call(self, node: CallExpr) -> tuple[str, str]:
        return gmp._lower_method_call(self, node)
    def _lower_dict_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_dict_method(self, ov, method, args)
    def _lower_list_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_list_method(self, ov, method, args)
    def _lower_set_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_set_method(self, ov, method, args)
    def _lower_pointer_method(self, ov: str, ot: str, method: str, args: list) -> tuple:
        return gmp._lower_pointer_method(self, ov, ot, method, args)
    def _lower_file_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_file_method(self, ov, method, args)
    def _lower_str_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_str_method(self, ov, method, args)
    def _repack_method_call_spread_args(self, mangled: str, struct_name: str, method: str, call_args: list, arg_pairs: list) -> list:
        return gmp._repack_method_call_spread_args(self, mangled, struct_name, method, call_args, arg_pairs)
    def _lower_struct_method_call(self, ov: str, ot: str, method: str, node) -> tuple:
        return gmp._lower_struct_method_call(self, ov, ot, method, node)


    # ---- delegates: calls family (bodies in gimple_gen_calls.py) ----

    def _lower_call(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_call(self, node)

    def _lower_builtin_len(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_len(self, node)

    def _isinstance_one_type(self, obj_type: str, obj_val: str, type_name: str) -> str:
        return ggc._isinstance_one_type(self, obj_type, obj_val, type_name)

    def _lower_builtin_isinstance(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_isinstance(self, node)

    def _lower_builtin_all_any(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_all_any(self, fname_raw, node)

    def _lower_builtin_dir(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_dir(self, node)

    def _lower_builtin_sorted(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_sorted(self, node)

    def _lower_builtin_zip_n(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_zip_n(self, node)

    def _lower_builtin_import(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_import(self, node)

    def _lower_ctor_from_iterable(self, kind: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_ctor_from_iterable(self, kind, node)

    def _lower_builtin_set(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_set(self, node)

    def _lower_builtin_dict(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_dict(self, node)

    def _lower_builtin_list(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_list(self, node)

    def _lower_builtin_open(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_open(self, node)

    def _lower_self_ctor(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_self_ctor(self, node)

    def _lower_imported_struct_ctor(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_imported_struct_ctor(self, fname_raw, node)

    def _lower_scalar_ctor(self, fname_raw: str, ctype: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_scalar_ctor(self, fname_raw, ctype, node)

    def _lower_opaque_ctor(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_opaque_ctor(self, fname_raw, node)

    def _lower_recursive_self_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_recursive_self_call(self, fname_raw, node)

    def _lower_outer_closure_call(self, fname_raw: str, ci, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_outer_closure_call(self, fname_raw, ci, node)

    def _lower_closure_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_closure_call(self, fname_raw, node)

    def _lower_LambdaExpr(self, node) -> tuple:
        return ggc._lower_LambdaExpr(self, node)

    def _lower_async_closure_construct(self, key: tuple, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_async_closure_construct(self, key, node)

    def _emit_asyncio_run_drive(self, base: str, vct: str, arg_pairs: list) -> tuple[str, str]:
        return ggc._emit_asyncio_run_drive(self, base, vct, arg_pairs)

    def _lower_fnptr_call(self, fname_raw: str, var_ctype: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_fnptr_call(self, fname_raw, var_ctype, node)

    def _lower_fnptr_call_value(self, fp_type: str, fp_raw: str, node: CallExpr, ret_type: str='int64_t') -> tuple[str, str]:
        return ggc._lower_fnptr_call_value(self, fp_type, fp_raw, node, ret_type)

    def _default_expr_to_pair(self, _dflt) -> tuple:
        return ggc._default_expr_to_pair(self, _dflt)

    def _pack_vararg_trailing_params(self, fname, fname_raw, arg_pairs, kwarg_dict, call_has_spread=False):
        return ggc._pack_vararg_trailing_params(self, fname, fname_raw, arg_pairs, kwarg_dict, call_has_spread)

    def _lower_named_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_named_call(self, fname_raw, node)

    def _resolve_overload(self, candidates: list, args: list, kwargs: list | None) -> dict | None:
        return ggc._resolve_overload(self, candidates, args, kwargs)

    def _lower_varargs_pack(self, pack_args: list) -> tuple:
        return ggc._lower_varargs_pack(self, pack_args)

    def _pack_kwargs_dict(self, kwarg_pairs) -> str:
        return ggc._pack_kwargs_dict(self, kwarg_pairs)

    def _build_call_args_for_candidate(self, chosen: dict, args: list, kwargs: list | None, defaults: dict | None=None) -> list:
        return ggc._build_call_args_for_candidate(self, chosen, args, kwargs, defaults)

    def _lower_struct_constructor(self, struct_name: str, args: list, kwargs: list | None=None) -> tuple[str, str]:
        return ggc._lower_struct_constructor(self, struct_name, args, kwargs)

    def _array_field_elem_ptr(self, member_expr) -> tuple[str, str] | None:
        return ggc._array_field_elem_ptr(self, member_expr)

    def _struct_data_field(self, ctype: str):
        return ggc._struct_data_field(self, ctype)

    def _emit_struct_subscript_write(self, obj_v: str, obj_t: str, idx_v: str, val: str, val_t: str) -> bool:
        return ggc._emit_struct_subscript_write(self, obj_v, obj_t, idx_v, val, val_t)

    def _lower_subscript(self, node: SubscriptExpr) -> tuple[str, str]:
        return ggc._lower_subscript(self, node)

    def _lower_slice_bounds(self, node: SliceExpr) -> tuple[str, str]:
        return ggc._lower_slice_bounds(self, node)

    def _lower_slice(self, node: SliceExpr) -> tuple[str, str]:
        return ggc._lower_slice(self, node)

    # ---- delegates: gimple_gen_funcs.py ----
    def _gen_stmt_FunctionDef(self, node):
        return gfn._gen_stmt_FunctionDef(self, node)
    def _gen_stmt_ImportStmt(self, node):
        return gfn._gen_stmt_ImportStmt(self, node)
    def _from_import_name_is_submodule(self, module: str, name: str) -> bool:
        return gfn._from_import_name_is_submodule(self, module, name)
    def _gen_stmt_FromImportStmt(self, node):
        return gfn._gen_stmt_FromImportStmt(self, node)
    def _gen_stmt_ComptimeIfStmt(self, node):
        return gfn._gen_stmt_ComptimeIfStmt(self, node)
    def _gen_stmt_ComptimeVarStmt(self, node):
        return gfn._gen_stmt_ComptimeVarStmt(self, node)
    def _gen_stmt_GlobalStmt(self, node):
        return gfn._gen_stmt_GlobalStmt(self, node)
    def _gen_stmt_ComptimeForStmt(self, node):
        return gfn._gen_stmt_ComptimeForStmt(self, node)
    def _signature_ctypes(self, params, node, self_struct=None, sentinel='...') -> list:
        return gfn._signature_ctypes(self, params, node, self_struct, sentinel)
    def _note_vararg_trailing_param_types(self, s) -> None:
        return gfn._note_vararg_trailing_param_types(self, s)
    def _fixed_param_ctypes(self, params, node, self_struct=None) -> list:
        return gfn._fixed_param_ctypes(self, params, node, self_struct)
    def _param_struct_name(self, ptype) -> str | None:
        return gfn._param_struct_name(self, ptype)
    def _param_ctype(self, pname: str, ptype, node: FunctionDef, is_self: bool=False) -> str:
        return gfn._param_ctype(self, pname, ptype, node, is_self)
    @staticmethod
    @staticmethod
    def overload_suffix_for(c_param_types) -> str:
        return gfn.overload_suffix_for(c_param_types)
    def _overload_suffix(self, bare_name: str) -> str:
        return gfn._overload_suffix(self, bare_name)
    def _note_own_func_home(self, bare_name: str, module_name: str, record_scope: bool=True) -> None:
        return gfn._note_own_func_home(self, bare_name, module_name, record_scope)
    def _push_import_scope(self) -> dict:
        return gfn._push_import_scope(self)
    def _pop_import_scope(self) -> None:
        return gfn._pop_import_scope(self)
    def _resolve_import_module_qualifier(self, mod: str) -> str:
        return gfn._resolve_import_module_qualifier(self, mod)
    def _collect_body_import_bindings(self, node_list: list, scope: dict) -> None:
        return gfn._collect_body_import_bindings(self, node_list, scope)
    def _func_qualifier(self, bare_name: str) -> str:
        return gfn._func_qualifier(self, bare_name)
    def _global_dst_ctype(self, name: str) -> str:
        """The destination C type for an assignment to a bare-name module
        global — the same lookup the four global-assignment emission sites
        in gimple_gen_stmts.py used to inline as
        `_global_c_decl_types.get(name, _global_var_types[name])`, plus one
        override: when THIS instance's own Phase 1.7 scan concluded a SCALAR
        type for this name (recorded in `_own_global_var_types` at write
        time), trust it over both shared dicts. The shared dicts are keyed
        by bare name across every module compiled together, so a
        later-scanned module declaring the same bare name (tokenize.py vs
        io.py/inspect.py's `__author__`, tarfile.py vs token.py's
        `ENCODING`) would otherwise make this module's own assignment
        coerce its RHS to the OTHER module's type (the observed "assignment
        to 'char *' from 'int64_t'" family). Two things keep prior behavior
        otherwise intact: a genuine POINTER entry in `_global_c_decl_types`
        (e.g. the `_EARLY_DISPATCH_DICTS`/`_EARLY_DISPATCH_SETS` overrides
        for this compiler's own dispatch tables) still wins unconditionally,
        and a CONTAINER-typed own conclusion still defers to
        `_global_c_decl_types`'s int64_t boxing exactly as before."""
        own = self._own_global_var_types.get(name)
        if own is not None:
            cdecl = self._global_c_decl_types.get(name)
            if cdecl is not None and cdecl.endswith(' *'):
                return cdecl
            if own in ('int64_t', 'double', '_Bool', 'char *'):
                return own
            return cdecl if cdecl is not None else own
        return self._global_c_decl_types.get(name, self._global_var_types.get(name, 'int64_t'))
    def _locally_binds_name(self, bare_name: str) -> bool:
        return gfn._locally_binds_name(self, bare_name)
    def _func_mangleable(self, name: str) -> bool:
        return gfn._func_mangleable(self, name)
    def _func_csym(self, bare_name: str) -> str:
        return gfn._func_csym(self, bare_name)
    def gen_func(self, node: FunctionDef) -> str:
        return gfn.gen_func(self, node)
    def _gen_toplevel(self, toplevel_stmts: list) -> str:
        return gfn._gen_toplevel(self, toplevel_stmts)
    def _imported_field_ctype(self, type_ann: str) -> str:
        return gfn._imported_field_ctype(self, type_ann)
    def _materialize_imported_struct(self, module: str, nm: str, local: str) -> bool:
        return gfn._materialize_imported_struct(self, module, nm, local)
    def _resolve_sibling_param_ctype(self, module: str, raw_ptype) -> str | None:
        return gfn._resolve_sibling_param_ctype(self, module, raw_ptype)
    def _register_imported_structs(self, stmts) -> None:
        return gfn._register_imported_structs(self, stmts)
    def _find_imported_struct(self, module: str, name: str):
        return gfn._find_imported_struct(self, module, name)
    def _find_struct_home_module(self, module: str, name: str, depth: int = 0) -> str | None:
        return gfn._find_struct_home_module(self, module, name, depth=depth)
    def _resolve_test_relative_module(self, module: str) -> str | None:
        return gfn._resolve_test_relative_module(self, module)
    def _parsed_import(self, module: str):
        return gfn._parsed_import(self, module)
    def _local_sibling_module_exports(self, module: str):
        return gfn._local_sibling_module_exports(self, module)
    @staticmethod
    @staticmethod
    def _abs_module(ref: str, base: str) -> str:
        return gfn._abs_module(ref, base)
    def _find_generic_source(self, module: str, name: str, kind: str='fn', depth: int=0):
        return gfn._find_generic_source(self, module, name, kind, depth)
    def _register_imported_generics(self, stmts) -> None:
        return gfn._register_imported_generics(self, stmts)
    def _register_imported_generic_structs(self, stmts) -> None:
        return gfn._register_imported_generic_structs(self, stmts)
    @staticmethod
    @staticmethod
    def _struct_method_overload_ids(stmt) -> list:
        return gfn._struct_method_overload_ids(stmt)
    def _struct_method_qualifier(self, struct_name: str) -> str:
        return gfn._struct_method_qualifier(self, struct_name)
    def _struct_method_csym(self, struct_name: str, method_name: str, overload_id: str='') -> str:
        return gfn._struct_method_csym(self, struct_name, method_name, overload_id)
    @staticmethod
    @staticmethod
    def _struct_method_csym_static(qualifier: str, struct_name: str, method_name: str, overload_id: str) -> str:
        return gfn._struct_method_csym_static(qualifier, struct_name, method_name, overload_id)
    def _gen_struct_method(self, struct_name: str, node: FunctionDef, overload_id: str='') -> str:
        return gfn._gen_struct_method(self, struct_name, node, overload_id)

    # ---- delegates: gimple_gen_loops.py ----
    def _gen_for_range(self, node: ForStmt):
        return glo._gen_for_range(self, node)
    def _get_actual_type(self, ctype: str, val: str) -> str:
        return glo._get_actual_type(self, ctype, val)
    def _tuple_elem_value(self, vtype: str, v: str, idx: int) -> tuple[str, str]:
        return glo._tuple_elem_value(self, vtype, v, idx)
    def _emit_unsupported_iter(self, it_type: str, node=None) -> None:
        return glo._emit_unsupported_iter(self, it_type, node)
    def _try_const_fold_int(self, expr) -> int | None:
        return glo._try_const_fold_int(self, expr)
    def _try_const_fold_str(self, expr) -> str | None:
        return glo._try_const_fold_str(self, expr)
    def _re_sub_repl_is_callback(self, cb_arg) -> bool:
        return glo._re_sub_repl_is_callback(self, cb_arg)
    def _lower_re_sub_callback(self, cb_arg) -> tuple[str, str]:
        return glo._lower_re_sub_callback(self, cb_arg)
    def _gen_for_regex_iter(self, node: ForStmt, pattern: str) -> None:
        return glo._gen_for_regex_iter(self, node, pattern)
    def _gen_for_iter(self, node: ForStmt):
        return glo._gen_for_iter(self, node)
    def _gen_for_enumerate(self, node):
        return glo._gen_for_enumerate(self, node)
    def _gen_for_list(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_list(self, var, it_val, body, shadow_name)
    def _gen_for_str(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_str(self, var, it_val, body, shadow_name)
    def _gen_for_cstr(self, var: str, it_val: str, body: list):
        return glo._gen_for_cstr(self, var, it_val, body)
    def _gen_for_dict(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_dict(self, var, it_val, body, shadow_name)
    def _gen_for_set(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_set(self, var, it_val, body, shadow_name)
    def _gen_lifted_closure(self, ci: ClosureInfo, outer_name: str=None) -> str:
        return glo._gen_lifted_closure(self, ci, outer_name)
    def _emit_generator_tuple_unpack(self, var_names: list, slot_types: list, list_ptr: str) -> None:
        return glo._emit_generator_tuple_unpack(self, var_names, slot_types, list_ptr)
    def _gen_for_generator_iter(self, var: str, gen_val: str, api: dict, body: list, destroy_after: bool=True):
        return glo._gen_for_generator_iter(self, var, gen_val, api, body, destroy_after)
    def _emit_generator_pending_exc_check(self, gen_val: str, base: str, destroy_after: bool, bb_not_pending: str):
        return glo._emit_generator_pending_exc_check(self, gen_val, base, destroy_after, bb_not_pending)
    def _gen_for_struct_iter(self, var: str, struct_type: str, obj_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_struct_iter(self, var, struct_type, obj_val, body, shadow_name)

    # ---- nested-AST accessors (keep attribute traffic on GimpleGen itself
    # so the self-host closure types these reads/writes in the monolith-era
    # context; see refactor/batch3-wip notes) ----
    def _get_fn_body(self, fn):
        return fn.body
    def _set_fn_body(self, fn, body) -> None:
        fn.body = body

    # ---- delegates: gimple_gen_stmts.py ----
    def gen_stmt(self, node):
        return gst.gen_stmt(self, node)
    def _gen_stmt_PassStmt(self, node):
        return gst._gen_stmt_PassStmt(self, node)
    def _annotation_dict_val_type(self, ann) -> str | None:
        return gst._annotation_dict_val_type(self, ann)
    def _gen_stmt_VarDecl(self, node):
        return gst._gen_stmt_VarDecl(self, node)
    def _track_pointer_actual_type(self, tname: str, dst: str, v: str, vtype: str) -> None:
        return gst._track_pointer_actual_type(self, tname, dst, v, vtype)
    def _assign_target(self, tgt, et, ev):
        return gst._assign_target(self, tgt, et, ev)
    def _is_except_as_member_target(self, obj_node) -> bool:
        return gst._is_except_as_member_target(self, obj_node)
    def _emit_dynattr_setattr_dispatch(self, member: str, vtype: str, v: str, ot: str, ov: str) -> None:
        return gst._emit_dynattr_setattr_dispatch(self, member, vtype, v, ot, ov)
    def _gen_stmt_AssignStmt(self, node):
        return gst._gen_stmt_AssignStmt(self, node)
    def _gen_stmt_AugAssignStmt(self, node):
        return gst._gen_stmt_AugAssignStmt(self, node)
    def _gen_stmt_ReturnStmt(self, node):
        return gst._gen_stmt_ReturnStmt(self, node)
    def _ensure_bool_cond(self, ctype: str, val: str) -> str:
        return gst._ensure_bool_cond(self, ctype, val)
    def _gen_stmt_IfStmt(self, node):
        return gst._gen_stmt_IfStmt(self, node)
    def _gen_stmt_DelStmt(self, node):
        return gst._gen_stmt_DelStmt(self, node)
    def _gen_stmt_MatchStmt(self, node):
        return gst._gen_stmt_MatchStmt(self, node)
    def _gen_stmt_WhileStmt(self, node):
        return gst._gen_stmt_WhileStmt(self, node)
    def _gen_stmt_MultiAssignStmt(self, node):
        return gst._gen_stmt_MultiAssignStmt(self, node)
    def _gen_stmt_ForStmt(self, node):
        return gst._gen_stmt_ForStmt(self, node)
    def _gen_stmt_BreakStmt(self, node):
        return gst._gen_stmt_BreakStmt(self, node)
    def _gen_stmt_ContinueStmt(self, node):
        return gst._gen_stmt_ContinueStmt(self, node)
    def _gen_stmt_ExprStmt(self, node):
        return gst._gen_stmt_ExprStmt(self, node)
    def _gen_stmt_AssertStmt(self, node):
        return gst._gen_stmt_AssertStmt(self, node)
    def _gen_stmt_RaiseStmt(self, node):
        return gst._gen_stmt_RaiseStmt(self, node)
    def _handler_exc_name(self, h):
        return gst._handler_exc_name(self, h)
    def _handler_exc_all_names(self, h):
        return gst._handler_exc_all_names(self, h)
    def _handler_bind_name(self, h):
        return gst._handler_bind_name(self, h)
    def _emit_except_handler(self, handler, node, bb_after):
        return gst._emit_except_handler(self, handler, node, bb_after)
    def _gen_stmt_TryStmt(self, node):
        return gst._gen_stmt_TryStmt(self, node)
    def _gen_stmt_WithStmt(self, node):
        return gst._gen_stmt_WithStmt(self, node)

    # ---- delegates via gex ----
    def _lower_strided(self, node, store: bool):
        return gex._lower_strided(self, node, store)
    def lower_expr(self, node) -> tuple[str, str]:
        return gex.lower_expr(self, node)
    def _lower_IntLiteral(self, node) -> tuple[str, str]:
        return gex._lower_IntLiteral(self, node)
    def _lower_FloatLiteral(self, node) -> tuple[str, str]:
        return gex._lower_FloatLiteral(self, node)
    def _lower_BoolLiteral(self, node) -> tuple[str, str]:
        return gex._lower_BoolLiteral(self, node)
    def _lower_EllipsisLiteral(self, node) -> tuple[str, str]:
        return gex._lower_EllipsisLiteral(self, node)
    def _lower_StringLiteral(self, node):
        return gex._lower_StringLiteral(self, node)
    def _lower_TstringLiteral(self, node) -> tuple[str, str]:
        return gex._lower_TstringLiteral(self, node)
    def _lower_IdentExpr(self, node) -> tuple[str, str]:
        return gex._lower_IdentExpr(self, node)
    def _lower_WalrusExpr(self, node) -> tuple[str, str]:
        return gex._lower_WalrusExpr(self, node)
    def _lower_UnaryOp(self, node) -> tuple[str, str]:
        return gex._lower_UnaryOp(self, node)
    def _lower_TernaryExpr(self, node) -> tuple[str, str]:
        return gex._lower_TernaryExpr(self, node)
    def _lower_MemberExpr(self, node) -> tuple[str, str]:
        return gex._lower_MemberExpr(self, node)
    def _lower_binary(self, node: BinaryOp) -> tuple[str, str]:
        return gex._lower_binary(self, node)
    def _lower_binary_tail(self, op: str, left_node, lt: str, lv: str, right_node, rt: str, rv: str) -> tuple[str, str]:
        return gex._lower_binary_tail(self, op, left_node, lt, lv, right_node, rt, rv)
    def _lower_compare_chain(self, node: CompareChain) -> tuple[str, str]:
        return gex._lower_compare_chain(self, node)
    def _lower_percent(self, node: BinaryOp):
        return gex._lower_percent(self, node)
    def _lower_percent_format(self, node: BinaryOp, fmt_text: str) -> tuple[str, str]:
        return gex._lower_percent_format(self, node, fmt_text)
    def _lower_floordiv(self, node: BinaryOp) -> tuple[str, str]:
        return gex._lower_floordiv(self, node)
    def _lower_pow(self, node: BinaryOp) -> tuple[str, str]:
        return gex._lower_pow(self, node)
    def _lower_matmul(self, node: BinaryOp) -> tuple[str, str]:
        return gex._lower_matmul(self, node)
    def _lower_in_range(self, x_val: str, range_args: list, negate: bool) -> tuple[str, str]:
        return gex._lower_in_range(self, x_val, range_args, negate)
    def _lower_in_impl(self, node: BinaryOp, negate: bool) -> tuple[str, str]:
        return gex._lower_in_impl(self, node, negate)
    def _lower_in_impl_values(self, xt: str, xv: str, right_node, negate: bool) -> tuple[str, str]:
        return gex._lower_in_impl_values(self, xt, xv, right_node, negate)
    def _lower_in_dispatch(self, xt: str, xv: str, rt: str, rv: str, negate: bool) -> tuple[str, str]:
        return gex._lower_in_dispatch(self, xt, xv, rt, rv, negate)
    def _lower_external_call(self, node: CallExpr) -> tuple[str, str]:
        return gex._lower_external_call(self, node)
    def _lower_mlir_mem(self, kind: str, arg_pairs: list) -> tuple[str, str]:
        return gex._lower_mlir_mem(self, kind, arg_pairs)
    def _lower_mlir_struct(self, kind: str, index, arg_pairs: list):
        return gex._lower_mlir_struct(self, kind, index, arg_pairs)
    def _lower_list_literal(self, node: ListExpr) -> tuple[str, str]:
        return gex._lower_list_literal(self, node)
    def _lower_dict_literal(self, node: DictExpr) -> tuple[str, str]:
        return gex._lower_dict_literal(self, node)
    def _lower_set_literal(self, node: SetExpr) -> tuple[str, str]:
        return gex._lower_set_literal(self, node)
    def _lower_tuple_literal(self, node: TupleExpr) -> tuple[str, str]:
        return gex._lower_tuple_literal(self, node)
    def _lower_comprehension(self, node: Comprehension) -> tuple[str, str]:
        return gex._lower_comprehension(self, node)

    # ---- delegates via gcc_ ----
    def _cpp_short_circuit_bool(self, node) -> bool | None:
        return gcc_._cpp_short_circuit_bool(self, node)
    def _cpp_in_link(self, a: str, a_node, b: str, b_node, negate: bool) -> str:
        return gcc_._cpp_in_link(self, a, a_node, b, b_node, negate)
    def _cpp_try_kwargs_forward_call(self, e):
        return gcc_._cpp_try_kwargs_forward_call(self, e)
    def _cpp_expr(self, e) -> str:
        return gcc_._cpp_expr(self, e)
    def _cpp_yield_tuple(self, tup: 'TupleExpr', declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_yield_tuple(self, tup, declared, indent)
    def _cpp_hoist_walrus_decls(self, expr, declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_hoist_walrus_decls(self, expr, declared, indent)
    def _cpp_stmt(self, s, declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_stmt(self, s, declared, indent)
    def _cpp_with_stmt(self, s, declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_with_stmt(self, s, declared, indent)
    def _cpp_for_generator_delegate(self, target, call: 'CallExpr', body: list, declared: dict, indent: str, index_var: str=None, index_start_expr: str='0') -> list[str]:
        return gcc_._cpp_for_generator_delegate(self, target, call, body, declared, indent, index_var, index_start_expr)
    def _cpp_for_stmt(self, s: 'ForStmt', declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_for_stmt(self, s, declared, indent)
    def _cpp_async_for_stmt(self, s: 'ForStmt', declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_async_for_stmt(self, s, declared, indent)
    def _cpp_raise_stmt(self, s, indent: str) -> list[str]:
        return gcc_._cpp_raise_stmt(self, s, indent)
    def _cpp_try_stmt(self, node, declared: dict, indent: str) -> list[str]:
        return gcc_._cpp_try_stmt(self, node, declared, indent)
    def _cpp_yield_from(self, yf: 'YieldFromExpr', indent: str) -> list[str]:
        return gcc_._cpp_yield_from(self, yf, indent)
    def _cls_refs_supported(self, body, struct_name: str) -> bool:
        return gcc_._cls_refs_supported(self, body, struct_name)

    # ---- delegates via gca ----
    def _cpp_declared_type(self, node) -> str | None:
        return gca._cpp_declared_type(self, node)
    def _cpp_known_ptr_struct(self, g_mtype: str) -> bool:
        return gca._cpp_known_ptr_struct(self, g_mtype)
    def _cpp_struct_ptr_local(self, name: str) -> str | None:
        return gca._cpp_struct_ptr_local(self, name)
    def _cpp_is_callable_value_expr(self, node) -> bool:
        return gca._cpp_is_callable_value_expr(self, node)
    def _cpp_dict_key_expr(self, idx_node, idx_cpp: str) -> str:
        return gca._cpp_dict_key_expr(self, idx_node, idx_cpp)
    def _cpp_fresh_name(self, prefix: str='_mg_t') -> str:
        return gca._cpp_fresh_name(self, prefix)
    def _cpp_stmt_with_break_flag(self, s, declared: dict, indent: str, brk_var: str) -> list[str]:
        return gca._cpp_stmt_with_break_flag(self, s, declared, indent, brk_var)
    def _cpp_with_guard_type_name(self, expr) -> str | None:
        return gca._cpp_with_guard_type_name(self, expr)
    def _cpp_iterable_is_delegatable_generator_call(self, iterable) -> bool:
        return gca._cpp_iterable_is_delegatable_generator_call(self, iterable)
    def _cpp_match_stmt(self, s, declared: dict, indent: str) -> list[str]:
        return gca._cpp_match_stmt(self, s, declared, indent)
    def _cpp_except_handler_body(self, handler, caught_var: str, declared: dict, indent: str) -> list[str]:
        return gca._cpp_except_handler_body(self, handler, caught_var, declared, indent)
    def _gen_cpp_generator_unit(self, fn: FunctionDef, struct_name: str | None=None) -> tuple[str, str, str, list]:
        return gca._gen_cpp_generator_unit(self, fn, struct_name)
    def _compute_nested_closure_captures(self, inner: FunctionDef, outer_scope: dict) -> list:
        return gca._compute_nested_closure_captures(self, inner, outer_scope)
    def _enclosing_scope_with_locals(self, outer_fn: FunctionDef) -> dict:
        return gca._enclosing_scope_with_locals(self, outer_fn)
    def _mutated_free_names(self, inner: FunctionDef, candidate_names) -> frozenset:
        return gca._mutated_free_names(self, inner, candidate_names)
    def _gen_cpp_async_unit(self, fn: FunctionDef, extra_captures: list | None=None, base_name_override: str | None=None, scope_prefix: str | None=None, enclosing_scope: str | None=None, mut_capture_names: frozenset=frozenset()) -> tuple[str, str, str, list]:
        return gca._gen_cpp_async_unit(self, fn, extra_captures, base_name_override, scope_prefix, enclosing_scope, mut_capture_names)
    def _resolve_and_start_task(self, inner) -> tuple[str, dict] | None:
        return gca._resolve_and_start_task(self, inner)
    def _resolve_kwargs_for_known_async_call(self, call) -> None:
        return gca._resolve_kwargs_for_known_async_call(self, call)
    def _normalize_await_kwargs(self, body: list) -> None:
        return gca._normalize_await_kwargs(self, body)
    def _inline_single_use_task_composition(self, body: list) -> list:
        return gca._inline_single_use_task_composition(self, body)
    def _compile_nested_async_functions(self, outer_fn: FunctionDef, async_fns: dict) -> None:
        return gca._compile_nested_async_functions(self, outer_fn, async_fns)
    def _gen_cpp_async_generator_unit(self, fn: FunctionDef) -> tuple[str, str, str, list]:
        return gca._gen_cpp_async_generator_unit(self, fn)

    # ---- delegates via ginf ----
    def _exc_type_id(self, name: str) -> int:
        return ginf._exc_type_id(self, name)
    def _is_exc_class_name(self, name: str) -> bool:
        return ginf._is_exc_class_name(self, name)
    def _reset_func(self, body: list=None, params: list=None):
        return ginf._reset_func(self, body, params)
    def _record_sys_path_inserts(self, source: str, base_dir: str=None) -> None:
        return ginf._record_sys_path_inserts(self, source, base_dir)
    def _compile_link_inline_cpp_unit(self, cpp_code: str):
        return ginf._compile_link_inline_cpp_unit(self, cpp_code)
    def _emit_stdlib_import_externs(self, stmts) -> None:
        return ginf._emit_stdlib_import_externs(self, stmts)
    def _emit_imported_global_accessors(self, stmts) -> None:
        return ginf._emit_imported_global_accessors(self, stmts)
    def _new_bb(self) -> str:
        return ginf._new_bb(self)
    def _emit(self, line: str):
        return ginf._emit(self, line)
    def _type_of(self, name: str) -> str:
        return ginf._type_of(self, name)
    def _elem_of(self, name: str) -> str:
        return ginf._elem_of(self, name)
    def _dict_val_of(self, name: str) -> str:
        return ginf._dict_val_of(self, name)
    def _emit_call(self, ret_type: str, result_var: str, fname: str, arg_pairs: list) -> None:
        return ginf._emit_call(self, ret_type, result_var, fname, arg_pairs)
    def _declared_int_ctype(self, val: str) -> str | None:
        return ginf._declared_int_ctype(self, val)
    def _ensure_local(self, ctype: str, val: str) -> str:
        return ginf._ensure_local(self, ctype, val)
    def _char_to_cstr(self, typ: str, val: str) -> tuple[str, str]:
        return ginf._char_to_cstr(self, typ, val)
    def _resolve_type(self, ann: str | None) -> str:
        return ginf._resolve_type(self, ann)
    def _infer_param_types(self, func: FunctionDef) -> dict[str, str]:
        return ginf._infer_param_types(self, func)
    def _declare_var(self, name: str, ctype: str, elem: str | None=None, force: bool=False):
        return ginf._declare_var(self, name, ctype, elem, force)
    def _write_dest(self, name: str) -> str:
        return ginf._write_dest(self, name)
    def _seed_mut_captured_local_types(self, func_name: str):
        return ginf._seed_mut_captured_local_types(self, func_name)
    def _new_jbp_temp(self) -> str:
        return ginf._new_jbp_temp(self)
    def _closure_info_for_ident(self, name: str):
        return ginf._closure_info_for_ident(self, name)
    def _collect_return_types(self, stmts: list, acc: list):
        return ginf._collect_return_types(self, stmts, acc)
    def _coerce_to_type(self, src_type: str, dst_type: str, value: str) -> str:
        return ginf._coerce_to_type(self, src_type, dst_type, value)
    def _infer_return_type(self, body: list) -> str:
        return ginf._infer_return_type(self, body)
    def _quick_container_elem(self, node) -> str | None:
        return ginf._quick_container_elem(self, node)
    def _prepass_list_elem(self, elements) -> str:
        return ginf._prepass_list_elem(self, elements)
    def _fstring_sub_exprs(self, node) -> list:
        return ginf._fstring_sub_exprs(self, node)
    def _scan_container_elems(self, body: list) -> tuple[dict, dict, dict]:
        return ginf._scan_container_elems(self, body)
    def _list_repr_fn(self, rav: str) -> str:
        return ginf._list_repr_fn(self, rav)
    def _stringify_value(self, et: str, ev: str) -> str:
        return ginf._stringify_value(self, et, ev)
    def _apply_fstring_spec(self, part_val: str, spec: str) -> str:
        return ginf._apply_fstring_spec(self, part_val, spec)
    def _subst_in_value(self, v, mapping: dict):
        return ginf._subst_in_value(self, v, mapping)
    def _is_known_field(self, member: str) -> bool:
        return ginf._is_known_field(self, member)
    def _known_field_type(self, member: str) -> str | None:
        return ginf._known_field_type(self, member)
    def _try_lower_slice_region_eq(self, slice_node, other_node, negate: bool):
        return ginf._try_lower_slice_region_eq(self, slice_node, other_node, negate)
    def _sprintf_one(self, c_spec: str, arg_val: str) -> str:
        return ginf._sprintf_one(self, c_spec, arg_val)
    def _to_int64(self, ctype: str, val: str) -> str:
        return ginf._to_int64(self, ctype, val)
    def _resolve_member_expr_type(self, node) -> str | None:
        return ginf._resolve_member_expr_type(self, node)
    def _elaborate_overload_call(self, node: CallExpr):
        return ginf._elaborate_overload_call(self, node)
    def _maybe_lower_mlir_op(self, node: CallExpr):
        return ginf._maybe_lower_mlir_op(self, node)
    def _compr_range_loop(self, node, gen0, res, res_type):
        return ginf._compr_range_loop(self, node, gen0, res, res_type)
    def _compr_list_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_list_loop(self, node, gen0, res, res_type, it_val)
    def _compr_generator_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_generator_loop(self, node, gen0, res, res_type, it_val)
    def _compr_dict_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_dict_loop(self, node, gen0, res, res_type, it_val)
    def _compr_set_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_set_loop(self, node, gen0, res, res_type, it_val)
    def _gen_print(self, args: list, kwargs: list=None):
        return ginf._gen_print(self, args, kwargs)
    def _eval_const_int(self, node) -> int | None:
        return ginf._eval_const_int(self, node)
    def _eval_const_bool(self, node) -> bool | None:
        return ginf._eval_const_bool(self, node)
    def _split_top_level_comma(self, s: str) -> list[str]:
        return ginf._split_top_level_comma(s)
    def _dedup_variadic_externs(self, parts: list) -> str:
        return ginf._dedup_variadic_externs(parts)

    # ---- delegates via grsl ----
    def _locally_bound_names(self, body: list, params: list=None) -> set:
        return grsl._locally_bound_names(self, body, params)
    def _module_candidate_paths(self, module_name: str) -> list:
        return grsl._module_candidate_paths(self, module_name)
    def _submodule_source_path(self, module_name: str) -> str | None:
        return grsl._submodule_source_path(self, module_name)
    def _compile_imported_module(self, module_name: str) -> tuple:
        return grsl._compile_imported_module(self, module_name)
    def _register_link_imports(self, stmts) -> list:
        return grsl._register_link_imports(self, stmts)
    def _register_reflected_struct(self, name, type_info, exports, parse_c_sig):
        return grsl._register_reflected_struct(self, name, type_info, exports, parse_c_sig)
    def _new_temp(self, ctype: str) -> str:
        return grsl._new_temp(self, ctype)
    def _new_val(self, ctype: str, rhs: str) -> str:
        return grsl._new_val(self, ctype, rhs)
    def _call_expr(self, ret_type: str, fname: str, arg_pairs: list) -> str:
        return grsl._call_expr(self, ret_type, fname, arg_pairs)
    def _void_call(self, fname: str, arg_pairs: list) -> tuple:
        return grsl._void_call(self, fname, arg_pairs)
    def _emit_label(self, label: str, freq_hint: str=''):
        return grsl._emit_label(self, label, freq_hint)
    def _scalar_arg_is_addressable_local(self, aval) -> bool:
        return ginf._scalar_arg_is_addressable_local(self, aval)
    def _strided_data_ptr(self, pt: str, pv: str) -> str:
        return grsl._strided_data_ptr(self, pt, pv)
    def _safe_coerce_emit(self, src: str, dst: str, val: str, lhs: str) -> None:
        return grsl._safe_coerce_emit(self, src, dst, val, lhs)
    def _cname(self, name: str) -> str:
        return grsl._cname(self, name)
    def _closure_value_locals(self, body: list) -> dict:
        return grsl._closure_value_locals(self, body)
    def _quick_type(self, node) -> str:
        return grsl._quick_type(self, node)
    def _infer_list_elem_type(self, elements: list) -> str:
        return grsl._infer_list_elem_type(self, elements)
    def _prepass_callee_key(self, node) -> str | None:
        return grsl._prepass_callee_key(self, node)
    def _collect_local_container_elems(self, stmts) -> None:
        return grsl._collect_local_container_elems(self, stmts)
    def _collect_return_elems(self, stmts, acc) -> None:
        return grsl._collect_return_elems(self, stmts, acc)
    def _infer_return_elem_type(self, body, func_def=None,
                                _base_var_types=None) -> str | None:
        return grsl._infer_return_elem_type(self, body, func_def=func_def,
                                            _base_var_types=_base_var_types)
    def _infer_local_var_types(self, func: FunctionDef) -> dict[str, str]:
        return grsl._infer_local_var_types(self, func)
    def _collect_calls(self, expr, out):
        return grsl._collect_calls(self, expr, out)
    def _calls_in_stmts(self, stmts, out):
        return grsl._calls_in_stmts(self, stmts, out)
    def _split_expr_format(self, src: str) -> str:
        return grsl._split_expr_format(src)
    def _parse_fstring_parts(self, inner):
        return grsl._parse_fstring_parts(self, inner)
    def _repr_value(self, rat: str, rav: str) -> str:
        return grsl._repr_value(self, rat, rav)
    def _decode_str_literal_text(self, val: str) -> tuple[str, bool]:
        return grsl._decode_str_literal_text(self, val)
    def _stub_result(self, ctype: str, value: str, note: str) -> tuple[str, str]:
        return grsl._stub_result(self, ctype, value, note)
    def _intern_string(self, escaped: str) -> str:
        return grsl._intern_string(self, escaped)
    def _str_literal_to_slit(self, str_literal: str) -> str:
        return grsl._str_literal_to_slit(self, str_literal)
    def _subst_idents(self, expr, mapping: dict):
        return grsl._subst_idents(self, expr, mapping)
    def _format_percent_spec(self, full_spec: str, conv: str, et: str, ev: str) -> str:
        return grsl._format_percent_spec(self, full_spec, conv, et, ev)
    def _cast_for_list(self, elem_type: str, val: str, suf: str) -> str:
        return grsl._cast_for_list(self, elem_type, val, suf)
    def _type_expr_to_ann(self, node) -> str:
        return grsl._type_expr_to_ann(self, node)
    def _static_generic_return_ctype(self, func_name: str) -> str | None:
        return grsl._static_generic_return_ctype(self, func_name)
    def _elaborate_generic_call(self, node: CallExpr):
        return grsl._elaborate_generic_call(self, node)
    def _refine_generic_return_type(self, info: dict, module_src: str, g: str, mangled_type_args: list, arg_count: int) -> None:
        return grsl._refine_generic_return_type(self, info, module_src, g, mangled_type_args, arg_count)
    def _ensure_generic_struct(self, base_name: str, type_args: list) -> str | None:
        return grsl._ensure_generic_struct(self, base_name, type_args)
    def _elaborate_generic_struct_call(self, node: CallExpr):
        return grsl._elaborate_generic_struct_call(self, node)
    def _emit_generic_instantiation(self, info, arg_pairs):
        return grsl._emit_generic_instantiation(self, info, arg_pairs)
    def _as_ptr(self, ctype: str, val: str) -> tuple[str, str]:
        return grsl._as_ptr(self, ctype, val)
    def _is_none_literal(self, el) -> bool:
        return grsl._is_none_literal(el)
    def _literal_elements_include_none(self, elements: list) -> bool:
        return grsl._literal_elements_include_none(self, elements)
    def _compr_enumerate_loop(self, node, gen0, res, res_type, it_val, start_val):
        return grsl._compr_enumerate_loop(self, node, gen0, res, res_type, it_val, start_val)
    def _compr_str_loop(self, node, gen0, res, res_type, it_val):
        return grsl._compr_str_loop(self, node, gen0, res, res_type, it_val)
    def _compr_cstr_loop(self, node, gen0, res, res_type, it_val):
        return grsl._compr_cstr_loop(self, node, gen0, res, res_type, it_val)
    def _gen_compr_append(self, node: Comprehension, gen0, res: str, res_type: str, bb_skip: str):
        return grsl._gen_compr_append(self, node, gen0, res, res_type, bb_skip)
    def _is_sys_stderr(self, expr) -> bool:
        return grsl._is_sys_stderr(expr)
    def _module_const_int(self, name: str, stmts: list, imported_stmts: list | None) -> int | None:
        return grsl._module_const_int(self, name, stmts, imported_stmts)
    def _eval_const_compare_op(self, op: str, left, right):
        return grsl._eval_const_compare_op(self, op, left, right)
    def _eval_const(self, node):
        return grsl._eval_const(self, node)

def _run_pipeline(mojo_src: str, *, do_imports: bool = False, filename: str = "",
                  link_mode: bool = False):
    """Shared driver behind every public compile_* entry point.

    One place owns the per-compile setup so the wrappers cannot drift apart
    again (BUG-2026-032 was exactly such drift between inline and link
    modes): reset cross-file dedup state, tokenize -> parse -> AST-rewrite,
    construct GimpleGen with the right mode flags, seed the self-import
    guard, honor sys.path.insert pre-scans, run gen_module. Returns
    (c_code, gen) so callers can read companion artifacts off the instance
    (generated_cpp, _link_dylibs, ...).
    """
    # One call here = one independent output artifact (this project's own
    # transitive-closure dumps included - the whole multi-file closure is one
    # call). Reset cross-file dedup state so it can't leak stale "already
    # emitted" markers between unrelated compiles that happen to share this
    # process (e.g. compile_stdlib.py compiling many independent modules),
    # while still deduping correctly *within* one call across every nested
    # GimpleGen instance recursive import-inlining creates. Now applied in
    # ALL modes — link mode historically skipped this (REF.html B1).
    _emitted_unresolved_stub_syms.clear()
    global _emitted_type_name_emitted  # B2: plain-bool reset
    _emitted_type_name_emitted = False
    tokens = py_tokenize(mojo_src)
    stmts = ast_rewriter.rewrite(Parser(tokens).with_filename(filename).parse_module())
    gen = GimpleGen(do_imports=do_imports, link_imports=link_mode)
    gen._current_filename = filename
    # Seed the self-import guard with the ROOT file's own identity — see
    # `_compiling_file_paths`'s declaration for why this is needed (a bare
    # import elsewhere in this file that happens to share this file's own
    # basename, e.g. `Lib/importlib/abc.py`'s `import abc`, must not resolve
    # back to this same file and get compiled a second time).
    if filename:
        gen._compiling_file_paths.add(os.path.abspath(filename))
    # Honor sys.path.insert(...) pre-scans in every mode: inline modes only
    # did this under do_imports, link mode only when a filename was given —
    # the drift that caused BUG-2026-032. The None base-dir argument matches
    # the inline-mode no-filename shape and is supported.
    if do_imports or link_mode:
        gen._record_sys_path_inserts(
            mojo_src, os.path.dirname(os.path.abspath(filename)) if filename else None)
    return gen.gen_module(stmts), gen


def compile_to_c(mojo_src: str) -> str:
    """Parse Mojo source and return C code WITHOUT __GIMPLE annotations.

    Useful for execution tests where __GIMPLE restrictions don't apply.
    """
    c_code, _gen = _run_pipeline(mojo_src)

    # Strip __GIMPLE annotations for executability
    c_code = c_code.replace(' __GIMPLE ', ' ')
    return c_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_compile_cache: dict = {}  # key -> str  (in-process L1 for compile_to_gimple_cached)

_IMPORT_LINE_RE = re.compile(r'^\s*(?:from|import)\s+([.\w]+)', re.MULTILINE)


def _dep_sources_digest(mojo_src: str, filename: str) -> str:
    """Digest of every non-stdlib source this compile can read: the transitive
    import closure of sibling modules resolved next to the entry file — both
    .mojo and .py (mojo.py's own bootstrap dumps inline .py siblings like
    myinterpreter.py). Mirrors how codegen finds them (imports.resolve_source,
    then _resolve_test_relative_module's walk up the entry file's ancestors).
    Stdlib sources are skipped: cas.stdlib_fingerprint() already covers every
    stdlib file, and re-hashing the reachable stdlib per compile would turn a
    cheap scan into a closure walk. Best-effort by design: an import the scan
    can't resolve contributes nothing (codegen skips it too), and hashing a
    file codegen never opens only over-invalidates, never goes stale."""
    import cas
    import imports as _imp
    try:
        from module_loader import STDLIB_PATH
        stdlib_root = os.path.abspath(STDLIB_PATH) + os.sep if STDLIB_PATH else None
    except Exception:
        stdlib_root = None
    seen = {}

    def _resolve(mod: str, fdir: str):
        try:
            path = _imp.resolve_source(mod)
        except Exception:
            path = None
        if path:
            return path
        rel = os.path.join(*mod.strip('.').split('.')) if mod.strip('.') else ''
        d = fdir
        while rel and d:
            for ext in ('.mojo', '.py'):
                cand = os.path.join(d, rel + ext)
                if os.path.exists(cand):
                    return cand
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    def _scan(src: str, fdir: str):
        for mod in _IMPORT_LINE_RE.findall(src):
            path = _resolve(mod, fdir)
            if not path:
                continue
            path = os.path.abspath(path)
            if path in seen or (stdlib_root and path.startswith(stdlib_root)):
                continue
            try:
                with open(path) as f:
                    text = f.read()
            except OSError:
                continue
            seen[path] = text
            _scan(text, os.path.dirname(path))

    _scan(mojo_src, os.path.dirname(os.path.abspath(filename)) if filename else '')
    if not seen:
        return ''
    return cas._hash(*(f'{p}\0{seen[p]}' for p in sorted(seen)))


def compile_to_gimple_cached(mojo_src: str, do_imports: bool = False, filename: str = "") -> str:
    """Like compile_to_gimple but CAS-cached (plus an in-process L1).

    The full tokenize -> parse -> AST-rewrite -> gen_module pipeline is
    content-addressed: the key covers everything it reads — the entry source,
    mode, filename, the compiler + stdlib fingerprints, and the sibling-import
    closure digest — so every caller (--dump, build_executable, build_mojo_cli,
    build_module, Makefile dump loops) shares one cache line per unique input
    set, and editing any transitively imported file invalidates it with no
    manual versioning.

    NOTE: the self-hosted compiler lowers calls to this function to the same
    C shim as compile_to_gimple (see the gimple_codegen method special-case in
    lower_method_call) — the compiled binary compiles uncached, which is
    correct, just slower."""
    import cas
    key = cas.compile_key(mojo_src, do_imports, filename,
                          deps_digest=_dep_sources_digest(mojo_src, filename))
    return cas.get_or_build_text(
        key, '.ci',
        lambda: compile_to_gimple(mojo_src, do_imports, filename),
        _compile_cache)


def compile_to_gimple(mojo_src: str, do_imports: bool = False, filename: str = "") -> str:
    """Parse Mojo source and return a C string with __GIMPLE annotations.

    If do_imports=True, recursively compile imported modules and inline their code.
    If do_imports=False, imports are recorded as metadata only.
    If filename is provided, emit #line directives with the filename.

    (Kept at this exact 3-arg signature: the self-hosting bootstrap emits a
    matching forward declaration for it. Link mode is a separate entry point —
    compile_to_gimple_linked — to avoid changing this ABI.)
    """
    # One call here = one independent output artifact (this project's own
    # transitive-closure dumps included - the whole multi-file closure is one
    # call). Reset cross-file dedup state so it can't leak stale "already
    # emitted" markers between unrelated compiles that happen to share this
    # process (e.g. compile_stdlib.py compiling many independent modules),
    # while still deduping correctly *within* one call across every nested
    # GimpleGen instance recursive import-inlining creates.
    result, _gen = _run_pipeline(mojo_src, do_imports=do_imports, filename=filename)
    return result


def compile_to_gimple_with_cpp(mojo_src: str, do_imports: bool = False,
                                filename: str = "") -> tuple[str, str]:
    """Like compile_to_gimple, but ALSO returns the companion .cpp text
    (Milestone B's C++20-coroutine translation of this module's supported
    generator function(s), '' if there are none). A separate entry point
    rather than changing compile_to_gimple's own return shape — that
    function's exact 3-arg-in/1-str-out signature is pinned (the self-hosted
    bootstrap forward-declares it and compile_to_gimple_cached's CAS-cache
    layer stores exactly one '.ci' text blob per key), so this is purely
    additive. NOT CAS-cached (unlike compile_to_gimple_cached) — only called
    by build paths that already checked (via a cheap pre-scan, no full
    compile) that this module actually contains a supported generator, so
    the extra work only happens on the rare module that needs it."""
    c_code, gen = _run_pipeline(mojo_src, do_imports=do_imports, filename=filename)
    return c_code, gen.generated_cpp


def module_may_have_supported_generator(mojo_src: str) -> bool:
    """Cheap, purely-textual pre-scan: does this source even MENTION `yield`
    or `async def` outside a string/comment? Used by build_executable/
    build_stdlib_dylib.py to decide whether a module is worth routing
    through the uncached compile_to_gimple_with_cpp at all (the
    overwhelmingly common case, neither anywhere, keeps using the existing
    cached compile_to_gimple_cached path — see that function's own
    docstring — completely unchanged). A false positive here just costs one
    extra (uncached) compile attempt that then finds generated_cpp == ''
    and behaves exactly like the plain path; a false negative would
    incorrectly skip the C++20-coroutine path entirely, so this
    intentionally over-triggers (a dumb substring check) rather than
    under-triggers. Name kept as-is (not renamed to something like
    "..._or_async") despite now covering both generator and async codegen —
    it has exactly one call site (mojo.py's build_executable) and its
    return value's MEANING ("routing through compile_to_gimple_with_cpp is
    worth trying") hasn't changed, only the set of source shapes that can
    make that true."""
    return 'yield' in mojo_src or 'async def' in mojo_src


def compile_to_gimple_linked(mojo_src: str, filename: str = "") -> str:
    """Like compile_to_gimple, but in *link mode*: imported symbols become
    `extern` declarations (bodies come from a linked artifact / stdlib dylib;
    see MODULE_CACHE_DESIGN.md and ABI.md) rather than being inlined."""
    return compile_linked(mojo_src, filename)[0]


def compile_linked(mojo_src: str, filename: str = "") -> tuple:
    """Link-mode compile that also returns what the driver must link: the
    dylibs `import` recorded, the object files elaboration produced
    (generic instantiations — possibly including a C++-compiled coroutine
    unit for a generic whose body needed one, e.g. test_tracing.mojo's own
    `test_tracing[level, enabled]()` — see monomorphize.instantiate's
    `cpp_object`), this module's OWN top-level companion .cpp text (real
    Mojo's `async def f(): ...`/generator content directly in THIS module,
    as opposed to inside an elaborated generic — '' if none), and whether
    the final link needs a C++-aware driver at all (True if either of the
    previous two is non-empty). Returns (c_code, [dylib, ...],
    [object, ...], cpp_code, needs_cxx).

    Before this gained the last two return values, link-mode compiles had
    NO way to signal "this program needs C++/coroutine support at link
    time" at all — confirmed via a direct repro: a program with an
    ordinary top-level `async def`/`create_task(...)` compiled fine through
    this function (the `.c` side has no problem referencing the coroutine
    unit's symbols) but FAILED TO LINK when driven through driver.py's
    `compile_program` (plain `gcc`, no companion .cpp ever compiled) —
    silently papered over in practice only because `mojo.py build`/`run`
    fall back to a completely different, simpler inline pipeline
    (`mojo.py`'s own `build_executable`, which already had this handling)
    whenever `driver.compile_program` fails, masking the gap."""
    code, gen = _run_pipeline(mojo_src, filename=filename, link_mode=True)
    # `gen._link_needs_cxx_box[0]`: a coroutine unit discovered several
    # `_compile_imported_module` levels deep (a do_imports=True-only nested
    # temp_gen, not `gen` itself) sets this shared box rather than `gen`'s
    # own `_link_needs_cxx` attribute directly — see the box's own
    # declaration and `_compile_imported_module`'s matching write site for
    # the full reasoning (bugs/COMPILE_FAIL_Tools_cases_generator_parser.md).
    needs_cxx = gen._link_needs_cxx or gen._link_needs_cxx_box[0] or bool(gen.generated_cpp)
    return (code,
            list(dict.fromkeys(gen._link_dylibs)),
            list(dict.fromkeys(gen._link_objects)),
            gen.generated_cpp,
            needs_cxx)
