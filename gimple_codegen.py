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
        self._emitted_structs: set[str] = set()      # struct names already emitted (dedup across modules)
        self._str_pool: dict[str, str] = {}          # escaped string → _slit_N (shared across imports)
        # Compile-time-known regex support (see regex_compile.py, BACKLOG-CODEGEN.md §4f):
        self._regex_patterns: dict[str, str] = {}    # `X = re.compile("...")` var name → pattern source
        self._regex_progs: dict[str, dict] = {}      # pattern source → regex_compile.compile_pattern(...) result
        self._regex_progs_defined: set = set()       # pattern source → already emitted its C decl (avoid duplicate `static const ARRAY[] = {...}` across submodules)
        self._find_generic_visited: set = set()      # (module, name, kind) already visited by _find_generic_source (breaks import cycles)
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
        'mojo_getattr':          ('int64_t',   ['void *', 'char *']),
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
        self._actual_types['stmts'] = 'MojoList *'
        # Direct local-sibling modules this file imports at top level (e.g.
        # `from base.resource import ...`) — populated by the "Process
        # imports" loop below, consumed by _gen_toplevel to call each
        # sibling's own <module>_init() before this module's own top-level
        # code runs. Fresh per gen_module call (never leaks across the
        # separate GimpleGen instances driver.compile_dylib/build_stdlib_
        # dylib.py spin up per module). See _gen_toplevel's own comment for
        # why this is needed: cross-module __attribute__((constructor))
        # firing order in a `mojo dylib` build follows link/discovery order
        # (driver._expand_dylib_modules' BFS), NOT the real dependency
        # graph, so a module whose top-level code calls into a transitively
        # -imported sibling's globals can run before that sibling's own
        # ctor has initialized them.
        self._toplevel_dep_init_modules: list[str] = []
        # Fold every TOP-LEVEL `comptime NAME = value` into self._comptime_vals
        # BEFORE anything else in this module gets compiled. Without this, a
        # module-level comptime constant was invisible everywhere: the only
        # two existing fold sites are `_gen_stmt_ComptimeVarStmt` (fires
        # during ordinary Phase 2a statement generation — but a top-level
        # ComptimeVarStmt is never even added to `toplevel_stmts` below,
        # since its isinstance tuple doesn't include ComptimeVarStmt, so
        # that never runs for one) and the FUNCTION-nested pre-fold a few
        # thousand lines down (scoped to `stmt.body` of the function
        # currently being compiled, not file/module scope). Every OTHER
        # reference anywhere in the file — struct field array-size
        # annotations, ordinary runtime reads via `_lower_IdentExpr`, bounds
        # checks — silently read the "ct param or undeclared" placeholder
        # value 0 instead. See test_gimple.py's
        # "toplevel_comptime_const_visible_everywhere". Recurses into
        # IfStmt/TryStmt/While/For bodies (mirroring this file's other
        # top-level pre-scans) since a comptime constant can legitimately be
        # declared inside a platform-resolved `if` block; processes in
        # source order so a later comptime referencing an earlier one folds
        # correctly.
        def _prefold_toplevel_comptime(_node_list):
            for _cn in _node_list:
                if isinstance(_cn, ComptimeVarStmt):
                    _cv = self._eval_const(_cn.value)
                    if _cv is not None:
                        self._comptime_vals.setdefault(_cn.target, _cv)
                    if isinstance(_cn.value, ListExpr):
                        self._comptime_list_asts.setdefault(_cn.target, _cn.value)
                elif isinstance(_cn, IfStmt):
                    _prefold_toplevel_comptime(_cn.then_body or [])
                    if _cn.else_body:
                        _prefold_toplevel_comptime(_cn.else_body)
                    for _, _eb in (_cn.elifs or []):
                        _prefold_toplevel_comptime(_eb or [])
                elif isinstance(_cn, (WhileStmt, ForStmt)):
                    _prefold_toplevel_comptime(_cn.body or [])
                elif isinstance(_cn, TryStmt):
                    _prefold_toplevel_comptime(_cn.body or [])
                    for _h in (_cn.handlers or []):
                        _prefold_toplevel_comptime(getattr(_h, 'body', None) or [])
        _prefold_toplevel_comptime(stmts)
        # Bare `from X import <comptime_const>` (BUG-2026-009): a `comptime`
        # constant is normally inlined as a literal VALUE at every use site
        # within its own home module (`_prefold_toplevel_comptime` just
        # above) — a genuinely different strategy from an ordinary runtime
        # `extern` symbol reference (which is what `_emit_imported_global_
        # accessors`, right above, does for a plain `var` global). Crossing
        # a module boundary, the constant's VALUE still needs to become
        # visible here somehow: `mojo dylib`'s per-module-independent
        # compile (driver.compile_dylib -> one GimpleGen per file, no
        # shared state) means this module's own `_comptime_vals` prefold
        # above only ever sees ITS OWN top-level statements, never module
        # X's — so `MAX_N` used directly (`Int64(MAX_N)`) previously fell
        # through `_lower_IdentExpr` all the way to the "unknown identifier"
        # placeholder and silently read 0.
        #
        # Reuses `_parsed_import` — the same source-resolution/parse-cache
        # this file already uses to resolve a sibling/stdlib module's
        # source text for OTHER purposes (comptime function calls via
        # `_imported_fn_sources`, the fixed-size-array `[Elem; N]`
        # annotation's `_module_const_int`) — and the identical recursive
        # `_prefold_toplevel_comptime` walk, just pointed at the imported
        # module's own top-level statements instead of this module's own.
        # Only DIRECT (this module's own top-level `from X import ...`)
        # imports are resolved — matches `_module_const_int`'s own scope,
        # not a full transitive closure.
        for _fis in stmts:
            if not isinstance(_fis, FromImportStmt):
                continue
            try:
                _imp_path, _imp_src, _imp_stmts = self._parsed_import(_fis.module)
            except Exception:
                continue
            if not _imp_stmts:
                continue
            for _iname, _ialias in _fis.names:
                _isym = _ialias if _ialias else _iname
                if _isym in self._comptime_vals:
                    continue   # a same-named local binding always wins
                _found = {}
                def _find_one(_node_list, _target=_iname, _out=_found):
                    if _out:
                        return
                    for _cn in _node_list:
                        if isinstance(_cn, ComptimeVarStmt) and _cn.target == _target:
                            _cv = self._eval_const(_cn.value)
                            if _cv is not None:
                                _out['v'] = _cv
                            return
                        elif isinstance(_cn, IfStmt):
                            _find_one(_cn.then_body or [], _target, _out)
                            if _cn.else_body:
                                _find_one(_cn.else_body, _target, _out)
                            for _, _eb in (_cn.elifs or []):
                                _find_one(_eb or [], _target, _out)
                        elif isinstance(_cn, (WhileStmt, ForStmt)):
                            _find_one(_cn.body or [], _target, _out)
                        elif isinstance(_cn, TryStmt):
                            _find_one(_cn.body or [], _target, _out)
                            for _h in (_cn.handlers or []):
                                _find_one(getattr(_h, 'body', None) or [], _target, _out)
                _find_one(_imp_stmts)
                if 'v' in _found:
                    self._comptime_vals[_isym] = _found['v']
        # Per-lexical-scope import tracking: push THIS module's own top-level
        # scope (frame 0) before any import scan or body generation runs.
        # _emit_stdlib_import_externs / _register_link_imports populate it from
        # this module's own top-level `from X import ...` statements; each
        # function/method body pushes its own frame on top (see gen_func /
        # _gen_struct_method / _gen_lifted_closure). Not popped on the
        # exception path: a raise abandons the whole compile and this
        # instance, so there is nothing to leak.
        self._import_scope_stack.append({})
        # Generator functions (`yield`/`yield from` anywhere in a function's
        # own body — mojo_compiler.py's parser sets FunctionDef.is_generator
        # during parsing) and async functions (`async def` — sets
        # FunctionDef.is_async) cannot be lowered to a single straight-line C
        # function the way this codegen represents every other function:
        # generators need an explicit suspend/resume state-machine transform
        # and async functions need an event loop / suspend-resume codegen,
        # neither of which exists yet (see
        # bugs/INTERP_generator_yield_entirely_unimplemented.md — generator
        # codegen and async codegen are both later milestones than the
        # parser-only ones that introduced these flags). A function CAN be
        # both (`async def f(): yield x`, a real "async generator") — that's
        # reported as its own combined category below rather than tripping
        # both the generator and async raises separately (only the first
        # raise encountered would ever be seen by a caller). Detect every
        # such FunctionDef anywhere in this module (top-level, nested inside
        # if/elif/else branches, struct/class methods, or nested defs) via
        # `_walk_ast`'s generic traversal — reused rather than a hand-rolled
        # walk, matching this file's own established "don't duplicate a
        # tree-walk" convention (see `_walk_ast`'s own docstring). The actual
        # eligibility/compile attempt (and the raise covering whichever
        # categories remain unsupported) is deferred to further below, AFTER
        # the module-wide parameter-type inference passes (in particular
        # Pass 1.3d's cross-call scalar contract) have run — see the comment
        # at that later site for why: an UNANNOTATED generator parameter
        # needs that same inference an ordinary function's unannotated
        # parameter already gets, and doing this here (before those passes
        # exist) silently defaulted such a parameter to int64_t instead of
        # honestly refusing it. Every caller of gen_module
        # (_compile_imported_module, build_stdlib_dylib.py's per-module
        # compile job, compile_stdlib.py, mojo.py's build_executable) already
        # treats an exception raised from codegen (at any point during it) as
        # "this module/file can't be compiled natively" and falls back to
        # interpreting it from source instead of emitting silently wrong or
        # broken C, so raising later than the earliest possible point is a
        # pure (harmless) perf trade-off, not a correctness one — each
        # gen_module call runs against its own freshly-constructed GimpleGen
        # instance (see this method's callers), so there is nothing to leak
        # into a later compile even if this one is ultimately refused after
        # partially populating this instance's tables.
        # Keyed by id(FunctionDef), NOT by name: a bare-name set (the shape
        # this used prior to Milestone C step 3, generator METHODS) is only
        # safe when every generator/async function in the module has a
        # name unique across the WHOLE tree — true for top-level functions
        # (already deduped by the `_overloaded` filter above... in practice,
        # by the time struct methods entered scope for real support, no
        # longer reliably true: two different structs may each define a
        # same-named generator method (`def __iter__(self): yield ...`),
        # one shape-supported and one not, or a struct method may simply
        # share a name with an unrelated top-level generator function. A
        # bare-name discard (`_generator_names.discard(s.name)`) in that
        # situation would incorrectly mark the OTHER, still-unsupported,
        # same-named function/method as resolved, silently skipping the
        # honest whole-module refusal it still needs. Identity-based keys
        # make this collision structurally impossible; display names are
        # derived from the FunctionDef objects only at the very end, for
        # the error message.
        _generator_fns: dict[int, FunctionDef] = {}
        _async_fns: dict[int, FunctionDef] = {}
        for n in _walk_ast(stmts):
            if isinstance(n, FunctionDef):
                if n.is_generator: _generator_fns[id(n)] = n
                if n.is_async: _async_fns[id(n)] = n
        # Every generator function NAME anywhere in this module, computed
        # ONCE here before the compile-attempt passes below start `.pop()`-
        # ing entries out of `_generator_fns` as they succeed — kept for
        # this GimpleGen instance's whole lifetime (unlike `_generator_fns`,
        # a purely-local dict) so `_cpp_for_generator_delegate`'s caller
        # (`_cpp_for_stmt`) can tell "this callee IS a generator in this
        # module, just not compiled yet (wrong source order for THIS pass)"
        # apart from "this callee was never a generator at all" even AFTER
        # the callee's own entry has already been popped/registered or is
        # still pending in a later pass. Without this, a `for x in g():`
        # loop whose callee `g` happens to be defined LATER in the module
        # (dis.py's `_get_instructions_bytes` calling `_unpack_opargs`,
        # defined ~180 lines below it) would see `g` missing from
        # `self._generator_api` on pass 1, silently fall through to the
        # generic (non-generator-aware) iterable lowering below, and emit
        # invalid C++ instead of raising `_UnsupportedGeneratorShape` — the
        # one signal that gets THIS caller retried once `g` has actually
        # been compiled, in pass 2/3/4, exactly like `_cpp_yield_from`'s own
        # identical source-order dependency already relies on.
        self._all_generator_names: set = {n.name for n in _generator_fns.values()}
        # Step I (create_task/Task/TaskGroup/RaisingTask project): every
        # async function NAME anywhere in this module (top-level or
        # nested), regardless of whether it ends up eligible/compiled —
        # lets create_task/create_raising_task's call-site lowering in
        # _lower_call tell "this genuinely names some async def in this
        # module, just one our narrow codegen couldn't compile" (a real,
        # documented, narrow degrade — see that call site's own docstring)
        # apart from "this name doesn't exist / isn't async at all" (still
        # an honest hard refusal, unchanged) when the inner call doesn't
        # resolve in self._async_api.
        self._all_async_fn_names: set[str] = {n.name for n in _async_fns.values()}

        # Structs DECLARED IN THIS FILE's own top-level stmts (as opposed to
        # imported, or referenced but never actually resolved as local or
        # imported) — the only names _struct_method_qualifier may safely
        # apply self.module_name to. See that method's docstring: a struct
        # name this compile can't place in EITHER _imported_struct_home NOR
        # here must fall back to the bare/unqualified form, not guess that
        # it belongs to the module currently being compiled — confirmed
        # regression otherwise (a cross-module call to an imported struct
        # that _register_imported_structs' narrow parameter-type-annotation
        # gate never registered, e.g. StridedSlice/TString/ContiguousSlice
        # used only via untyped locals, got glued with THIS file's own
        # module qualifier instead of either its real home module's or no
        # qualifier at all).
        # Rename any struct/class named after a C keyword (`auto`, ...) to a
        # C-safe name BEFORE anything reads sd.name — so registration, typedef
        # emission, method symbols, alloc, etc. all use the safe name uniformly
        # (the logical name IS the safe name from here on, avoiding the
        # emit-vs-bookkeeping split that made a pure emission-site patch
        # unworkable). Mutates sd.name in place and records the mapping in the
        # shared _c_kw_struct_renames; reference sites (constructor calls, type
        # annotations) map through it at lookup time. Idempotent: a safe name
        # like `_kw_auto` isn't a keyword, so re-running is a no-op.
        for _s in stmts:
            if isinstance(_s, StructDef) and _s.name in _C_KEYWORDS:
                _safe = f'_kw_{_s.name}'
                self._c_kw_struct_renames[_s.name] = _safe
                _s.name = _safe
        self._local_struct_names = {s.name for s in stmts if isinstance(s, StructDef)}
        # Overloaded top-level functions (same name, multiple defs) can't be
        # emitted as distinct C symbols. Drop them here — the elaborator selects
        # and instantiates the right overload per call site (slice 4). One filter
        # at the top keeps every downstream loop collision-free. No-op otherwise.
        _fn_counts = {}
        for _s in stmts:
            if isinstance(_s, FunctionDef):
                _fn_counts[_s.name] = _fn_counts.get(_s.name, 0) + 1
        _overloaded = {n for n, c in _fn_counts.items() if c > 1}
        if _overloaded:
            stmts = [s for s in stmts
                     if not (isinstance(s, FunctionDef) and s.name in _overloaded)]

        # `try: from X import Y / except ImportError: from Z import Y`
        # (or a bare `def NAME(): ...` fallback shape) — the standard
        # CPython compatibility idiom for "try the modern/preferred name,
        # fall back to an older/alternate one on ImportError", both
        # branches binding the SAME local name. Unlike the IfStmt
        # platform-conditional case just below (which already flattens
        # to one branch), NOTHING resolves a top-level TryStmt's
        # try/except branches down to one — both get scanned/compiled,
        # producing two conflicting C definitions for the same symbol
        # ("redefinition of X"), or — when one branch's def/import never
        # gets its own real definition emitted — a silently-wrong
        # "unavailable in compiled mode" stub instead. This compiler
        # doesn't implement real exception-based control flow at the
        # type-checking/codegen level (whether the try branch's import
        # actually succeeds depends on the target platform's real
        # availability, unlike an `if sys.platform == ...:` check this
        # compiler CAN resolve), so — mirroring how the `if` case below
        # picks one branch with a fixed heuristic when the condition
        # isn't staticaly resolvable — the correct behavior for THIS
        # specific idiom is "prefer the try branch, drop the except
        # branch(es)" for the purpose of choosing which definition of a
        # shared name to emit. Deliberately conservative in TWO ways:
        # (a) the trigger only looks at FromImportStmt/ImportStmt/
        # FunctionDef bindings — the shapes that actually emit a real
        # C-level symbol DEFINITION that can collide — NOT plain
        # AssignStmt/MultiAssignStmt/VarDecl. An ordinary
        # `try: result = f() \n except: result = fallback` shares the
        # variable name `result` across both branches, but that's
        # everyday defensive error-handling, not the redefinition bug
        # this fix targets; treating a shared assignment target as
        # grounds to silently drop the except branch's actual fallback
        # logic would be a real behavior regression for that (far more
        # common) idiom. (b) even when triggered, an ordinary try/except
        # doing genuinely different, non-overlapping things in each
        # branch is left completely untouched. See
        # bugs/hard/CODEGEN_try_except_import_fallback_both_branches_
        # compiled.md.
        def _toplev_bound_names(_tb_body):
            _names = set()
            for _tb_s in (_tb_body or []):
                if isinstance(_tb_s, FromImportStmt):
                    for _tb_nm, _tb_alias in (_tb_s.names or []):
                        _names.add(_tb_alias if _tb_alias else _tb_nm)
                elif isinstance(_tb_s, ImportStmt):
                    for _tb_mod, _tb_alias in _import_targets(_tb_s):
                        _names.add(_tb_alias if _tb_alias else _tb_mod.split('.')[0])
                elif isinstance(_tb_s, FunctionDef):
                    _names.add(_tb_s.name)
            return _names

        _try_replaced: list = []
        for _s in stmts:
            if isinstance(_s, TryStmt):
                _try_names = _toplev_bound_names(_s.body)
                _handler_names: set = set()
                for _h in (_s.handlers or []):
                    _handler_names |= _toplev_bound_names(_h.body)
                if _try_names and (_try_names & _handler_names):
                    # Same-name-rebinding fallback idiom confirmed: keep
                    # only the try branch's own statements (dropping the
                    # except handler(s), else_body, and finally_body
                    # entirely for codegen purposes — matches the
                    # IfStmt case's "drop the branch container" comment
                    # just below), so every later pass (Phase 1.7, the
                    # closure/def scan, actual statement emission) sees
                    # ordinary top-level statements instead of a TryStmt
                    # it has no special handling for.
                    _try_replaced.extend(_s.body or [])
                else:
                    _try_replaced.append(_s)
            else:
                _try_replaced.append(_s)
        stmts = _try_replaced

        # Two (or more) top-level `def NAME(...):` statements with the SAME
        # name, nested in mutually-exclusive `if`/`elif`/`else` branches at
        # module scope (a common platform-conditional idiom — e.g.
        # `if sys.platform == 'win32': def wait(...): ...` /
        # `else: def wait(...): ...`, as seen for real in
        # multiprocessing/connection.py) cannot be compiled as distinct C
        # functions: both bodies would want the same unmangled top-level
        # symbol. Worse, unlike the plain-top-level `_overloaded` case just
        # above, nested-in-conditional defs are not even recognized as
        # ordinary top-level functions anywhere else in this pass (the
        # module-level closure scan a few hundred lines down only walks
        # *direct* top-level FunctionDef entries in `stmts`, never into
        # IfStmt branches) — so they silently fall through as unregistered
        # "closures", emit no body at all, and leave call sites to guess an
        # extern declaration for the bare name. That previously surfaced as a
        # confusing conflict with an unrelated same-named libc symbol (e.g.
        # `wait` vs. <sys/wait.h>'s `pid_t wait(int *)`) instead of an honest
        # diagnostic pointing at the real problem.
        #
        # Detect the shape here and fail this module's compile clearly and
        # immediately. Every caller of gen_module (_compile_imported_module,
        # build_stdlib_dylib.py's per-module compile job, compile_stdlib.py,
        # and mojo.py's own build_executable) already treats an exception
        # raised from codegen as "this module/file can't be compiled natively"
        # and reacts accordingly — an import falls back to being resolved via
        # dylib/extern/interpreted-source instead of inlined C, and a directly
        # built file gets a clear compiler error — both are honest outcomes,
        # unlike silently emitting broken code or guessing which branch's
        # definition should win.
        # Iterative worklist, not a self-recursive nested helper: a nested
        # function calling itself does not survive self-host closure-lifting
        # (see _register_imported_structs's _collect, a few hundred lines
        # up, for the same gotcha spelled out in full) — this exact shape
        # broke `make check-selfhost` (undefined symbol
        # `__collect_conditional_toplevel_defs`) the first time this was
        # written as `def _collect_conditional_toplevel_defs(...): ...
        # _collect_conditional_toplevel_defs(...)`.
        #
        # Pre-fold simple top-level constant assignments (e.g. `_MS_WINDOWS
        # = (sys.platform == 'win32')`) into self._comptime_vals, the same
        # dict real `comptime NAME = value` declarations populate — an
        # ordinary module-level assignment whose RHS is itself compile-time
        # foldable (now that _eval_const understands `sys.platform`) is
        # semantically the same kind of constant for the platform-
        # conditional-toplevel-def idiom below, which needs to resolve
        # `if _MS_WINDOWS:`-style bare-name conditions, not just direct
        # `if sys.platform == 'win32':` ones. `setdefault` only, matching
        # the existing pre-fold pattern elsewhere in this file — never
        # overwrites a genuine comptime declaration.
        for _tls in stmts:
            if (isinstance(_tls, AssignStmt) and isinstance(_tls.target, IdentExpr)):
                _tlv = self._eval_const(_tls.value)
                if _tlv is not None:
                    self._comptime_vals.setdefault(_tls.target.name, _tlv)
        _cond_fn_counts: dict = {}
        _cond_worklist = [s for s in stmts if isinstance(s, IfStmt)]
        while _cond_worklist:
            _wi = _cond_worklist.pop()
            for _s in (_wi.then_body or []):
                if isinstance(_s, FunctionDef):
                    _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
                elif isinstance(_s, IfStmt):
                    _cond_worklist.append(_s)
            for _cond, _elif_body in (getattr(_wi, 'elifs', None) or []):
                for _s in (_elif_body or []):
                    if isinstance(_s, FunctionDef):
                        _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
                    elif isinstance(_s, IfStmt):
                        _cond_worklist.append(_s)
            if _wi.else_body:
                for _s in _wi.else_body:
                    if isinstance(_s, FunctionDef):
                        _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
                    elif isinstance(_s, IfStmt):
                        _cond_worklist.append(_s)
        # TODO(real fix, not this approximation): the promotion below
        # handles BOTH the same-name collision case AND the single,
        # non-duplicated `def` nested in a module-scope if/elif/else
        # (bugs/CODEGEN_conditional_toplevel_def_never_compiled.md), by
        # hoisting the first-branch def into a real top-level FunctionDef so
        # it flows through the same pre-pass structures (closure scan, gen_
        # func loop) a direct top-level def goes through. What it does NOT
        # yet do — the durable fix's remaining half — is represent the
        # branch-selectivity faithfully for COLLIDING names:
        #   1. Give same-named defs from sibling branches distinct mangled C
        #      symbols (e.g. suffix by branch index), rather than the single
        #      unmangled name every direct top-level def gets.
        #   2. Make each call site to that name dispatch at runtime between
        #      the mangled per-branch symbols, re-evaluating the same
        #      condition the def was originally guarded by (or, if the
        #      guarding condition is one this compiler can already resolve
        #      statically — e.g. a literal `sys.platform` check, if that's
        #      special-cased anywhere else already — pick the matching
        #      branch's mangled symbol directly at compile time instead of
        #      emitting a runtime check).
        # Until that exists, first-branch-wins (matching CPython semantics
        # for the branch that RUNS) is the honest approximation, not the
        # complete one.
        _cond_collisions = {n for n, c in _cond_fn_counts.items() if c > 1}
        # A SINGLE, non-duplicated `def` nested in a module-scope
        # if/elif/else is JUST as invisible to the pre-passes below (which
        # only walk direct top-level FunctionDef entries in `stmts`, never
        # IfStmt branches) as a collision-pair is — it would silently fall
        # through to _gen_stmt_FunctionDef's closure path with no pre-pass
        # ClosureInfo, emit no body, and leave every call site with a
        # dangling extern that fails at LINK time (the `if sys.platform ==
        # 'darwin': def greet(): ...` + `print(greet())` repro in
        # bugs/CODEGEN_conditional_toplevel_def_never_compiled.md). Promote
        # it to a real top-level statement exactly like the collision case
        # above, first-branch-wins. Guard: never promote a name that ALSO
        # has a direct top-level `def` in this module — hoisting it would
        # create exactly the same-name C-symbol clash the collision case
        # exists to catch (such a def stays exactly as broken as it was
        # before, no regression).
        _direct_toplevel_names = {s.name for s in stmts if isinstance(s, FunctionDef)}
        _cond_unique = {n for n, c in _cond_fn_counts.items()
                        if c == 1 and n not in _direct_toplevel_names}
        _promote_names = _cond_collisions | _cond_unique
        if _promote_names:
            # Platform-conditional def idiom (same fn name in if/elif/else
            # branches, or a single conditionally-defined helper). This
            # compiler targets CPython semantics, so the FIRST branch's
            # definition is the correct one — promote it to a real top-level
            # function and discard the branch container (the other branches'
            # same-named defs would otherwise collide). A top-level IfStmt
            # whose branches contain no def to promote is left untouched —
            # it's ordinary conditional top-level code, not a definition.
            # Iterative explicit-stack traversal (first-occurrence defs
            # across then/elif/else branches in execution order, recursing
            # into NESTED IfStmts the same way the counting worklist above
            # does — the two share one root cause: defs inside module-scope
            # conditionals), NOT a self-recursive nested helper: a nested
            # function calling itself does not survive self-host closure-
            # lifting (same constraint the counting worklist above documents
            # in full).
            _already_promoted_names: set = set()
            _replaced: list = []
            for _s in stmts:
                if not isinstance(_s, IfStmt):
                    _replaced.append(_s)
                    continue
                _promoted: list = []
                _seen_names: set = set()
                _stack: list = [([_s], 0)]
                while _stack:
                    _frame_body, _frame_idx = _stack[-1]
                    if _frame_idx >= len(_frame_body):
                        _stack.pop()
                        continue
                    _frame_stmt = _frame_body[_frame_idx]
                    _stack[-1] = (_frame_body, _frame_idx + 1)
                    if isinstance(_frame_stmt, FunctionDef):
                        if (_frame_stmt.name in _promote_names
                                and _frame_stmt.name not in _seen_names
                                and _frame_stmt.name not in _already_promoted_names):
                            _promoted.append(_frame_stmt)
                            _seen_names.add(_frame_stmt.name)
                            _already_promoted_names.add(_frame_stmt.name)
                    elif isinstance(_frame_stmt, IfStmt):
                        # If this IfStmt's own condition (and each elif's,
                        # in order) is compile-time-resolvable (e.g. `if
                        # sys.platform == 'win32':` — see _eval_const's
                        # `sys.platform` case), use ONLY the single branch
                        # CPython would actually execute on this host,
                        # instead of blindly concatenating every branch and
                        # letting first-occurrence-in-source-order win
                        # regardless of truth value. Without this, `if
                        # _MS_WINDOWS: def f(): ...(Windows body)... else:
                        # def f(): ...(POSIX body)...` always promoted the
                        # Windows body even when _MS_WINDOWS folds to False
                        # on this (non-Windows) host — a silent WRONG-
                        # runtime-behavior bug, not just a missed-compile
                        # one. Falls back to the old "concatenate every
                        # branch" behavior unchanged whenever the condition
                        # isn't foldable, so non-constant conditionals are
                        # unaffected. See bugs/COMPILE_FAIL_importlib__
                        # bootstrap_external.md.
                        _resolved = False
                        _resolved_body = []
                        _cond_val = self._eval_const_bool(_frame_stmt.condition)
                        if _cond_val is True:
                            _resolved = True
                            _resolved_body = _frame_stmt.then_body or []
                        elif _cond_val is False:
                            _resolved = True
                            for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                                _elif_val = self._eval_const_bool(_cond2)
                                if _elif_val is True:
                                    _resolved_body = _elif_body2 or []
                                    break
                                if _elif_val is None:
                                    _resolved = False  # an unresolvable elif — fall back below
                                    break
                            else:
                                _resolved_body = _frame_stmt.else_body or []
                        if _resolved:
                            _nested_body = _resolved_body
                        else:
                            _nested_body = (_frame_stmt.then_body or [])
                            for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                                _nested_body = _nested_body + _elif_body2
                            if _frame_stmt.else_body:
                                _nested_body = _nested_body + _frame_stmt.else_body
                        _stack.append((_nested_body, 0))
                if _promoted:
                    _replaced.extend(_promoted)
                    # Drop the branch container entirely (its non-promoted
                    # defs and other statements are not the platform-correct
                    # ones — mirroring the collision path above)
                else:
                    _replaced.append(_s)
            stmts = _replaced

        # Local generic free functions: the parser drops the `[T]` type params, so
        # detect them from the source text. Register each (with this module's own
        # source) so call sites elaborate a concrete CAS-cached instantiation
        # (id[Int64] → id_Int64), and drop the erased template so it is neither
        # emitted as a type-erased body nor collides across modules.
        _gsrc = ''
        if getattr(self, '_current_filename', None):
            try:
                _gsrc = open(self._current_filename).read()
            except Exception:
                _debug_note('cannot read source for generics scan', self._current_filename)
                _gsrc = ''
        if _gsrc:
            _local_generics = {
                s.name for s in stmts
                if isinstance(s, FunctionDef)
                and s.name not in self._NO_OVERLOAD_MANGLE
                and re.search(rf'\b(?:fn|def)\s+{re.escape(s.name)}\s*\[', _gsrc)
            }
            for _gn in _local_generics:
                self._imported_generics.setdefault(_gn, self._current_filename)
            if _local_generics:
                _stripped_generic_fns = [s for s in stmts
                                          if isinstance(s, FunctionDef) and s.name in _local_generics]
                stmts = [s for s in stmts
                         if not (isinstance(s, FunctionDef) and s.name in _local_generics)]
                # A nested async/generator def inside a stripped local
                # generic (test_tracing.mojo's own real shape:
                # `test_tracing_add`/`test_tracing_add_two_of_them` nested
                # inside `def test_tracing[level: TraceLevel, enabled:
                # Bool]()`) was already counted into _async_fns/
                # _generator_fns by the deep `_walk_ast(stmts)` scan a few
                # lines above — which ran BEFORE this strip, over the
                # ORIGINAL (unstripped) `stmts`. Once the outer generic is
                # stripped here, nothing else in THIS module compile will
                # ever attempt (or pop) that nested id — it's only ever
                # compiled inside the SEPARATE, per-call-site elaborated
                # instance `_elaborate_generic_call`/monomorphize.py spins
                # up (its own independent GimpleGen, own independent
                # gen_module run, own independent _async_fns/_generator_fns
                # tally). Left uncleaned, it would ALWAYS show up in this
                # module's own final "still unsupported" error — a real,
                # pre-existing false-positive refusal for ANY module with a
                # local generic function that happens to nest an async/
                # generator def, confirmed via a hand-written repro
                # matching test_tracing.mojo's exact structure.
                for _sgf in _stripped_generic_fns:
                    for _n in _walk_ast(_sgf.body):
                        if isinstance(_n, FunctionDef):
                            _async_fns.pop(id(_n), None)
                            _generator_fns.pop(id(_n), None)

        # Struct methods with a FUNCTION-TYPED comptime bracket parameter that
        # is actually referenced (directly or via a nested closure) — see
        # _method_threaded_comptime_params' docstring / bugs/CODEGEN_
        # device_context_captured_function_parameter_closures_broken.md's
        # Repro 1. Unlike the local-generic-FREE-FUNCTION case above (which
        # elaborates a distinct specialized function per call site via
        # textual substitution), a function-typed comptime parameter carries
        # no compile-time-varying information this codegen's monomorphization
        # needs — it's always just an opaque callable pointer — so it's
        # threaded through as one ordinary trailing C parameter instead
        # (_gen_struct_method appends it; the "obj.method[...]"  call site in
        # _lower_call forwards the bracket argument as an extra positional
        # arg), with NO per-call-site specialization and no change to methods
        # whose comptime bracket parameter is never independently threaded
        # (an Int/Bool/other comptime method parameter, or one that's a pure
        # type-bound never referenced as a plain identifier — e.g. `FuncType:
        # def() -> None` typing an ordinary `func: FuncType` parameter — is
        # completely unaffected, left exactly as before).
        if _gsrc:
            for _s in stmts:
                if not isinstance(_s, StructDef):
                    continue
                # Scope the textual bracket-annotation search to just THIS
                # struct's own source slice (not the whole module) — an
                # occurrence index is only meaningful relative to a single,
                # well-defined search space; scoping to the struct keeps
                # "occurrence N of this method name" unambiguous even if
                # some other struct/free-function elsewhere in the same file
                # happens to reuse the same method name with its own bracket
                # parameters.
                try:
                    import elaborate as _elaborate_mod
                    _struct_src = _elaborate_mod.extract_struct_source(_gsrc, _s.name) or _gsrc
                except Exception:
                    _struct_src = _gsrc
                _moids_pre = self._struct_method_overload_ids(_s)
                _name_occurrence: dict = {}  # method name -> next occurrence index to consume
                for _m, _oid in zip(_s.methods, _moids_pre):
                    _occ = _name_occurrence.get(_m.name, 0)
                    _name_occurrence[_m.name] = _occ + 1
                    if not _m.comptime_params:
                        continue
                    _bp_types = _bracket_param_type_annotations(_struct_src, _m.name, occurrence=_occ)
                    _func_typed = {p for p in _m.comptime_params
                                   if _bp_types.get(p, '').startswith('def')}
                    if not _func_typed:
                        continue
                    _used = set()
                    for _b in _m.body:
                        _used |= _used_idents_deep(_b)
                    _threaded = [p for p in _m.comptime_params if p in _func_typed and p in _used]
                    if _threaded:
                        _key = (_s.name, _m.name)
                        self._method_threaded_comptime_params.setdefault(_key, {})[_oid] = _threaded
                        self._method_comptime_param_order.setdefault(_key, {})[_oid] = list(_m.comptime_params)

        # Structs with a __call__ method: a variable of such a type invoked like a
        # function (obj(args)) routes to Struct___call__(obj, args).
        self._callable_structs = {
            s.name for s in stmts
            if isinstance(s, StructDef) and any(m.name == '__call__' for m in s.methods)
        }

        # Register concrete imported structs used (with field access) as param types.
        self._register_imported_structs(stmts)
        # Register imported generic free functions (via re-export chains) so their
        # calls elaborate a concrete CAS-cached instantiation.
        self._register_imported_generics(stmts)
        # Register imported generic structs (via re-export chains) so
        # Struct[Args](...) calls / nested generic-struct type args elaborate too.
        self._register_imported_generic_structs(stmts)

        # Pre-scan MODULE-LEVEL `comptime NAME = [...]` list constants so
        # `for a, b in materialize[NAME]():` (see _gen_for_iter's special
        # case) has them available no matter which function is compiled
        # first — a top-level ComptimeVarStmt is normally only recorded by
        # _gen_stmt_ComptimeVarStmt when gen_stmt walks over IT, which for a
        # module-level statement happens only as part of the toplevel-code
        # pass; a function whose body is emitted BEFORE that pass runs would
        # otherwise see an empty _comptime_list_asts even though the comptime
        # list is textually declared earlier in the file (real, in stdlib's
        # test_atof.mojo).
        for _s in stmts:
            if isinstance(_s, ComptimeVarStmt) and isinstance(_s.value, ListExpr):
                self._comptime_list_asts.setdefault(_s.target, _s.value)

        # This module's own top-level function names — used by _func_qualifier
        # (SB-1 fix) to tell a genuinely LOCAL definition (qualify with THIS
        # module's own name) apart from a same-bare-name entry that merely got
        # added to self._mangled_funcs because it's an IMPORTED function (must
        # use its actual defining module's qualifier instead — see
        # _imported_func_home). `stmts` is this call's own top-level list, so
        # identity membership here is exactly "declared in this file".
        self._local_top_level_func_names = {
            s.name for s in stmts if isinstance(s, FunctionDef)}

        # Pre-register current module's own function names into _global_inline_defs
        # BEFORE Phase 0 so that recursive sub-module compilations see them.
        for _s in stmts:
            if isinstance(_s, FunctionDef):
                self._global_inline_defs.add(_s.name)
            elif isinstance(_s, StructDef):
                for _m in _s.methods:
                    self._global_inline_defs.add(_m.name)
                    self._global_inline_defs.add(f"{_s.name}_{_m.name}")
                # Struct-level comptime aliases (e.g. BitSet._words_size) expand
                # to their expression at member-access sites, not physical fields.
                _al = getattr(_s, 'comptime_aliases', None)
                if _al:
                    self._struct_comptime_aliases[_s.name] = _al

        # Link mode: register imported symbol signatures (return/param types) from
        # module_loader so call sites lower correctly; decls emitted in preamble.
        # No body inlining — bodies come from the linked artifact (ABI.md).
        self._link_import_decl_list = []
        if self.link_imports:
            self._link_import_decl_list = self._register_link_imports(stmts)

        # Lightweight stdlib import extern pass: scan from-imports and emit extern
        # declarations for concrete functions found via load_module (simple text
        # parser, no dylib builds). This resolves "implicit declaration" errors for
        # functions like `is_occupied` imported from other stdlib modules.
        self._link_import_decl_list = list(self._link_import_decl_list)
        self._emit_stdlib_import_externs(stmts)
        self._emit_imported_global_accessors(stmts)

        # ── Phase 0: Compile imported modules and extract their type info ────
        # Do this FIRST so imported function types are available for everything
        imported_code = []
        imported_stmts = []
        if self.do_imports:
            modules_to_compile = set()
            # Recursively scan for all imports (including in function bodies)
            def find_imports(node_list):
                for stmt in node_list:
                    if isinstance(stmt, FromImportStmt):
                        modules_to_compile.add(stmt.module)
                        # `from PACKAGE import SUBMODULE` (e.g. `from
                        # tkinter import commondialog`) — real Python
                        # resolves the imported NAME as a submodule FILE
                        # (tkinter/commondialog.py), not a name looked up
                        # inside tkinter/__init__.py, so compiling just
                        # `stmt.module` alone never pulls in commondialog's
                        # own struct/function defs (e.g. `Dialog`, whose
                        # methods a same-transitive-closure subclass like
                        # tkinter/filedialog.py's `_Dialog(commondialog.
                        # Dialog)` needs merged in — see bugs/
                        # COMPILE_FAIL_tkinter_filedialog.md). Try each
                        # imported name as a dotted submodule path too, in
                        # addition to the bare module — _compile_imported_
                        # module already resolves dotted names via its own
                        # existing search-path logic, and silently finds
                        # nothing (a no-op) for the overwhelmingly common
                        # case where the imported name is genuinely just a
                        # symbol inside the module rather than a submodule
                        # file.
                        for _fn, _fa in (stmt.names or []):
                            modules_to_compile.add(f"{stmt.module}.{_fn}")
                    elif isinstance(stmt, ImportStmt):
                        for _m, _a in _import_targets(stmt):
                            modules_to_compile.add(_m)
                    elif isinstance(stmt, FunctionDef):
                        find_imports(stmt.body)
                    elif isinstance(stmt, IfStmt):
                        find_imports(stmt.then_body)
                        for _, elif_body in stmt.elifs:
                            find_imports(elif_body)
                        if stmt.else_body:
                            find_imports(stmt.else_body)
                    elif isinstance(stmt, (WhileStmt, ForStmt, TryStmt)):
                        find_imports(stmt.body)

            find_imports(stmts)

            # Compile imported modules to extract type information
            for module_name in sorted(modules_to_compile):
                if module_name not in self._compiled_modules:
                    self._compiled_modules.add(module_name)
                    code, module_stmts = self._compile_imported_module(module_name)
                    if code:
                        imported_code.append(f"/* ─── Imported module: {module_name} ───────────────────── */")
                        imported_code.append(code)
                        imported_code.append('')
                        imported_stmts.extend(module_stmts)
                        # Record all function names defined inline to suppress extern stubs
                        for _ms in module_stmts:
                            if isinstance(_ms, FunctionDef):
                                self._global_inline_defs.add(_ms.name)
                                # SB-1 fix (_func_qualifier): the nested temp_gen
                                # that compiled this function inline used
                                # module_name=module_name as ITS OWN module_name
                                # (see _compile_imported_module below), so any
                                # mangled symbol it emitted for this function was
                                # qualified with that same prefix. Record it here
                                # (mirroring _imported_struct_home just below) so
                                # a call site in this module recomputes the
                                # identical qualified symbol instead of an
                                # unqualified one nothing defines.
                                self._imported_func_home.setdefault(_ms.name, module_name)
                                # _own_imported_func_home (per-instance, NOT
                                # shared across nested temp_gens — see its own
                                # comment): `self` HERE is specifically the
                                # temp_gen that is DOING the importing (its own
                                # find_imports scan is what put module_name into
                                # modules_to_compile), so this registration is
                                # always correct for THIS module's own call
                                # sites and must win over any OTHER importer's
                                # conflicting claim on the same bare name in the
                                # shared _imported_func_home fallback above.
                                # record_scope=False: these are TRANSITIVE
                                # registrations of an inlined dependency
                                # module's OWN top-level functions, NOT this
                                # module's own lexical imports — they must not
                                # pollute this module's scope (a call site's
                                # authoritative binding comes from ITS OWN
                                # `from X import ...` statements, recorded
                                # into the right scope by _gen_stmt_FromImport
                                # Stmt / the body pre-scan).
                                self._note_own_func_home(_ms.name, module_name, record_scope=False)
                            elif isinstance(_ms, StructDef):
                                for _m in _ms.methods:
                                    self._global_inline_defs.add(_m.name)
                                    self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                                # _compile_imported_module's nested temp_gen
                                # compiled with module_name=module_name, so
                                # every one of its own locally-defined
                                # structs' method symbols got qualified with
                                # that prefix. A call site in THIS module (or
                                # a shallower ancestor, imported_struct_home
                                # is shared down the whole nested-temp_gen
                                # chain) on that struct needs to derive the
                                # identical qualified symbol — see
                                # _struct_method_qualifier. Previously
                                # unregistered here: harmless for a direct
                                # (root -> leaf) import, since the struct's
                                # OWN compile pass registers types into the
                                # shared struct_field_types dict either way,
                                # but a 3-level-deep chain (root -> A -> B,
                                # B defines the struct, A merely re-uses it)
                                # left the root's own call sites on that
                                # struct recomputing an unqualified symbol
                                # the defining module never exports under
                                # (BUG-2026-032's arena.mojo/ast_nodes.mojo).
                                self._imported_struct_home.setdefault(_ms.name, module_name)
                    self._compiled_modules.add(module_name)

            # Also collect stmts from transitively compiled modules (compiled by sub-temp-gens).
            # These may not be in imported_stmts if a sub-gen compiled them first (e.g. mojo_compiler
            # compiled via gimple_codegen before the outer gen could compile it directly).
            #
            # PERF (see bugs/hard/PERF_nested_module_compile_walk_ast_
            # quadratic_rescan.md, Phase 1): iterate the incrementally-
            # maintained flat `_all_transitive_stmts_ordered` list instead
            # of re-flattening `self._module_stmts.items()` from scratch —
            # identical final `imported_stmts` content (same dedup-by-id
            # logic, same append order, since `_all_transitive_stmts_
            # ordered` is itself built by walking each module's stmts in
            # the same per-module order `_module_stmts.items()` would visit
            # them, just accumulated once instead of re-derived at every
            # nesting level), but O(this level's own delta) instead of
            # O(current total tree size) — the repeated full re-flattening
            # at every one of N nesting levels is what produced the O(N^2)
            # `_walk_ast` blowup this doc profiles (4.47M calls for a
            # 36-module graph in Lib/contextlib.py).
            already_in_stmts = set(id(s) for s in imported_stmts)
            for s in self._all_transitive_stmts_ordered:
                if id(s) not in already_in_stmts:
                    imported_stmts.append(s)
                    already_in_stmts.add(id(s))

            # Imported types are now in self._imported_func_types and struct_field_types

        # Link mode's fallback for plain structs with no dylib to reflect off
        # of (_register_link_imports, above) records the MODULE name here —
        # compile it for real (body generation, not just field-type
        # registration) the same way do_imports=True's Phase 0 above compiles
        # each transitively-imported module, since there's no dylib to link
        # its methods from. Kept separate from the `if self.do_imports:`
        # block above: that block additionally tries to fully compile+inline
        # EVERY transitively-imported module (Phase 0's find_imports), which
        # would be a large, unwanted behavior change for link mode (defeats
        # per-import dylib caching for every OTHER, dylib-resolvable import
        # in the program) — this only compiles modules that already proved
        # unresolvable any other way.
        if self.link_imports:
            for module_name in sorted(self._link_inline_modules):
                if module_name not in self._compiled_modules:
                    self._compiled_modules.add(module_name)
                    code, module_stmts = self._compile_imported_module(module_name)
                    if code:
                        imported_code.append(f"/* ─── Imported module (link-mode fallback): {module_name} ───────────────────── */")
                        imported_code.append(code)
                        imported_code.append('')
                        imported_stmts.extend(module_stmts)
                        for _ms in module_stmts:
                            if isinstance(_ms, FunctionDef):
                                self._global_inline_defs.add(_ms.name)
                                # SB-1 fix (_func_qualifier): the nested temp_gen
                                # that compiled this function inline used
                                # module_name=module_name as ITS OWN module_name
                                # (see _compile_imported_module below), so any
                                # mangled symbol it emitted for this function was
                                # qualified with that same prefix. Record it here
                                # (mirroring _imported_struct_home just below) so
                                # a call site in this module recomputes the
                                # identical qualified symbol instead of an
                                # unqualified one nothing defines.
                                self._imported_func_home.setdefault(_ms.name, module_name)
                                # _own_imported_func_home (per-instance, NOT
                                # shared across nested temp_gens — see its own
                                # comment): `self` HERE is specifically the
                                # temp_gen that is DOING the importing (its own
                                # find_imports scan is what put module_name into
                                # modules_to_compile), so this registration is
                                # always correct for THIS module's own call
                                # sites and must win over any OTHER importer's
                                # conflicting claim on the same bare name in the
                                # shared _imported_func_home fallback above.
                                # record_scope=False: these are TRANSITIVE
                                # registrations of an inlined dependency
                                # module's OWN top-level functions, NOT this
                                # module's own lexical imports — they must not
                                # pollute this module's scope (a call site's
                                # authoritative binding comes from ITS OWN
                                # `from X import ...` statements, recorded
                                # into the right scope by _gen_stmt_FromImport
                                # Stmt / the body pre-scan).
                                self._note_own_func_home(_ms.name, module_name, record_scope=False)
                            elif isinstance(_ms, StructDef):
                                for _m in _ms.methods:
                                    self._global_inline_defs.add(_m.name)
                                    self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                                # _compile_imported_module's nested temp_gen
                                # compiles with module_name=module_name, so
                                # _struct_method_qualifier qualified every one
                                # of its own locally-defined structs' method
                                # symbols with that same prefix (e.g.
                                # ast_nodes_IfStmt___init__). THIS module's own
                                # call sites on that struct (imported by bare
                                # name, e.g. `from ast_nodes import IfStmt`)
                                # need to derive the identical qualified
                                # symbol — _struct_method_qualifier checks
                                # _imported_struct_home for exactly that.
                                self._imported_struct_home.setdefault(_ms.name, module_name)

        # ── Phase 1: build complete type tables (pre-pass) ────────────────

        # Register struct field types first so _resolve_type works for funcs
        # Include both current module and imported module structs
        # NOTE: do NOT clear struct_field_types here — it was already populated
        # by temp_gens during Phase 0 import compilation.  Clearing it would
        # lose structs from transitive imports (ModuleLoader, Layout, etc.)
        # that were added to the shared dict by nested temp_gens.

        # These hardcoded field/param tables exist for exactly one reason:
        # self-hosting this very compiler. When gimple_codegen.py compiles
        # mojo.py's own transitive closure (mojo_compiler.py, myinterpreter.py,
        # ...), those files' classes are plain Python `class Foo: def
        # __init__(self): self.x = ...` — field-type inference from scanning
        # `__init__` bodies (_collect_self_assigns) sometimes can't recover a
        # field's real type, so these entries are a hand-maintained cheat
        # sheet for THIS repo's own Scope/Token/Parser/Interpreter/MojoClass/
        # CallExpr/BinaryOp/... classes specifically.
        #
        # They must NOT apply to an external project's unrelated same-named
        # struct. A compiler-adjacent Mojo project (a hand-written parser,
        # interpreter, or AST library — exactly the kind of thing someone
        # writes in Mojo) is very likely to define its OWN Parser/Token/
        # Scope/CallExpr/BinaryOp/... with completely different fields, and
        # unconditionally seeding this dict before scanning the real
        # StructDefs let those hardcoded phantom fields leak into that
        # unrelated struct's C typedef, and (worse) the "don't overwrite an
        # already-known field name" guard in the real-struct scan below meant
        # the struct's ACTUAL matching field names were silently ignored too
        # (see BUG-2026-014's fuller repro, test_cp_tree_final.mojo: a
        # same-named `Parser` struct's real `errors: Int` field was invisible
        # at codegen because 'errors' happened not to collide with any
        # hardcoded name, but plenty of OTHER user structs — VarDecl, Parser
        # itself for its other fields — silently got the wrong ones instead).
        #
        # Gate on whether we're compiling one of THIS repo's own files: only
        # then can `s.name` genuinely be gimple_codegen.py's own bootstrap
        # class rather than a coincidentally-same-named third-party struct.
        # Span / StringSlice — fat pointer {data, len}. Seeded so .unsafe_ptr()
        # and .__len__()/len() lower to field reads even without walking
        # span.mojo. Unlike the self-host-only block below, this is a REAL
        # stdlib type used broadly — NOT gated on _is_selfhost_file (an
        # earlier version of this fix wrongly gated it too, which broke
        # every ordinary stdlib compile referencing Span with "unknown type
        # name 'Span'": compile_stdlib.py isn't compiling one of THIS repo's
        # own files, so the gate was always False for it).
        self.struct_field_types['Span'] = {
            '_data': 'char *',
            '_len': 'int64_t',
        }

        _cur_file = getattr(self, '_current_filename', None)
        _cur_abs = os.path.abspath(_cur_file) if _cur_file else ''
        # Self-host detection: the compiled `mojoc` binary is ALWAYS the
        # self-hosted compiler, regardless of which input file it compiles
        # (its `__file__` is the literal "<bootstrap>", so _SELFHOST_DIR
        # resolves to the process CWD — which differs from the input file's
        # dir — and a path-only check would wrongly be False for a user
        # file, skipping the interpreter/AST struct registrations and
        # segfaulting on node.condition etc. Class D of the A/B list).
        # Self-host detection is PATH-BASED only (repo files under
        # _SELFHOST_DIR). The old `_compiled_selfhost` override
        # (__file__ == "<bootstrap>") forced _is_selfhost_file True for EVERY
        # file the compiled binary compiled, so a user file emitted the 26
        # self-host-only struct registrations (Parser/Interpreter/Scope/Token/
        # CallExpr/BinaryOp/... plus the _AutoStub*/_Mojo* helpers) as typedefs
        # in its .ci — an A/B divergence (Python emits only the 53 ungated
        # AST structs for a user file). Path-based detection keeps the gated
        # self-host structs for repo files (byte-identical with Python's own
        # self-host compile) while user files match Python's 53-struct set.
        _is_selfhost_file = bool(_cur_file) and (
            _cur_abs == _SELFHOST_DIR or _cur_abs.startswith(_SELFHOST_DIR + '/'))
        if _is_selfhost_file:
            # Pre-populate known interpreter structs with their field types
            # This handles cases where field type inference from method bodies fails
            self.struct_field_types['Scope'] = {
                'parent': 'Scope *',
                'vars': 'MojoDict *',
            }
            self.struct_field_types['Token'] = {
                'kind':  'char *',
                'value': 'char *',
                'line':  'int64_t',
                'col':   'int64_t',
            }
            self.struct_field_types['ReturnValue'] = {
                'value': 'int64_t',
            }
            self.struct_field_types['BreakException'] = {}
            self.struct_field_types['ContinueException'] = {}
            self.struct_field_types['MojoFunction'] = {
                'name': 'char *',
                'params': 'MojoList *',
                'body': 'MojoList *',
                'closure_scope': 'Scope *',
                'comptime_params': 'MojoList *',
                '_pd': 'MojoList *',
                # Milestone 2 of
                # bugs/INTERP_generator_yield_entirely_unimplemented.md:
                # MojoFunction.is_generator (myinterpreter.py) — mirrors
                # FunctionDef.is_generator, gates MojoFunction._invoke's
                # generator-construction-only vs. eager-execution branch.
                'is_generator': '_Bool',
                # Milestone 3b of
                # bugs/INTERP_generator_yield_entirely_unimplemented.md:
                # MojoFunction.is_async (myinterpreter.py) — mirrors
                # FunctionDef.is_async, gates MojoFunction._invoke's
                # coroutine-construction-only vs. eager-execution branch,
                # same treatment as is_generator immediately above.
                'is_async': '_Bool',
            }
            self.struct_field_types['_MojoSortFn'] = {
                '_impl': 'int64_t',
                '_interpreter': 'Interpreter *',
            }
            self.struct_field_types['_MojoSortPartial'] = {
                '_impl': 'int64_t',
                '_cmp_fn': 'int64_t',
            }
            self.struct_field_types['_ComplexFloat'] = {
                'bits': 'int64_t',
            }
            self.struct_field_types['_MojoComplex'] = {
                '_r': 'double',
                '_i': 'double',
            }
            self.struct_field_types['_AutoStubValue'] = {}
            self.struct_field_types['_AutoStubNamespace'] = {}
            self.struct_field_types['_AutoStubCheckNamespace'] = {}
            self.struct_field_types['_MojoBoundComptimeFunction'] = {
                'func': 'MojoFunction *',
                'comptime_bindings': 'MojoDict *',
            }
            self.struct_field_types['MojoClass'] = {
                'name': 'char *',
                'fields': 'MojoList *',
                'methods': 'MojoDict *',
                'interpreter': 'Interpreter *',
                'bases': 'MojoList *',
                'comptime_aliases': 'MojoDict *',
                'static_methods': 'MojoSet *',
                'def_scope': 'Scope *',
            }
            self.struct_field_types['MojoInstance'] = {
                '_mojo_class': 'MojoClass *',
            }
            self.struct_field_types['BoundMethod'] = {
                'bound_func': 'MojoFunction *',
                'instance': 'MojoInstance *',
                'interpreter': 'Interpreter *',
            }
            self.struct_field_types['MojoOverloadSet'] = {
                'name': 'char *',
                'candidates': 'MojoList *',
            }
            self.struct_field_types['Interpreter'] = {
                'scope': 'Scope *',
                'filename': 'char *',
                'argv': 'MojoList *',
                '_mojo_module_cache': 'MojoDict *',
                '_func_specs': 'MojoDict *',
                '_raised_mojo_value': 'int64_t',
                # `_INT_TYPE_NAMES`/`_FLOAT_TYPE_NAMES` are class-level `set`
                # literals on Interpreter (myinterpreter.py, used by
                # `_coerce_to_declared_type`) — plain Python class attributes
                # with no `var` declaration, so like Parser._known_traits
                # below they need an explicit entry here or codegen silently
                # infers 'int' and self-host miscompiles.
                '_INT_TYPE_NAMES': 'MojoSet *',
                '_FLOAT_TYPE_NAMES': 'MojoSet *',
                # Milestone 2 of
                # bugs/INTERP_generator_yield_entirely_unimplemented.md:
                # Interpreter._gen_tls (myinterpreter.py, a
                # `threading.local()`) — per-OS-thread storage for the
                # currently-running Mojo generator's `yield_fn`. Opaque to
                # the compiled path (only ever getattr/setattr'd, never
                # itself Mojo-observable), same treatment as 'object'/'Any'
                # elsewhere in this file.
                '_gen_tls': 'void *',
            }
            self.struct_field_types['Parser'] = {
                '_tok': 'MojoList *',
                '_pos': 'int64_t',
                '_filename': 'char *',
                '_pending_decs': 'MojoList *',
                # `set(_BUILTIN_TRAITS)` in Parser.__init__ (mojo_compiler.py)
                # — a plain Python class field, no `var` declaration for the
                # self-host type inferencer to consult, so an unlisted field
                # here silently fell back to "assume it's a pointer to the
                # containing struct" (Parser *), corrupting `x not in
                # self._known_traits` under self-hosting. See the "self-host
                # hardcoded struct tables" memory note: any new field added to
                # a self-hosted Python class needs a matching entry here.
                '_known_traits': 'MojoSet *',
                # `_CONV_KWS` is a class-level `set` literal (mojo_compiler.py,
                # used by the `ref`/`out`/`mut`/... soft-keyword handling in
                # _parse_for/_parse_funcdef/_parse_primary) — same class-field
                # gap as `_known_traits` above.
                '_CONV_KWS': 'MojoSet *',
            }
            self.struct_field_types['Scope'] = {
                'parent': 'Scope *',
                'vars': 'MojoDict *',
            }

            # Hardcode Scope method param types so 'name' is char* not int
            self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
            self.func_param_types['Scope_get']    = ['Scope *', 'char *']
            self.func_param_types['Scope_set']    = ['Scope *', 'char *', 'int']
            self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']
            # Lock these four against Pass 1.3c's later unconditional
            # overwrite -- see `_selfhost_locked_param_types`'s own comment
            # (__init__) for why this is necessary, not just defensive.
            self._selfhost_locked_param_types.update((
                'Scope_define', 'Scope_get', 'Scope_set', 'Scope___init__',
            ))
            # `MojoFunction.__call__(self, interpreter, *args, **kwargs)`:
            # register its kwargs slot so `_repack_method_call_spread_args`
            # (see that method's own docstring) can fix up
            # `BoundMethod.__call__`'s `f(self.interpreter, self.instance,
            # *args, **kwargs)` -- a mixed fixed-arg + spread call into this
            # exact signature shape, previously mis-packed (arity mismatch
            # against the real 4-param C signature). Index 3: self=0,
            # interpreter=1, args(vararg, one MojoList* slot)=2, kwargs=3.
            self._func_kwargs_slot['MojoFunction___call__'] = 3
            self._func_kwargs_has_vararg['MojoFunction___call__'] = True

            # Pre-populate AST node struct fields
            self.struct_field_types['CallExpr'] = {
                'func': 'int64_t',
                'args': 'MojoList *',
            }
            self.struct_field_types['BinaryOp'] = {
                'op': 'char *',
                'left': 'int64_t',
                'right': 'int64_t',
            }
            self.struct_field_types['CompareChain'] = {
                'operands': 'MojoList *',
                'ops': 'MojoList *',
            }
            self.struct_field_types['UnaryOp'] = {
                'op': 'char *',
                'operand': 'int64_t',
            }
            self.struct_field_types['TernaryExpr'] = {
                'condition': 'int64_t',
                'then_val': 'int64_t',
                'else_val': 'int64_t',
            }
            self.struct_field_types['MemberExpr'] = {
                'obj': 'int64_t',
                'member': 'char *',
            }
            self.struct_field_types['SubscriptExpr'] = {
                'obj': 'int64_t',
                'index': 'int64_t',
            }
            # These hardcoded fields are boxed (Optional/Any-typed AST-node refs
            # stored as int64_t) same as the annotation-scan-derived ones below —
            # pre-populated here so they bypass that scan (see the `if f_name not
            # in self.struct_field_types[s.name]` guard), so their boxed-ness must
            # be recorded explicitly too or repr() prints raw pointers for them.
            self.struct_boxed_fields['CallExpr'] = {'func'}
            self.struct_boxed_fields['BinaryOp'] = {'left', 'right'}
            self.struct_boxed_fields['UnaryOp'] = {'operand'}
            self.struct_boxed_fields['TernaryExpr'] = {'condition', 'then_val', 'else_val'}
            self.struct_boxed_fields['MemberExpr'] = {'obj'}
        self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}
        # Literal/collection node boxed fields: the `value` of a child
        # expression node is an int64_t handle to a nested AST node, not a
        # raw integer (e.g. WalrusExpr.value, YieldExpr.value, AwaitExpr.value).
        self.struct_boxed_fields['WalrusExpr'] = {'value'}
        self.struct_boxed_fields['YieldExpr'] = {'value'}
        self.struct_boxed_fields['YieldFromExpr'] = {'value'}
        self.struct_boxed_fields['AwaitExpr'] = {'value'}

        # ── AST statement/expression node fields (ALWAYS-ON, not gated) ──────
        # The compiled `mojoc` binary reads AST-node fields off the parser's
        # runtime objects (node.then_body, node.condition, node.body, ...) via
        # struct_field_types-driven member lowering. Those reads happen for ANY
        # input file, not just this repo's own self-host files — but
        # `_is_selfhost_file` is False for a plain user file, so the block above
        # (which registers only the 7 expression nodes CallExpr/BinaryOp/...)
        # would be skipped and every statement-node field access would fall back
        # to mojo_obj_getattr returning 0/NULL → garbage → segfault (the
        # if_else.mojo `mojo_str_join(parts=NULL)` crash). Register them here,
        # unconditionally, with the same C types the dataclass annotation-scan
        # below derives (object→int64_t boxed, str→char *, list→MojoList *,
        # dict→MojoDict *, bool→_Bool) so the baked struct layout matches.
        self.struct_field_types['IfStmt'] = {
            'condition': 'int64_t',
            'then_body': 'MojoList *',
            'elifs': 'MojoList *',
            'else_body': 'MojoList *',
        }
        self.struct_field_types['WhileStmt'] = {
            'condition': 'int64_t',
            'body': 'MojoList *',
            'else_body': 'MojoList *',
        }
        self.struct_field_types['ForStmt'] = {
            'target': 'int64_t',
            'iterable': 'int64_t',
            'body': 'MojoList *',
            'else_body': 'MojoList *',
            'is_async': '_Bool',
        }
        self.struct_field_types['FunctionDef'] = {
            'name': 'char *',
            'params': 'MojoList *',
            'return_type': 'int64_t',
            'body': 'MojoList *',
            'decorators': 'MojoList *',
            'param_convs': 'MojoDict *',
            'param_has_default': 'MojoDict *',
            'param_defaults': 'MojoDict *',
            'kwonly': 'MojoList *',
            'comptime_params': 'MojoList *',
            'is_generator': '_Bool',
            'yield_bearing_node_ids': 'int64_t',
            'is_async': '_Bool',
        }
        self.struct_field_types['ExprStmt'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['AssignStmt'] = {
            'target': 'int64_t',
            'value': 'int64_t',
            'line': 'int64_t',
            'col': 'int64_t',
            'type_ann': 'int64_t',
        }
        self.struct_field_types['AugAssignStmt'] = {
            'target': 'int64_t',
            'op': 'char *',
            'value': 'int64_t',
        }
        self.struct_field_types['ReturnStmt'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['VarDecl'] = {
            'name': 'char *',
            'type_ann': 'int64_t',
            'value': 'int64_t',
        }
        self.struct_field_types['MultiAssignStmt'] = {
            'targets': 'MojoList *',
            'value': 'int64_t',
        }
        self.struct_field_types['BreakStmt'] = {}
        self.struct_field_types['ContinueStmt'] = {}
        self.struct_field_types['PassStmt'] = {}
        self.struct_field_types['AssertStmt'] = {
            'value': 'int64_t',
            'msg': 'int64_t',
            'is_comptime': '_Bool',
        }
        self.struct_field_types['RaiseStmt'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['TryStmt'] = {
            'body': 'MojoList *',
            'handlers': 'MojoList *',
            'else_body': 'MojoList *',
            'finally_body': 'MojoList *',
        }
        self.struct_field_types['WithStmt'] = {
            'items': 'MojoList *',
            'body': 'MojoList *',
            'is_async': '_Bool',
        }
        self.struct_field_types['ImportStmt'] = {
            'module': 'char *',
            'alias': 'char *',
            'extra': 'MojoList *',
        }
        self.struct_field_types['FromImportStmt'] = {
            'module': 'char *',
            'names': 'MojoList *',
            'wildcard': '_Bool',
        }
        self.struct_field_types['ComptimeIfStmt'] = {
            'condition': 'int64_t',
            'then_body': 'MojoList *',
            'elifs': 'MojoList *',
            'else_body': 'MojoList *',
        }
        self.struct_field_types['ComptimeForStmt'] = {
            'target': 'char *',
            'iterable': 'int64_t',
            'body': 'MojoList *',
        }
        self.struct_field_types['ComptimeVarStmt'] = {
            'target': 'char *',
            'value': 'int64_t',
        }
        self.struct_field_types['GlobalStmt'] = {
            'names': 'MojoList *',
        }
        self.struct_field_types['DelStmt'] = {
            'targets': 'MojoList *',
        }
        self.struct_field_types['MatchStmt'] = {
            'subject': 'int64_t',
            'cases': 'MojoList *',
        }
        self.struct_field_types['LambdaExpr'] = {
            'params': 'MojoList *',
            'body': 'int64_t',
        }
        self.struct_field_types['SubscriptExpr'] = {
            'obj': 'int64_t',
            'index': 'int64_t',
            'attrs': 'MojoList *',
        }
        self.struct_field_types['SliceExpr'] = {
            'obj': 'int64_t',
            'start': 'int64_t',
            'stop': 'int64_t',
            'step': 'int64_t',
        }
        self.struct_field_types['Comprehension'] = {
            'kind': 'char *',
            'element': 'int64_t',
            'key': 'int64_t',
            'generators': 'MojoList *',
        }
        self.struct_field_types['IdentExpr'] = {
            'name': 'char *',
        }
        # Literal and collection expression nodes — the compiled binary's own
        # parser produces these for ANY input file, and unregistered fields
        # fall back to mojo_obj_getattr → 0/NULL → garbage operands (e.g. the
        # `0` in `x > 0` lowering to a node handle instead of int 0, crashing
        # _lower_binary_tail's mojo_str_join). Register the full field sets.
        self.struct_field_types['IntLiteral'] = {
            'value': 'int64_t', 'line': 'int64_t', 'col': 'int64_t', 'raw': 'char *',
        }
        self.struct_field_types['FloatLiteral'] = {
            'value': 'double',
        }
        self.struct_field_types['BoolLiteral'] = {
            'value': '_Bool',
        }
        self.struct_field_types['EllipsisLiteral'] = {}
        self.struct_field_types['NoneLiteral'] = {}
        self.struct_field_types['StringLiteral'] = {
            'value': 'char *',
        }
        self.struct_field_types['TstringLiteral'] = {
            'value': 'char *',
        }
        self.struct_field_types['ImagLiteral'] = {
            'value': 'double',
        }
        self.struct_field_types['TupleLiteral'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['TupleExpr'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['ListLiteral'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['ListExpr'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['SetLiteral'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['SetExpr'] = {
            'elements': 'MojoList *',
        }
        self.struct_field_types['DictLiteral'] = {
            'pairs': 'MojoList *',
        }
        self.struct_field_types['DictExpr'] = {
            'pairs': 'MojoList *',
        }
        self.struct_field_types['WalrusExpr'] = {
            'name': 'char *', 'value': 'int64_t',
        }
        self.struct_field_types['YieldExpr'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['YieldFromExpr'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['AwaitExpr'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['StructDef'] = {
            'name': 'char *', 'fields': 'MojoList *', 'methods': 'MojoList *',
            'decorators': 'MojoList *', 'comptime_aliases': 'MojoDict *',
            'bases': 'MojoList *', 'line': 'int64_t', 'col': 'int64_t',
            '_fieldwise_ctor_synthesized': '_Bool',
        }
        self.struct_field_types['TraitDef'] = {
            'name': 'char *', 'methods': 'MojoList *', 'decorators': 'MojoList *',
        }
        # Boxed-object fields (int64_t handles to child AST nodes / values),
        # mirroring the same-named entries in the gated block above. Must be
        # recorded explicitly so repr()/getattr treat them as boxed handles
        # rather than raw integers (see the _is_selfhost_file block's comment).
        self.struct_boxed_fields['IfStmt'] = {'condition'}
        self.struct_boxed_fields['WhileStmt'] = {'condition'}
        self.struct_boxed_fields['ForStmt'] = {'target', 'iterable'}
        self.struct_boxed_fields['FunctionDef'] = {'return_type', 'yield_bearing_node_ids'}
        self.struct_boxed_fields['ExprStmt'] = {'value'}
        self.struct_boxed_fields['AssignStmt'] = {'target', 'value', 'type_ann'}
        self.struct_boxed_fields['AugAssignStmt'] = {'target', 'value'}
        self.struct_boxed_fields['ReturnStmt'] = {'value'}
        self.struct_boxed_fields['VarDecl'] = {'type_ann', 'value'}
        self.struct_boxed_fields['MultiAssignStmt'] = {'value'}
        self.struct_boxed_fields['AssertStmt'] = {'value', 'msg'}
        self.struct_boxed_fields['RaiseStmt'] = {'value'}
        self.struct_boxed_fields['ComptimeIfStmt'] = {'condition'}
        self.struct_boxed_fields['ComptimeForStmt'] = {'iterable'}
        self.struct_boxed_fields['ComptimeVarStmt'] = {'value'}
        self.struct_boxed_fields['MatchStmt'] = {'subject'}
        self.struct_boxed_fields['LambdaExpr'] = {'body'}
        self.struct_boxed_fields['SliceExpr'] = {'obj', 'start', 'stop', 'step'}
        self.struct_boxed_fields['Comprehension'] = {'element', 'key'}
        # SubscriptExpr.attrs is a MojoList of (name, value) tuple-pairs, so it
        # stays out of struct_boxed_fields; obj/index are already registered in
        # the gated block above — keep them here too since this block is the one
        # that runs for non-self-host user files.
        self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}

        # Fields declared `object = None` (or bare `object`, no
        # default_factory) in the real dataclass but hardcoded above to a
        # concrete 'MojoList *' ctype — see struct_nullable_container_fields'
        # own doc comment for why these need a NULL check in repr().
        self.struct_nullable_container_fields['SubscriptExpr'] = {'attrs'}
        self.struct_nullable_container_fields['IfStmt'] = {'else_body'}
        self.struct_nullable_container_fields['WhileStmt'] = {'else_body'}
        self.struct_nullable_container_fields['ForStmt'] = {'else_body'}
        self.struct_nullable_container_fields['TryStmt'] = {'else_body', 'finally_body'}
        self.struct_nullable_container_fields['ComptimeIfStmt'] = {'else_body'}
        self.struct_nullable_container_fields['ImportStmt'] = {'extra'}

        # Snapshot of every struct name whose field list is already known at
        # this point — either a real stdlib type seeded just above (Span) or,
        # when `_is_selfhost_file`, one of this repo's own hand-maintained
        # cheat-sheet entries (Scope/Token/Parser/Interpreter/_AutoStubValue/...).
        # The completeness passes further down (which auto-discover extra
        # fields by scanning method bodies for `self.x`/annotated-local reads
        # not caught by the normal `__init__`-assignment scan — the general
        # fix for stdlib files failing with "has no member named ...") must
        # never ADD to one of these: `_AutoStubValue = {}` above is a real,
        # deliberately empty field list (it's compiled as a bare scalar int
        # with dynamic getattr, not a real struct) — found via check-selfhost
        # regressing when a read-scan pass walked unrelated code elsewhere in
        # this same file that calls `_AutoStubValue(...)` and accesses an
        # attribute on the result (resolved dynamically via `__getattr__` in
        # real Python), and added that attribute as a phantom field here,
        # corrupting the intentionally-scalar C representation.
        self._selfhost_hardcoded_struct_names = frozenset(self.struct_field_types.keys())

        all_struct_defs = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        # Captured before _merge_struct_inheritance runs (it only mutates
        # .fields/.methods, never .bases, so ordering doesn't matter here) —
        # used by _lower_method_call's `super().method(...)` handling to find
        # the struct's base class name(s) at call-lowering time.
        self._struct_bases = {s.name: list(getattr(s, 'bases', None) or [])
                               for s in all_struct_defs if isinstance(s, StructDef)}
        # Structs with at least one base name that isn't any StructDef this
        # compilation unit knows about — e.g. `class IDGatherer
        # (html.parser.HTMLParser)`, where the parser only captures the
        # leading name token of a dotted base expression (see
        # mojo_compiler.py's ClassDef/StructDef base-list parsing), so even
        # `html` never resolves to a real struct. Used by
        # _lower_struct_method_call's auto-stub path: a method call that
        # can't be found on the struct's own/resolved-base methods, on one
        # of these, is inherited from a base with no native definition
        # anywhere — not a same-struct forward reference — so the auto-stub
        # must be a real (weak) definition, not a bare declaration.
        #
        # This must be a TRANSITIVE closure, not just a direct-base check:
        # e.g. Lib/logging/handlers.py's `class BaseRotatingHandler
        # (logging.FileHandler)` has an unresolved base (bare `import
        # logging` never pulls logging/__init__.py's StructDefs into this
        # compile's known-struct set, unlike `from logging import X`), so
        # BaseRotatingHandler correctly lands in this set — but its OWN
        # subclass `TimedRotatingFileHandler(BaseRotatingHandler)` has a
        # base name that IS a known StructDef (BaseRotatingHandler, defined
        # right there in the same file), so a direct-base-only check never
        # flagged the SUBCLASS, even though it inherits (and calls, e.g.
        # `self.handleError(...)`, `self._open()`) the exact same
        # never-defined-anywhere methods through that chain. Those calls
        # fell into the bare-forward-declaration branch below instead of
        # the weak-definition one, leaving a real undefined symbol at link
        # time (confirmed via `mojo.py build .../logging/handlers.py`).
        _all_struct_names = {s.name for s in all_struct_defs if isinstance(s, StructDef)}
        _struct_bases_map = {s.name: (getattr(s, 'bases', None) or [])
                              for s in all_struct_defs if isinstance(s, StructDef)}
        _unresolved_base_memo: dict = {}
        def _has_unresolved_base(_name, _stack=frozenset()):
            if _name in _unresolved_base_memo:
                return _unresolved_base_memo[_name]
            if _name in _stack:
                return False  # inheritance-cycle guard; shouldn't normally happen
            result = False
            for _b in _struct_bases_map.get(_name, ()):
                if _b not in _all_struct_names or _has_unresolved_base(_b, _stack | {_name}):
                    result = True
                    break
            _unresolved_base_memo[_name] = result
            return result
        self._structs_with_unresolved_base = {
            _name for _name in _struct_bases_map if _has_unresolved_base(_name)
        }
        _merge_struct_inheritance(all_struct_defs)
        self._exc_descendants = _compute_exc_descendants(all_struct_defs)
        # Pre-register all struct names so cross-references in _collect_self_assigns work
        # regardless of definition order (e.g. DispatchSolver before FunctionCompilability).
        for _s in all_struct_defs:
            if isinstance(_s, StructDef) and _s.name not in self.struct_field_types:
                self.struct_field_types[_s.name] = {}
        # Two unrelated classes sharing a bare name (found via mojo_compiler.py's
        # FunctionDef/ExprStmt/StringLiteral/... vs ast_nodes.py's own, entirely
        # separate, same-named AST-node classes — both reachable in the same
        # self-hosted closure since myinterpreter.py imports ast_nodes purely
        # for method-signature type annotations, never actually instantiating
        # them) must NOT have their fields merged into the same
        # struct_field_types[name] entry: struct reflection (_struct_type_id,
        # getattr/setattr/dataclasses.fields/repr) dispatches purely on that
        # bare name, so every REAL instance of either class — regardless of
        # which module it's really from — would get read through one
        # Frankenstein field list combining both. Found via `repr(ast)` on
        # even hello.mojo's trivial 2-statement AST once self-hosted:
        # FunctionDef gained a phantom `is_static` field (only ast_nodes.py's
        # FunctionDef has one) and unrelated later fields read as raw
        # addresses. First StructDef seen under a given name wins entirely;
        # track by identity (in the cross-module-shared _struct_name_owner,
        # not a call-local dict — a name claimed while compiling one imported
        # module must stay claimed when a *different* temp_gen sub-compile
        # later reaches an unrelated same-named class in another module) so a
        # legitimate re-scan of the *same* node (e.g. the transitive closure
        # reaching one file via two import paths) is still a harmless no-op,
        # not itself treated as a collision.
        # Constructor call-site scalar inference (bugs/hard/CODEGEN_
        # unannotated_init_param_field_type_defaults_int64.md): the
        # struct-field-collection loop just below (`_collect_self_assigns`)
        # types `self.field = unannotated_param` purely from __init__'s own
        # declared params, with zero cross-reference to how the class is
        # actually constructed — `Widget("hello")` right there in the same
        # file never informs `Widget.__init__`'s own `label` parameter,
        # which silently defaults to int64_t (the raw pointer's bit pattern
        # printed as a decimal integer instead of the real string). This
        # codebase already has a general mechanism for exactly this class of
        # problem for FREE functions (Pass 1.3d's cross-call scalar
        # contract, a few thousand lines down in this same method) — but
        # that pass runs too LATE to help here: it depends on
        # self._inferred_var_types, itself only populated even later, and
        # by the time it runs, `_collect_self_assigns` below has already
        # locked in every field's type. Rather than reordering Pass 1.3d
        # (broad, high-risk — this exact call-argument/parameter type-
        # inference machinery has already produced two real regressions
        # elsewhere this session), this is a standalone, narrower, EARLY
        # pass: only DIRECT LITERAL constructor arguments (StringLiteral/
        # FloatLiteral) are observed, not the fuller "IdentExpr referencing
        # an already-inferred variable" evidence Pass 1.3d's free-function
        # version uses (that needs machinery not built yet at this point in
        # gen_module). Still resolves the common, directly-reproducible
        # shape (a literal argument passed straight to a constructor)
        # additively — every unresolvable case (no literal evidence, or
        # disagreeing call sites) is left at today's int64_t default,
        # unchanged. Kept in its OWN attribute (not self._inferred_param_
        # types) since that dict is unconditionally reset to {} later, at
        # Pass 1.3c (~line 29351) — harmless for THIS pass's own consumer
        # (which reads it before that reset), but a distinct name avoids
        # any ambiguity about which pass owns which entries.
        self._ctor_lit_param_types: dict[str, dict[str, str]] = {}
        _ctor_init_params = {}
        _ctor_init_methods = {}
        for _s in all_struct_defs:
            if isinstance(_s, StructDef):
                _init = None
                for _m in _s.methods:
                    if _m.name == '__init__':
                        _init = _m
                        break
                if _init:
                    _ctor_init_params[_s.name] = [pn for pn, _ in (_init.params or [])
                                                  if pn != 'self' and not pn.startswith('*')]
                    # Avoid `next(gen, default)` here — a self-hosted build
                    # of this very file failed to link with an undefined
                    # `_next` symbol the last time this pattern was used
                    # over a freshly-built generator (see the identical,
                    # already-documented gotcha a few thousand lines down
                    # at Pass 1.3d's own scalar-type resolution).
                    _ctor_init_methods[_s.name] = _init
        if _ctor_init_params:
            _ctor_lit_obs: dict[str, dict[str, set]] = {}
            _ctor_calls: list = []
            self._calls_in_stmts(stmts, _ctor_calls)
            if self.do_imports or self.link_imports:
                self._calls_in_stmts(imported_stmts, _ctor_calls)
            for _call in _ctor_calls:
                if not isinstance(_call.func, IdentExpr):
                    continue
                _pnames = _ctor_init_params.get(_call.func.name)
                if not _pnames:
                    continue
                for _i, _a in enumerate(_call.args):
                    if _i >= len(_pnames):
                        break
                    if isinstance(_a, StringLiteral):
                        _ctor_lit_obs.setdefault(_call.func.name, {}).setdefault(
                            _pnames[_i], set()).add('char *')
                    elif isinstance(_a, FloatLiteral):
                        _ctor_lit_obs.setdefault(_call.func.name, {}).setdefault(
                            _pnames[_i], set()).add('double')
            for _struct_name, _pmap in _ctor_lit_obs.items():
                _init = _ctor_init_methods.get(_struct_name)
                if not _init:
                    continue
                _ann = {pn: pt for pn, pt in (_init.params or [])}
                for _pname, _types in _pmap.items():
                    if _types not in ({'double'}, {'char *'}):
                        continue                    # not unanimous double / char *
                    if _ann.get(_pname) is not None:
                        continue                    # respect explicit annotation
                    self._ctor_lit_param_types.setdefault(_struct_name, {})[_pname] = (
                        'double' if _types == {'double'} else 'char *')

        for s in all_struct_defs:
            if isinstance(s, StructDef) and s.name not in self._struct_name_owner:
                self._struct_name_owner[s.name] = id(s)
        for s in all_struct_defs:
            if isinstance(s, StructDef):
                if self._struct_name_owner.get(s.name) != id(s):
                    continue
                if s.name not in self.struct_field_types:
                    self.struct_field_types[s.name] = {}
                # For now, assume all struct fields on unknown types are pointers to the same struct
                # (e.g. Scope.parent is Scope*, Interpreter.scope is Scope*, etc.)
                # This is a heuristic to handle incomplete type information from imports
                for field in (s.fields if hasattr(s, 'fields') else []):
                    if isinstance(field, VarDecl) and field.name and field.name != 'self':
                        # For untyped fields, assume they're pointers to the containing struct
                        if not field.type_ann and field.name not in self.struct_field_types[s.name]:
                            # An untyped (`type_ann is None`) VarDecl here isn't
                            # always a genuinely-unresolvable field: it's ALSO
                            # the exact placeholder shape `_merge_struct_
                            # inheritance` copies in from a BASE class's
                            # `.fields` once that base's own fields were
                            # already fully resolved by an earlier compile
                            # pass (module caching — the base struct's real
                            # per-field types live in `self.struct_field_
                            # types[base_name]`, never in the placeholder
                            # VarDecl's own `type_ann`, by design: see the
                            # `_collect_self_assigns`/`_collect_self_reads`
                            # completion loop just below, which appends
                            # `VarDecl(name=fn, type_ann=None, value=None)`
                            # for exactly this reason). Blindly guessing
                            # "pointer to self" for such an inherited field
                            # clobbers its real, already-known type — e.g. a
                            # subclass with no `__init__` of its own
                            # (`class Parser(PLexer): ...`, only ever using
                            # the base's inherited constructor) got EVERY
                            # inherited field (`pos`, `src`, `filename`,
                            # `tokens`, all correctly `int64_t`/`char *`/
                            # `MojoList *` on the base struct `PLexer`)
                            # redeclared `struct Parser *` on `Parser`
                            # itself — a self-referential pointer type that
                            # is never actually assigned a `Parser *` value
                            # anywhere, so every real (scalar/string/list)
                            # value written through it hit GCC's `-fgimple`
                            # frontend as a hard type mismatch, or — for a
                            # `-` used on such a field's boxed-as-a-property
                            # value further downstream — a frontend internal
                            # compiler error. Look the field up on each base
                            # (in MRO order, matching `_merge_struct_
                            # inheritance`'s own `s.bases` walk) BEFORE
                            # falling back to the same-struct-pointer guess,
                            # so a genuinely inherited, already-resolved
                            # field keeps its real type and only a truly
                            # unknown field (not found on any base either —
                            # the original `Scope.parent`-style case this
                            # heuristic was written for) still gets the
                            # same-struct-pointer fallback. Found via Tools/
                            # cases_generator/parsing.py's `Parser(PLexer)`.
                            _inherited_ft = None
                            for _base_name in (getattr(s, 'bases', None) or []):
                                _base_ft = self.struct_field_types.get(_base_name, {})
                                if field.name in _base_ft:
                                    _inherited_ft = _base_ft[field.name]
                                    break
                            self.struct_field_types[s.name][field.name] = (
                                _inherited_ft if _inherited_ft is not None else s.name + ' *')
                # Record which of this struct's OWN methods are generators
                # (`FunctionDef.is_generator`) — used by `_cls_refs_supported`/
                # `_cpp_expr`'s `cls.<method>(...)` call handling to refuse a
                # call to another compiled GENERATOR method via `cls` (that
                # needs its own coroutine-construction call convention this
                # fix does not add — see those two call sites' own comments)
                # even when the method's mangled name also happens to be a
                # real `@classmethod` (`self._classmethod_names` is populated
                # purely from the decorator, independent of whether the
                # method is ALSO a generator — Lib/enum.py's `Flag.
                # _iter_member_by_value_` is exactly both at once). Populated
                # here (not derived on demand from `self._classmethod_names`/
                # `self.func_return_types`, neither of which distinguishes
                # "compiled as an ordinary function" from "compiled as a
                # coroutine") since this same loop already has `s.methods`
                # in scope for every struct. See bugs/CODEGEN_generator_
                # function_Lib_enum.md's 2026-08-21 update.
                self._struct_generator_method_names.setdefault(s.name, set()).update(
                    m.name for m in s.methods if getattr(m, 'is_generator', False))
                # Collect class-level attributes (non-self, non-method assignments at class body)
                self._class_attrs[s.name] = {}
                for field in s.fields:
                    if isinstance(field, AssignStmt):
                        if isinstance(field.target, IdentExpr):
                            aname = field.target.name
                            # Store a C-safe mangled name for this class attribute
                            mangled = f"_classattr_{s.name}__{aname}"
                            self._class_attrs[s.name][aname] = mangled
                            # Pre-populate _global_var_types so Phase 2a sees the correct type
                            v = field.value
                            ctype = _class_attr_ctype(v)
                            if ctype is not None:
                                self._global_var_types[mangled] = ctype
                                # A container-valued class-body attribute (e.g.
                                # `_PRELUDE_GENERICS = {...}`) is ALSO an
                                # instance struct field when read via `self.X`:
                                # _lower_MemberExpr checks struct_field_types
                                # (direct `self->X` read) BEFORE the _class_attrs
                                # global redirect, so without an entry here the
                                # self-reads scan defaulted the field to a
                                # 32-bit `int` and _alloc_{s.name}'s seeding
                                # guard (`field type == class-global type`)
                                # skipped the seed — leaving the instance slot
                                # as raw malloc garbage. The first
                                # `self._X.items()` / `x in self._X` then
                                # dereferenced that garbage (deterministic
                                # SIGSEGV/SIGABRT; the _PRELUDE_GENERICS one
                                # reproduced 100% with MallocGuardEdges=1).
                                # Register the matching container type here so
                                # the struct field is correct AND the alloc
                                # seed fires (Python semantics: a fresh
                                # instance's attr starts as the class value).
                                cur = self.struct_field_types[s.name].get(aname)
                                if cur is None or cur in ('int', 'int64_t'):
                                    self.struct_field_types[s.name][aname] = ctype
                                # Record the container's ELEMENT type too
                                # (`_field_elem_types`, the same map an
                                # instance `self.x = [...]` assignment in
                                # `__init__` already populates — see the
                                # CallExpr-branch companion in
                                # `_collect_self_assigns`) so a later `for x
                                # in self.<field>:` inside a generator body
                                # (`_cpp_for_stmt`) knows whether to unpack
                                # elements as `char *`/`int64_t` instead of
                                # guessing. Without this, a class-body tuple-
                                # of-strings attribute (save_env.py's
                                # `resources = ('sys.argv', 'cwd', ...)`)
                                # left `_field_elem_types` empty, and the
                                # generator-body for-loop defaulted every
                                # element to `int64_t` — wrong C type for a
                                # string, cascading into `name.replace(...)`
                                # "request for member ... non-class type
                                # int64_t" downstream.
                                if ctype == 'MojoList *' and isinstance(v, (ListExpr, TupleExpr)):
                                    self._field_elem_types.setdefault(s.name, {})[aname] = (
                                        self._infer_list_elem_type(v.elements))
                            elif isinstance(v, StringLiteral):
                                self._global_var_types[mangled] = 'char *'
                            elif isinstance(v, (IntLiteral, BoolLiteral)):
                                self._global_var_types[mangled] = 'int64_t'
                            else:
                                self._global_var_types[mangled] = 'int64_t'
                            # Seed `self._global_dict_val_types` from this
                            # class-body attribute's OWN declared annotation
                            # (`_X: dict[K, V] = {...}`), mirroring the
                            # struct-field pre-pass's identical eager seed
                            # of `_field_dict_val_types` a little further
                            # down in this same method (see that seed's own
                            # docstring for the full "generator methods are
                            # translated before the lazy per-statement pass"
                            # rationale — the class-level-global sibling has
                            # the exact same timing problem). Needed so a
                            # `cls.<dict-class-attr>.get(key)` read inside a
                            # compiled @classmethod generator (see this
                            # file's `_cpp_expr` MemberExpr/CallExpr `cls.
                            # <attr>` handling) can resolve the dict's real
                            # VALUE type instead of defaulting to int64_t.
                            # A dict literal WITH pairs already gets this
                            # from Phase 1.7's `_phase17_infer_global_type`
                            # (`_global_dict_val_types[_gname] = _vt`, from
                            # the pairs' own values) — but that only fires
                            # for a NON-EMPTY literal; an empty `{}` (the
                            # common class-attr-declared-then-populated-
                            # elsewhere idiom, e.g. `_value2member_map_:
                            # dict[Any, Flag] = {}`) needs the annotation
                            # instead, exactly like the struct-field case.
                            # Deliberately a SEPARATE, independent statement
                            # (not nested inside the ctype if/elif/else
                            # chain just above) so it can never change that
                            # chain's own control flow for a class attr with
                            # no annotation, or perturb `struct_field_types`
                            # for a non-container-valued attribute.
                            if field.type_ann is not None:
                                _dv_cls_early = self._annotation_dict_val_type(field.type_ann)
                                if _dv_cls_early is not None:
                                    self._global_dict_val_types[mangled] = _dv_cls_early
                # Explicit field declarations. A dataclass field with a
                # default (`x: Type = default`, the normal shape for every
                # trailing/optional field — e.g. `decorators: list =
                # field(default_factory=list)`) parses as an AssignStmt with
                # its type_ann set (not a VarDecl, which is a bare `x: Type`
                # declaration with no value) — see mojo_compiler.py's
                # annotated-assignment parsing. Without this, such fields
                # were invisible to struct_field_types entirely: found via
                # StructDef's own _fieldwise_ctor_synthesized field aborting
                # through the generic getattr fallback (struct_field_types
                # only had StructDef's 3 no-default fields, missing all 6
                # that have one).
                for field in s.fields:
                    _is_typed_assign = (isinstance(field, AssignStmt)
                                         and isinstance(field.target, IdentExpr)
                                         and field.type_ann is not None)
                    if isinstance(field, VarDecl) or _is_typed_assign:
                        f_name = field.name if isinstance(field, VarDecl) else field.target.name
                        # Don't overwrite hardcoded entries (e.g. BinaryOp.op)
                        if f_name not in self.struct_field_types[s.name]:
                            ft = _mojo_type(field.type_ann)
                            # Fixed-size-array field: `var x: [ElemType; N]`.
                            # See _FIXED_ARRAY_ANN_RE's own comment and
                            # bugs/BUG-2026-008.md (box.3d/game) — `ft` here
                            # becomes the marker string "ElemCtype[N]" (never
                            # produced by any other branch: it doesn't end in
                            # ' *', isn't a bare _TYPE_MAP/struct name), which
                            # the struct-typedef emission (gen_module) turns
                            # into a REAL embedded C array field, and
                            # _lower_subscript's dedicated branch (via
                            # self._array_field_sizes) turns `obj.field[i]`
                            # into real C array indexing instead of falling
                            # through to the MojoList*/generic-pointer paths.
                            _arr_m = (_FIXED_ARRAY_ANN_RE.match(str(field.type_ann).strip())
                                      if field.type_ann else None)
                            if _arr_m:
                                _elem_nm, _size_txt = _arr_m.group(1), _arr_m.group(2)
                                _n = (int(_size_txt) if _size_txt.isdigit()
                                      else self._module_const_int(_size_txt, stmts, imported_stmts))
                                if _n is not None and _n > 0:
                                    # A locally-defined struct element type is
                                    # embedded BY VALUE (the bare struct-typedef
                                    # name, not "Name *" — this is genuinely
                                    # different from every other struct-typed
                                    # field in this codegen, which are always
                                    # pointers; see the array-field comment
                                    # block above _FIXED_ARRAY_ANN_RE).
                                    _elem_ct = (_elem_nm if _elem_nm in self.struct_field_types
                                                else _mojo_type(_elem_nm))
                                    ft = f"{_elem_ct}[{_n}]"
                                    self._array_field_sizes.setdefault(s.name, {})[f_name] = (_elem_ct, _n)
                            if f_name == 'value' and s.name == 'Generator':
                                ft = 'int'  # boxed object field
                            _ann_bare = str(field.type_ann).strip() if field.type_ann else ''
                            if _ann_bare in ('object', 'Any') or (
                                    ' | ' in _ann_bare
                                    and any(p.strip()[:1].isupper()
                                            for p in _ann_bare.split(' | ') if p.strip() != 'None')):
                                self.struct_boxed_fields.setdefault(s.name, set()).add(f_name)
                            if _ann_bare == 'bool':
                                self.struct_bool_fields.setdefault(s.name, set()).add(f_name)
                            # If the type resolved to a generic container pointer (MojoList *,
                            # MojoDict *, MojoSet *, or double-pointer like MojoDict * *)
                            # but there is a locally-defined struct, prefer the local struct.
                            # Also handle Pointer[LocalStruct[...]] → LocalStruct *.
                            if field.type_ann and not _arr_m:
                                _ann_str = str(field.type_ann)
                                # Extract the outermost base name (e.g. 'Pointer', 'Dict', 'List')
                                _outer_base = _ann_str.split('[')[0].strip()
                                _ptr_wrappers = ('UnsafePointer', 'OwnedPointer',
                                                 'ArcPointer', 'Pointer', 'Reference')
                                if _outer_base in _ptr_wrappers and '[' in _ann_str:
                                    # Pointer[InnerType[...], origin] — grab InnerType base
                                    _inner = _ann_str.split('[', 1)[1]
                                    _inner_base = _inner.split('[')[0].strip()
                                    if _inner_base in self.struct_field_types:
                                        # Pointer[LocalStruct[...]] → LocalStruct *
                                        ft = f'{_inner_base} *'
                                elif ft.endswith(' *') and _outer_base in self.struct_field_types:
                                    # Direct: List[T] → List * (override MojoList *)
                                    ft = f'{_outer_base} *'
                            self.struct_field_types[s.name][f_name] = ft
                            # Seed `self._field_dict_val_types` from this
                            # field's OWN declared annotation (`var x: dict[K,
                            # V]`) at this same early pre-pass, using the
                            # SAME `_annotation_dict_val_type` helper the
                            # ordinary per-statement AssignStmt lowering later
                            # uses for its own (lazier) seeding -- reused, not
                            # duplicated. Needed so a compiled GENERATOR
                            # METHOD's `self.<dict-field>.get(key)` (struct-
                            # pointer-yield support, see
                            # _infer_simple_expr_ctype's docstring) can see
                            # the field's real dict value type: generator
                            # methods are translated in gen_module's
                            # "Milestone C step 3" pass, which runs BEFORE
                            # the ordinary per-statement body-compile loop
                            # that populates `_field_dict_val_types` lazily
                            # (from an ANNOTATED `self.x: dict[K, V] = ...`
                            # assignment inside `__init__`'s own body) — a
                            # class-body-declared field's annotation is
                            # already sitting right here, so there is no
                            # reason to wait for that later pass to see it
                            # for THIS shape.
                            _dv_early = self._annotation_dict_val_type(field.type_ann)
                            if _dv_early is not None:
                                self._field_dict_val_types.setdefault(s.name, {})[f_name] = _dv_early

                # Always scan ALL methods for self.x = ... to build complete field list.
                # Uses the generic _walk_ast walker (module-level, above) rather than
                # a hand-rolled list of body-bearing attribute names, so assignments
                # nested inside elif/try-except/finally/with/match bodies are seen too
                # (a real, previously-missed gap: fields only ever assigned inside such
                # a branch were absent from struct_field_types and the generated C
                # struct never declared them at all — not merely mistyped).
                def _self_member(expr):
                    """MemberExpr's `.member` name iff its object is bare `self`."""
                    if (isinstance(expr, MemberExpr) and isinstance(expr.obj, IdentExpr)
                            and expr.obj.name == 'self'):
                        return expr.member
                    return None

                def _collect_self_assigns(body, param_types, found):
                    for node in _walk_ast(body):
                        if isinstance(node, AssignStmt):
                            fn = _self_member(node.target)
                            # Was: `fn not in found` (first assignment to a
                            # given field wins, later ones in the SAME method
                            # silently ignored). Real bug: turtle.py's
                            # RawTurtle.__init__ assigns `self.screen` from
                            # FOUR different branches of one if/elif chain —
                            # the FIRST in document order is
                            # `self.screen = canvas` where `canvas` is an
                            # unannotated, defaulted (`=None`) parameter, so
                            # `ft` below is the generic 'int64_t' fallback;
                            # a later, much more specific branch in the very
                            # same __init__ (`self.screen =
                            # TurtleScreen(canvas)`, `cn in
                            # self.struct_field_types` below) would have
                            # correctly resolved to 'TurtleScreen *', but
                            # "first wins" never let it compete. The wrongly-
                            # int64_t-typed `screen` field then made every
                            # `self.screen.<method>(...)` call site (real:
                            # RawTurtle._color/_colorstr calling
                            # `self.screen._color(args)`) unresolvable to a
                            # real struct method, silently lowered as an
                            # "int64_t.<method>() stubbed" no-op instead —
                            # which in turn made `_color`'s OWN inferred
                            # return type wrong (int64_t instead of the real
                            # pointer/string type its body actually produces
                            # via the stub's fallthrough), cascading into
                            # `-fgimple`'s honest "invalid conversion in
                            # return statement" for every caller (`pencolor`/
                            # `fillcolor`) whose forward-declared return type
                            # was inferred from that wrong `_color` return
                            # type. Mirrors the EXACT same weak-vs-strong
                            # upgrade reasoning the cross-method `can_override`
                            # check below already uses (there: 'int' ->
                            # pointer, across separate methods) — generalized
                            # here to also apply WITHIN one method's own
                            # multiple assignment sites, and to the 'int64_t'
                            # weak default too (the case that actually fires
                            # for an unannotated/defaulted parameter, not just
                            # bare 'int'). Only ever upgrades a generic
                            # int/int64_t guess to a more specific type —
                            # never fights two already-specific candidates
                            # against each other, so a field genuinely
                            # reassigned different concrete types across
                            # branches keeps whichever specific type is
                            # found first, same as before.
                            _existing_fn_ft = found.get(fn)
                            if fn is not None and (
                                    fn not in found
                                    or (_existing_fn_ft in ('int', 'int64_t')
                                        and _existing_fn_ft is not None)):
                                v = node.value
                                if isinstance(v, IdentExpr):
                                    ft = param_types.get(v.name, 'int64_t')
                                elif isinstance(v, IntLiteral):
                                    ft = 'int64_t'
                                elif isinstance(v, StringLiteral):
                                    ft = 'char *'
                                elif isinstance(v, BoolLiteral):
                                    ft = '_Bool'
                                elif isinstance(v, DictExpr):
                                    ft = 'MojoDict *'
                                elif isinstance(v, (ListExpr, TupleExpr)):
                                    ft = 'MojoList *'
                                elif isinstance(v, SetExpr):
                                    ft = 'MojoSet *'
                                elif isinstance(v, Comprehension):
                                    # A comprehension is a DIFFERENT AST node
                                    # than a literal ListExpr/DictExpr/SetExpr
                                    # (see bugs/hard/CODEGEN_unannotated_
                                    # init_param_field_type_defaults_int64.md's
                                    # "Sibling gap" section) and matched none
                                    # of the cases above, falling to the
                                    # generic 'int' default -- found via
                                    # Tools/cases_generator/cwriter.py's
                                    # `self.indents = [i * 4 for i in
                                    # range(indent + 1)]` (declared `int
                                    # indents;`, the real value a truncated
                                    # MojoList* pointer).
                                    ft = {'list': 'MojoList *', 'set': 'MojoSet *',
                                          'dict': 'MojoDict *'}.get(v.kind, 'MojoList *')
                                elif isinstance(v, CallExpr):
                                    cfn = v.func
                                    cn = cfn.name if isinstance(cfn, IdentExpr) else ''
                                    if cn in ('list', 'DynamicVector', 'mojo_list_new'):
                                        ft = 'MojoList *'
                                    elif cn in ('dict', 'Dict', 'mojo_dict_new'):
                                        ft = 'MojoDict *'
                                    elif cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
                                        ft = 'MojoSet *'
                                    elif cn.startswith('_alloc_'):
                                        # _alloc_StructName() returns StructName *
                                        sname = cn[len('_alloc_'):]
                                        ft = sname + ' *'
                                    elif cn in self.struct_field_types:
                                        ft = cn + ' *'
                                    elif (isinstance(cfn, MemberExpr)
                                          and cfn.member in _STR_RETURNING_METHODS):
                                        # A chained method call (`loader.prefix.
                                        # replace(...)`) has a MemberExpr func, not
                                        # a bare IdentExpr, so `cn` above is always
                                        # '' for it -- every one of these fell to
                                        # the generic 'int' default below regardless
                                        # of the method actually being one of
                                        # Python's well-known ALWAYS-str-returning
                                        # str methods. A field seeded 'int' here
                                        # then gets a real `char *` value written
                                        # into it (self.prefix = ...replace(...)),
                                        # a struct-field type mismatch ("non-trivial
                                        # conversion" family of GIMPLE errors) rather
                                        # than a targeted fix -- found via importlib/
                                        # resources/readers.py's ZipReader.__init__.
                                        ft = 'char *'
                                    elif (isinstance(cfn, MemberExpr)
                                          and cfn.member in _LIST_RETURNING_METHODS):
                                        ft = 'MojoList *'
                                    else:
                                        ft = 'int'
                                else:
                                    ft = 'int'
                                found[fn] = ft
                        elif isinstance(node, MultiAssignStmt):
                            for tgt in node.targets:
                                fn = _self_member(tgt)
                                if fn is not None and fn not in found:
                                    found[fn] = 'int'
                        elif isinstance(node, AugAssignStmt):
                            fn = _self_member(node.target)
                            if fn is not None and fn not in found:
                                found[fn] = 'int64_t'

                # Second pass: fields that are only ever *read* via `self.x` and never
                # assigned anywhere in this class's own methods (e.g. a field a real
                # subclass, possibly in another module, is responsible for setting —
                # `_markupbase.ParserBase.rawdata`/`updatepos` is the canonical example:
                # every method reads `self.rawdata` but only a subclass like
                # `html.parser.HTMLParser` ever assigns it). Compiling this class
                # standalone can't see that subclass, but the C struct still must
                # declare the field or every read is a hard 'has no member named'
                # compiler error — so register it with the same generic boxed-object
                # representation ('int') already used for any field whose type can't
                # be pinned down statically; runtime attribute access on it still goes
                # through the normal dynamic dispatch machinery.
                # `self.foo` walked generically by `_walk_ast` also matches the
                # `.func` of a method CALL (`self.foo(...)`) — that is a read of
                # the *method* `foo`, never a struct field, and must not be
                # confused with one. Otherwise every ordinary method call inside
                # the class's own methods (e.g. BufferedSubFile.close() calling
                # `self.pushlines(...)`) synthesizes a spurious int-typed field
                # named after the method, which then fights the method's real
                # signature — the `non-trivial conversion`/`declared void`/
                # `conflicting types` family of C errors on the generated
                # struct's getattr/setattr/repr dispatch functions.
                _method_names = {m.name for m in s.methods}

                def _collect_self_reads(body, found):
                    for node in _walk_ast(body):
                        fn = _self_member(node)
                        if (fn is not None and fn not in found and fn not in _method_names
                                and fn not in _PSEUDO_DUNDER_ATTRS):
                            found[fn] = 'int'

                already = set(self.struct_field_types[s.name].keys())
                for method in s.methods:
                    pm = {}
                    _defaults = getattr(method, 'param_defaults', {}) or {}
                    for pname, ptype in method.params:
                        if pname != 'self':
                            # Unannotated params hold object handles (pointer-width);
                            # default to int64_t so a field assigned from one isn't
                            # truncated to 32-bit int (size-mismatch cast on read).
                            if ptype:
                                pm[pname] = self._resolve_type(ptype)
                            elif pname in _defaults:
                                # Infer type from the default value when no
                                # annotation is provided (e.g. `file=""`).
                                _dv = _defaults[pname]
                                if isinstance(_dv, StringLiteral):
                                    pm[pname] = 'char *'
                                elif isinstance(_dv, BoolLiteral):
                                    pm[pname] = '_Bool'
                                else:
                                    pm[pname] = 'int64_t'
                            elif (method.name == '__init__'
                                  and pname in self._ctor_lit_param_types.get(s.name, {})):
                                # Real constructor call-site evidence (a
                                # literal argument observed above) beats the
                                # generic int64_t default — see bugs/hard/
                                # CODEGEN_unannotated_init_param_field_type_
                                # defaults_int64.md. Scoped to __init__ only:
                                # a same-named param on a DIFFERENT method has
                                # no relation to how the class was constructed.
                                pm[pname] = self._ctor_lit_param_types[s.name][pname]
                            else:
                                pm[pname] = 'int64_t'
                    new_fields = {}
                    _collect_self_assigns(method.body, pm, new_fields)
                    for fn, ft in new_fields.items():
                        # Don't overwrite annotation-based / hardcoded field types,
                        # annotations are the source of truth for struct field types.
                        # However, allow overriding 'int' (from = None / = 0) with a more
                        # specific pointer type discovered in a later method assignment.
                        existing_ft = self.struct_field_types[s.name].get(fn)
                        can_override = (existing_ft == 'int' and ft.endswith(' *'))
                        if fn not in self.struct_field_types[s.name] or can_override:
                            self.struct_field_types[s.name][fn] = ft
                            if fn not in already:
                                s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                                already.add(fn)
                if s.name in self._selfhost_hardcoded_struct_names:
                    # Authoritative hand-maintained field list (see the
                    # snapshot comment above) — never auto-extend it.
                    continue
                for method in s.methods:
                    read_fields = {}
                    _collect_self_reads(method.body, read_fields)
                    for fn, ft in read_fields.items():
                        if fn not in self.struct_field_types[s.name]:
                            # Before falling back to the generic 'int'
                            # read-only default, check whether a base class
                            # already resolved this field to something more
                            # specific. A field ASSIGNED only inside a base
                            # class's `__init__` (`TurtleScreenBase.__init__`:
                            # `self.cv = cv`) is invisible to this class's own
                            # `_collect_self_assigns` scan whenever the
                            # subclass overrides `__init__` itself (even if
                            # that override's only job is calling
                            # `Base.__init__(self, cv)` — `_merge_struct_
                            # inheritance` excludes an overridden method from
                            # `s.methods` entirely, by design, so the base
                            # method's own self-assignment is never walked
                            # for THIS class). The field is still read all
                            # over the subclass's own methods
                            # (`self.cv.coords(...)`/`self.cv.config(...)`),
                            # so `_collect_self_reads` finds it and, absent
                            # this check, always guesses the generic 'int'
                            # boxed-object fallback — even when the base
                            # class already pinned it to a real, specific
                            # type (here 'int64_t', from the unannotated
                            # `cv` constructor param). A mixed 'int' (this
                            # class's struct field) vs 'int64_t' (the actual
                            # value stored through it, e.g. via another
                            # subclass that DOES scan the base assignment)
                            # cross-struct-instance type split is exactly the
                            # shape GCC's `-fgimple` rejects as "non-trivial
                            # conversion"/"type mismatch in binary
                            # expression" once two differently-typed
                            # monomorphized copies of a shared method
                            # (`_pointlist`, common to `TurtleScreenBase`/
                            # `TurtleScreen`/`_Screen`) exist side by side.
                            # Mirrors the identical base-lookup pattern the
                            # VarDecl-completion pass above already uses
                            # (same MRO-order walk over `s.bases`) — only
                            # ever upgrades a generic guess to a more
                            # specific inherited type, never overrides an
                            # already-specific local finding.
                            _base_ft = None
                            for _base_name in (getattr(s, 'bases', None) or []):
                                _cand = self.struct_field_types.get(_base_name, {}).get(fn)
                                if _cand is not None:
                                    _base_ft = _cand
                                    break
                            self.struct_field_types[s.name][fn] = _base_ft if _base_ft is not None else ft
                            if fn not in already:
                                s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                                already.add(fn)

        # Fourth completeness pass: fields accessed only through a *locally
        # annotated* variable of a known struct type, not through `self`
        # directly. E.g. _pyrepl/completing_reader.py's `complete.do()`:
        #   r: CompletingReader
        #   r = self.reader
        #   r.msg = "..."
        # `r`'s own class (`complete`, a Command) is unrelated to
        # CompletingReader — the field belongs on CompletingReader, a
        # *different* struct than the one whose method we're scanning, so
        # this can't be folded into the per-`s` passes above (each of those
        # only ever registers fields on `s.name` itself). Runs after every
        # struct's own fields are known so `local_types` below can recognize
        # any struct name regardless of definition order.
        # This also covers a plain free function's local variable, not just a
        # method's (e.g. asyncio/__main__.py's `repl_thread = REPLThread(...)`
        # / later `repl_thread.daemon = True`, both inside a module-level
        # function, no class involved at all).
        _struct_by_name = {st.name: st for st in all_struct_defs
                            if isinstance(st, StructDef)
                            and self._struct_name_owner.get(st.name) == id(st)}

        # Per-top-level-statement caches for the two `_walk_ast` sub-scans
        # below (see bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
        # rescan.md, Phase 2). `_scan_body_for_local_field_access` used to
        # call `_walk_ast(body)` twice on every invocation, and `body`
        # (`imported_stmts` in particular) grows to O(total transitive tree
        # size) at EVERY nesting level (see the doc's root-cause section) —
        # summed over N levels that's O(N^2) total node visits. Since
        # `_walk_ast(list_of_stmts)` is exactly the concatenation of
        # `_walk_ast([s])` for each `s` in the list (no cross-statement
        # state in `_walk_ast` itself), the expensive per-node walk of each
        # INDIVIDUAL top-level statement's own subtree can be memoized by
        # `id(stmt)` and reused verbatim across every later call that also
        # includes that same statement object — shared by reference into
        # every temp_gen exactly like `_all_transitive_stmts_ordered`
        # (see its own sharing block in `_compile_imported_module`), so the
        # memoization applies tree-wide, not just within one level.
        #
        # Care point: the CANDIDATES cached here are the raw syntactic
        # matches only (VarDecl-with-annotation / `x = Ctor(...)` shape,
        # MemberExpr-with-IdentExpr-obj minus dunder members) — NOT
        # filtered by `ann in self.struct_field_types` / `not in
        # self._selfhost_hardcoded_struct_names` / `!= own_struct_name`.
        # Those three filters are all time-/call-dependent (struct_field_
        # types grows monotonically as unrelated structs are discovered
        # elsewhere during compilation; _selfhost_hardcoded_struct_names is
        # a per-gen_module-call snapshot; own_struct_name is a per-call
        # parameter) — baking them into the cache at first-visit time would
        # silently and permanently miss any candidate whose governing
        # struct becomes known only on a LATER call. Re-applying them fresh
        # against the cached candidate list on every call (cheap — a plain
        # list iteration, no `_walk_ast`) preserves the original's exact
        # per-call semantics while still eliminating the repeated tree
        # walk itself, which is what the profile shows dominating cost.
        def _scan_stmt_var_candidates(stmt):
            sid = id(stmt)
            cached = self._field_scan_var_cache.get(sid)
            if cached is not None:
                return cached
            cands = []
            for node in _walk_ast(stmt):
                if isinstance(node, VarDecl) and node.type_ann:
                    cands.append((node.name, str(node.type_ann).strip()))
                # `x = SomeStruct(...)` — no explicit annotation, but the
                # constructor call itself pins the type just as well.
                elif (isinstance(node, AssignStmt) and isinstance(node.target, IdentExpr)
                      and isinstance(node.value, CallExpr) and isinstance(node.value.func, IdentExpr)):
                    cands.append((node.target.name, node.value.func.name))
            self._field_scan_var_cache[sid] = cands
            return cands

        def _scan_stmt_member_candidates(stmt):
            sid = id(stmt)
            cached = self._field_scan_member_cache.get(sid)
            if cached is not None:
                return cached
            cands = []
            for node in _walk_ast(stmt):
                if not (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)):
                    continue
                fn = node.member
                if fn.startswith('__') and fn.endswith('__'):
                    continue
                cands.append((node.obj.name, fn))
            self._field_scan_member_cache[sid] = cands
            return cands

        def _scan_body_for_local_field_access(body, own_struct_name):
            local_types = {}
            for stmt in body:
                for name, ann in _scan_stmt_var_candidates(stmt):
                    if (ann in self.struct_field_types and ann != own_struct_name
                            and ann not in self._selfhost_hardcoded_struct_names):
                        local_types[name] = ann
            if not local_types:
                return
            for stmt in body:
                for obj_name, fn in _scan_stmt_member_candidates(stmt):
                    target_struct = local_types.get(obj_name)
                    if target_struct is None:
                        continue
                    if fn in self.struct_field_types[target_struct]:
                        continue
                    self.struct_field_types[target_struct][fn] = 'int'
                    target_def = _struct_by_name.get(target_struct)
                    if target_def is not None and not any(
                            isinstance(f, VarDecl) and f.name == fn for f in target_def.fields):
                        target_def.fields.append(VarDecl(name=fn, type_ann=None, value=None))

        # `_walk_ast` already recurses into every nested FunctionDef/StructDef
        # method/if/try/loop body reachable from a statement list, so a single
        # call over the whole module's top-level statements also reaches every
        # function body AND every class method body in one pass — no need to
        # separately iterate `s.methods` vs. free `FunctionDef`s vs. bare
        # module-level code (e.g. asyncio/__main__.py's `repl_thread = REPLThread(...)`
        # sits directly under an `if __name__ == "__main__":` at module scope,
        # not inside any function or class at all).
        _scan_body_for_local_field_access(stmts, None)
        if self.do_imports or self.link_imports:
            _scan_body_for_local_field_access(imported_stmts, None)

        # Register struct constructors as functions returning T *
        # Include both current module and imported module structs
        # Preserve types registered by _emit_stdlib_import_externs (Phase 0 pre-pass) so
        # they survive the Phase 1 reset. _RUNTIME_FUNCS forms the base; Phase 0 types win.
        _phase0_func_types = dict(self.func_return_types)   # save Phase 0 registrations
        _phase0_imported   = dict(getattr(self, 'imported_symbols', {}))  # save Phase 0 imported_symbols
        self.func_return_types = dict(_RUNTIME_FUNCS)
        self.func_return_types.update(_phase0_func_types)   # Phase 0 types win over defaults
        all_struct_defs_for_types = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        for s in all_struct_defs_for_types:
            if isinstance(s, StructDef):
                self.func_return_types[s.name] = f"{s.name} *"

        # Process imports: load modules and register imported symbols
        self.imported_symbols = dict(_phase0_imported)   # restore Phase 0 imported_symbols
        for s in stmts:
            if isinstance(s, FromImportStmt):
                # A local project sibling module (e.g. `mojo dylib`'s
                # per-module standalone compile importing a neighboring
                # .mojo file — see bugs/DYLIB_sibling_import_calls_bind_
                # to_weak_stubs.md) isn't in module_loader's stdlib/test
                # tracked set, so load_module() raises. Before falling back
                # to the "genuinely external/unresolved" path below (weak
                # stub, no module qualifier), try resolving it the same way
                # _find_imported_struct/_find_generic_source already do for
                # cross-module struct/generic lookups: if it resolves, this
                # sibling's real definition is compiled into the very same
                # output (driver._expand_dylib_modules walks this same
                # import closure into the dylib's build list) — so its call
                # sites must learn the sibling's module qualifier via
                # _note_own_func_home, not bind to an unqualified weak stub.
                _sib_qualifier = None
                try:
                    exports = load_module(s.module)
                except Exception:
                    exports, _sib_qualifier = self._local_sibling_module_exports(s.module)
                # Whether `s.module` resolved to a file genuinely OUTSIDE the
                # tracked stdlib/test trees — i.e. a real local PROJECT
                # sibling (base/chest.mojo, this whole mechanism's actual
                # target — see bugs/DYLIB_sibling_import_calls_bind_to_weak_
                # stubs.md), not a stdlib-internal relative import that
                # merely failed the bare `load_module(s.module)` call above
                # because that call doesn't resolve leading-dot relative
                # module strings itself (unlike `_emit_stdlib_import_
                # externs`'s own explicit dot-resolution) even though the
                # module IS a real, already-tracked stdlib file. Confirmed
                # via std/pwd/__init__.mojo's `from .pwd import getpwnam,
                # getpwuid`: `.pwd` hits this same `_local_sibling_module_
                # exports` fallback (`_sib_qualifier` gets set) purely
                # because of that dot-resolution gap, and `_emit_stdlib_
                # import_externs` (Phase 0, run earlier) ALSO independently
                # registers an extern for the SAME qualified symbol —
                # harmless while both computed the same generic `int64_t`
                # default, but a hard "conflicting types" compile error once
                # the struct/return-type corrections below started
                # resolving ONE of the two declarations to the real
                # `Passwd *` while the other stayed stale. Scoping these
                # corrections to genuine non-stdlib project files avoids
                # this pre-existing dual-registration hazard entirely rather
                # than trying to reconcile two independently-maintained
                # extern-emission passes.
                _sib_is_local_project = False
                if _sib_qualifier:
                    try:
                        import module_loader as _mlmod_chk
                        _sib_path0 = self._parsed_import(s.module)[0]
                        _sib_is_local_project = bool(_sib_path0) and not (
                            _sib_path0.startswith(_mlmod_chk.STDLIB_PATH)
                            or _sib_path0.startswith(_mlmod_chk.TEST_PATH))
                    except Exception:
                        _sib_is_local_project = False
                if _sib_is_local_project and _sib_qualifier not in self._toplevel_dep_init_modules:
                    self._toplevel_dep_init_modules.append(_sib_qualifier)
                if exports is not None:
                    def _register_sym(sym_name, orig_name, sym_info):
                        if sym_name in self.struct_field_types:
                            return
                        # `from PKG import NAME` where NAME is a real
                        # SUBMODULE FILE (`PKG/NAME.py`/`PKG/NAME/
                        # __init__.py`), not a symbol defined inside PKG's
                        # own source — this is the TOP-LEVEL (module-scope)
                        # twin of `_gen_stmt_FromImportStmt`'s identical
                        # submodule check (see `_from_import_name_is_
                        # submodule`'s docstring and bugs/CODEGEN_
                        # generator_function_Lib_test_test_support.md's
                        # 2026-08-09 root-cause: `TESTFN = os_helper.
                        # TESTFN` via a MODULE-LEVEL `from test.support
                        # import os_helper` never reaches the function-
                        # body statement-lowering path at all — gen_module
                        # skips top-level FromImportStmts there entirely
                        # and processes them here instead). Register a
                        # genuine module marker (mirrors `_gen_stmt_
                        # ImportStmt`'s function-body registration shape)
                        # BEFORE the `sym_info`-empty fallback below, which
                        # would otherwise mark it `_unresolved_import_
                        # aliases` — losing the submodule's real dotted
                        # identity, and with it any chance of
                        # `_lower_MemberExpr`'s cross-module-global-read
                        # branch resolving `os_helper.TESTFN` to the real
                        # value instead of a NULL-pointer runtime dispatch.
                        if not s.wildcard and self._from_import_name_is_submodule(s.module, orig_name):
                            self.imported_symbols[sym_name] = {
                                'module': f"{s.module}.{orig_name}",
                                'return_type': 'unknown',
                            }
                            return
                        if _sib_qualifier and not sym_info:
                            # The sibling FILE resolved, but this particular
                            # imported name wasn't found among its fn/def
                            # signatures (module_loader's scanner — same one
                            # load_module() itself uses for stdlib — only
                            # extracts FUNCTIONS; a struct, comptime alias,
                            # or re-exported-from-a-further-sibling name
                            # comes back with no info). Unlike the stdlib
                            # case just below (where this has always been a
                            # silent no-op — untouched, pre-existing
                            # behavior), a local sibling name reaching here
                            # was, before this whole sibling-import fix
                            # existed, marked `_unresolved_import_aliases`
                            # (the module-load exception below used to fire
                            # for EVERY name in a local-sibling import,
                            # struct or not) — and callers like
                            # `_lower_opaque_ctor`'s uppercase-constructor
                            # guard rely on that marking to fall back to a
                            # self-contained weak stub instead of emitting a
                            # bare `extern` with no definition anywhere
                            # (confirmed via box.3d/game's real `ItemSlot`
                            # struct, imported cross-module exactly this
                            # way: silently link-broken — "symbol not found"
                            # at dlopen — without this fallback, since this
                            # fix's own function scan never taught struct
                            # constructors a home module). Restore that
                            # fallback for exactly this "resolved file, but
                            # this specific name isn't a function" case, so
                            # non-function local-sibling imports keep
                            # working exactly as before this fix.
                            if not s.wildcard:
                                self._unresolved_import_aliases.add(sym_name)
                            return
                        if isinstance(sym_info, str):
                            self.imported_symbols[sym_name] = {
                                'module': s.module, 'original_name': orig_name,
                                'return_type': sym_info, 'parameters': [],
                                'signature': f"{sym_info} {sym_name} (void)"
                            }
                            self.func_return_types[sym_name] = sym_info
                        elif isinstance(sym_info, dict):
                            # Defensive shallow copy BEFORE any mutation: this
                            # dict is NOT private to this call — it's the
                            # actual object cached inside module_loader's
                            # process-WIDE singleton (`_module_loader.
                            # _path_cache[path][sym_name]`, returned by
                            # `_local_sibling_module_exports` ->
                            # `load_module_from_path`, keyed purely by file
                            # path — the SAME dict object is handed back,
                            # unconditionally, to every GimpleGen instance in
                            # this process that ever imports this symbol from
                            # this path, for the lifetime of the process, not
                            # just this one compile). Mutating it in place
                            # (as every line below this comment, and the
                            # return-type/parameter-type corrections further
                            # down, do) silently poisons that shared cache for
                            # every OTHER, unrelated module's compile that
                            # happens to import the same symbol later in the
                            # same process — e.g. `mojo dylib`'s multi-module
                            # build compiles dozens of files sequentially in
                            # one process. Confirmed real: compiling game_
                            # engine.mojo (which resolves `engine_world`'s
                            # `engine_view_hopper_input` return type to a
                            # real `ItemSlot *` ONLY because game_engine.mojo
                            # ALSO separately imports `ItemSlot` directly from
                            # base.items, pre-registering it in THAT
                            # instance's own struct_field_types) mutated the
                            # shared cache entry for `engine_view_hopper_
                            # input` to `c_return_type='ItemSlot *'`; a LATER,
                            # completely independent compile of game_ffi.mojo
                            # then inherited that leaked `'ItemSlot *'` return
                            # type from the poisoned cache (its OWN, correct,
                            # from-scratch resolution attempt returns None —
                            # traced and confirmed) WITHOUT also getting a
                            # real local typedef for ItemSlot (materialization
                            # is genuinely per-instance, so it did NOT leak) —
                            # "unknown type name 'ItemSlot'". Copying here
                            # makes every mutation below strictly local to
                            # THIS sym_name/THIS import statement/THIS
                            # GimpleGen instance, closing the leak at its
                            # single point of entry rather than auditing every
                            # mutation site individually.
                            sym_info = dict(sym_info)
                            sym_info['module'] = s.module
                            sym_info['original_name'] = orig_name
                            self.imported_symbols[sym_name] = sym_info
                            _ret_changed = False
                            # A leading-underscore ORIGINAL name (e.g.
                            # std/pwd/_macos.mojo's `_getpw_macos`) is NOT
                            # exported by reflect.py's dylib-reflection table
                            # (module_loader.py's own `_mojo_type_to_c`
                            # docstring documents this — BUG-2026-036), so a
                            # call site importing one is resolved through a
                            # SEPARATE mechanism that computes its own extern
                            # declaration independently of `sym_info`/
                            # `imported_symbols` (confirmed: std/pwd/pwd.mojo
                            # emits TWO differently-guarded externs for
                            # `_getpw_macos` — one from this loop, one from
                            # that other path — that happened to coincide on
                            # the generic `int64_t`/`(...)` default before
                            # this fix and diverge, a hard "conflicting
                            # types" compile error, once this loop alone
                            # started resolving its real `Passwd *` return
                            # type). Correcting the type on only ONE of two
                            # independently-emitted declarations for the same
                            # symbol is unsafe by construction (exactly the
                            # "two sides compute different signatures for one
                            # symbol" class of bug this whole fix exists to
                            # avoid) — leave leading-underscore names exactly
                            # as module_loader's scan computed them, matching
                            # `_register_imported_structs`'s own established
                            # `nm.startswith('_')` skip for the same class of
                            # name.
                            if orig_name.startswith('_'):
                                pass
                            elif _sib_is_local_project and sym_info.get('return_type'):
                                # Mirror the parameter-type correction below,
                                # but for the sibling function's own RETURN
                                # type — e.g. base/chest.mojo's `Chest_new()
                                # -> Chest`. Left uncorrected, module_loader's
                                # text-only scan defaults an unrecognized
                                # `Chest` return type to plain int64_t, so a
                                # caller's `c := Chest_new()` types `c` as a
                                # bare scalar — NOT a `Chest *` — and a
                                # subsequent local `c.s0_id = 5` then lowers
                                # to a DYNAMIC `_mojo_dispatch_setattr` call
                                # (the generic "unknown struct type" fallback)
                                # instead of a real struct field write.
                                # Meanwhile a later call whose PARAMETER type
                                # WAS corrected (chest_total_count(c, ...))
                                # casts that same `c` to a real `Chest *` and
                                # reads its fields directly — a different
                                # storage path than the dynamic setattr wrote
                                # to, so the read silently comes back as the
                                # zero-initialized default instead of the
                                # value just assigned. No crash, no link
                                # error — just a silently wrong value
                                # (confirmed via `Chest_new()` + direct
                                # `c.s0_id = 5`/`c.s0_count = 10` field writes
                                # + `chest_total_count(c, 5)`: real Mojo/the
                                # interpreter both return the correct `10`;
                                # this gap alone made the compiled dylib path
                                # return `0`). Correcting `c_return_type` here
                                # (before it's read into func_return_types
                                # just below, and before this loop's own
                                # parameter/signature correction further down
                                # rebuilds `signature` from it) makes both the
                                # WRITE side (real struct field assignment,
                                # once `c`'s real type is known) and the READ
                                # side (already correct) agree on the same
                                # real struct memory.
                                _resolved_ret = self._resolve_sibling_param_ctype(
                                    s.module, sym_info['return_type'])
                                if _resolved_ret:
                                    sym_info['c_return_type'] = _resolved_ret
                                    _ret_changed = True
                            if 'c_return_type' in sym_info:
                                self.func_return_types[sym_name] = sym_info['c_return_type']
                            if sym_info.get('variadic'):
                                # An OVERLOADED sibling name (module_loader's
                                # scan can't represent multiple real
                                # signatures under one name, so it collapses
                                # them to a variadic `name(...)` accepting
                                # any arity — e.g. std/pwd/_macos.mojo's
                                # `_getpw_macos` is defined twice, once per
                                # parameter type) has an intentionally EMPTY
                                # `parameters`/`c_parameters` and a `(...)`
                                # signature — that emptiness is not "zero
                                # arguments", so the parameter-correction
                                # block below (keyed on `parameters`/
                                # `c_parameters` having equal, iterable
                                # length) must never treat it as a genuine
                                # zero-arg function and rebuild `signature`
                                # as `Name ()` (found via std/pwd/pwd.mojo
                                # regressing to "too many arguments to
                                # function ... expected 0, have 1" once the
                                # RETURN type correction below started firing
                                # for these two purely by virtue of returning
                                # a struct, `Passwd`, independent of the
                                # variadic-arity gap). Only rebuild the
                                # signature's RETURN type here, preserving
                                # the `(...)` marker verbatim.
                                if _ret_changed:
                                    sym_info['signature'] = (
                                        f"{sym_info.get('c_return_type', 'int64_t')} "
                                        f"{orig_name} (...)")
                            elif (_sib_is_local_project and not orig_name.startswith('_')
                                    and sym_info.get('c_parameters') is not None
                                    and len(sym_info.get('parameters') or []) == len(sym_info['c_parameters'])
                                    and (sym_info.get('parameters') or _ret_changed)):
                                # (leading-underscore names excluded — see the
                                # matching skip on the return-type correction
                                # above, same dual-extern-declaration reason.)
                                # A sibling function's OWN parameter may be
                                # typed with a struct defined in ITS module
                                # (e.g. base/chest.mojo's `chest_total_count(c:
                                # Chest, item_id: UInt64)`) that THIS file
                                # never itself imports. module_loader's
                                # text-only scan (which computed
                                # sym_info['c_parameters']/['signature']
                                # above, via load_module_from_path) has no
                                # struct-layout knowledge at all and defaults
                                # such a parameter to plain int64_t — while
                                # `Chest`'s own home module (compiled
                                # standalone) resolves it to `Chest *` via its
                                # real struct_field_types. Left uncorrected,
                                # that mismatch propagates into
                                # func_param_types below (this call site's
                                # emitted qualified symbol hashes int64_t,
                                # the real definition hashes `Chest *` — an
                                # undefined-symbol link/dlopen failure), and
                                # even if only the HASH were patched (a prior,
                                # reverted attempt: see bugs/DYLIB_sibling_
                                # import_calls_bind_to_weak_stubs.md's
                                # "follow-on attempt #2"), this file would
                                # still pass a bare int64_t on the call —
                                # `Chest`'s real caller-side construction
                                # would be a null placeholder, corrupting
                                # memory on first field write.
                                #
                                # Fix in place, at the source: resolve each
                                # parameter's REAL Mojo type name (still
                                # available in sym_info['parameters'], unlike
                                # the already-C-typed 'c_parameters') against
                                # the callee's OWN module via
                                # _resolve_sibling_param_ctype below. When it
                                # names a genuine struct there,
                                # _materialize_imported_struct gives THIS
                                # file a real local typedef (fields resolved
                                # the same way _register_imported_structs
                                # resolves any other imported struct's
                                # fields) and this loop corrects
                                # sym_info['c_parameters']/['signature'] to
                                # match — the SAME dict object the extern-
                                # declaration emission (gen_module's
                                # "_emit_stdlib_import_externs"-adjacent pass,
                                # which reads sym_info['signature'] verbatim)
                                # and the func_param_types hash computation
                                # just below both read, so both sides of the
                                # symbol-name agreement AND the actual
                                # calling convention are fixed together, by
                                # construction, not independently patched
                                # (the mistake the reverted attempt made).
                                # Only genuine structs get corrected — a
                                # param that's really a scalar/collection
                                # type, or a struct this compile genuinely
                                # can't find anywhere, is left exactly as
                                # module_loader's scan computed it (an
                                # honest, unresolvable case keeps today's
                                # honest link-failure behavior, never a
                                # guess).
                                # (Also reached, with an empty `parameters`
                                # list, when only the RETURN type changed —
                                # see `_ret_changed` above and its own
                                # docstring-length comment just above this
                                # block for why a zero-argument function like
                                # `Chest_new() -> Chest` still needs its
                                # `signature` text rebuilt here, not only
                                # `c_return_type`.)
                                _new_c_params = []
                                _params_changed = False
                                for (_p_name, _p_raw_type), _c_param in zip(
                                        sym_info.get('parameters') or [],
                                        sym_info['c_parameters']):
                                    _resolved_ctype = self._resolve_sibling_param_ctype(
                                        s.module, _p_raw_type)
                                    if _resolved_ctype:
                                        _c_name = (_c_param.split()[-1]
                                                   if _c_param.strip() else _p_name)
                                        _new_c_params.append(f"{_resolved_ctype} {_c_name}")
                                        _params_changed = True
                                    else:
                                        _new_c_params.append(_c_param)
                                if _params_changed or _ret_changed:
                                    sym_info['c_parameters'] = _new_c_params
                                    _c_ret = sym_info.get('c_return_type', 'int64_t')
                                    _param_str = ', '.join(_new_c_params) if _new_c_params else 'void'
                                    sym_info['signature'] = f"{_c_ret} {orig_name} ({_param_str})"
                            if _sib_qualifier and 'c_parameters' in sym_info:
                                # A local-sibling import bypasses
                                # _emit_stdlib_import_externs (which raised
                                # on this same non-stdlib module name and
                                # gave up before reaching its own
                                # func_param_types population) — the ONLY
                                # other place that sets it. Without this,
                                # _overload_suffix(sym_name) sees no param
                                # types here and hashes '' while the
                                # sibling's OWN standalone compile hashes
                                # its real params, so this call site's
                                # qualified symbol (module_suffix1) and the
                                # sibling's actual definition (module_
                                # suffix2) disagree — an undefined symbol at
                                # link/dlopen time, not just a wrong-value
                                # miscompile.
                                self.func_param_types[sym_name] = [
                                    ' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                                    for cp in (sym_info.get('c_parameters') or [])
                                ]
                        if _sib_qualifier and sym_info:
                            self._note_own_func_home(sym_name, _sib_qualifier)
                    try:
                        if not s.names:
                            # Wildcard import: register all exported symbols
                            for _wc_key, _wc_info in exports.items():
                                _register_sym(_wc_key, _wc_key, _wc_info)
                        else:
                            for name, alias in s.names:
                                sym_name = alias if alias else name
                                sym_info = exports.get(name, {})
                                _register_sym(sym_name, name, sym_info)
                    except Exception:
                        _debug_note('error registering sibling module imports', s.module)
                else:
                    # Gracefully ignore module load errors — but still
                    # record each imported NAME (under its alias, if any)
                    # as *having been imported at all*, even with no real
                    # type info. Without this, `from os import getcwd as
                    # main` (a real, common shape: importing a C-stdlib-
                    # backed module this compiler's own load_module()
                    # doesn't resolve at all — it's scoped to THIS
                    # compiler's own tracked Mojo stdlib/test set, raising
                    # "Only stdlib and test imports supported: os") left
                    # no record whatsoever of 'main' having been imported,
                    # so the "is this call site's `main()` really calling
                    # an aliased IMPORT, or genuinely this module's own
                    # entry point?" check elsewhere (`fname_raw not in
                    # self.imported_symbols`) wrongly concluded "not an
                    # import" and redirected the call to `_gimple_main` —
                    # producing a bogus, wrongly-typed second definition of
                    # the real entry point ("conflicting types for
                    # '_gimple_main'"). Found via tkinter/__main__.py's own
                    # `from . import _test as main; main()` (a relative
                    # import hitting the identical module-load-failure
                    # path here).
                    #
                    # Deliberately NOT added to `self.imported_symbols`
                    # itself: half a dozen OTHER call-lowering checks
                    # (`_lower_opaque_ctor`'s uppercase-constructor guard,
                    # the scalar-ctor guard, both auto-stub-unknown-name
                    # guards) treat "not in imported_symbols" as "safe to
                    # treat this bare name as a locally-stubbable opaque
                    # constructor / auto-stub extern". An entry here has no
                    # real signature behind it, so it doesn't actually
                    # satisfy any of those paths -- it only suppressed
                    # them, leaving calls like `from concurrent.futures
                    # import ProcessPoolExecutor` + `ProcessPoolExecutor(
                    # max_workers=jobs)` (build_stdlib_dylib.py) with NO
                    # declaration at all ("implicit declaration of function
                    # 'ProcessPoolExecutor'" — a real check-selfhost
                    # regression this exact fix introduced the first time
                    # it used `self.imported_symbols` directly). A separate,
                    # narrow set — consulted ONLY by the aliased-main
                    # checks below — fixes the original bug without
                    # touching any of those unrelated call-lowering paths.
                    _debug_note('module load failed while registering imports')
                    if not s.wildcard:
                        for _fb_name, _fb_alias in s.names:
                            _fb_sym = _fb_alias if _fb_alias else _fb_name
                            # `s.module` itself didn't resolve as a package
                            # this compiler tracks, but `_fb_name` may still
                            # independently resolve as a real submodule FILE
                            # on the search path (`_submodule_source_path`
                            # does its own probing, not dependent on `s.
                            # module` having parsed) — same submodule-marker
                            # registration as the `exports is not None`
                            # branch above, so a module-attribute read off
                            # it (`submod.GLOBAL`) still resolves instead of
                            # being marked permanently unresolved.
                            if self._from_import_name_is_submodule(s.module, _fb_name):
                                self.imported_symbols[_fb_sym] = {
                                    'module': f"{s.module}.{_fb_name}",
                                    'return_type': 'unknown',
                                }
                                continue
                            self._unresolved_import_aliases.add(_fb_sym)

        # Register user function return types (from current + imported modules)
        #   Pass 1: annotated return types (authoritative)
        all_functions = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        # 'main' is kept a fixed, unqualified name on purpose
        # (_NO_OVERLOAD_MANGLE) — it's THE program's entry point, renamed to
        # _gimple_main/_{module}_main at emission (see gen_func) and looked
        # up back under the bare key 'main' at every call site that
        # redirects to it (_lower_call, _gen_stmt_ExprStmt). Those bare
        # 'main' lookups into func_param_types/func_return_types (populated
        # by the several passes below that iterate `all_functions` keyed by
        # bare name — Pass 1, Pass 1.3c, the cross-call scalar-contract
        # rebuild, Pass 2, ...) are only ever meant to mean THIS module's own
        # main. But an inlined dependency (do_imports=True whole-program
        # compile) can ALSO define its own top-level `def main():` (e.g. a
        # self-test entry point) — its own FunctionDef node rides along in
        # imported_stmts, appended AFTER stmts, so it's visited LAST and
        # silently overwrites the importing module's own, correctly-
        # registered 'main' entry in these bare-keyed dicts — even though
        # the two modules' `main`s can have completely different
        # arity/return type. A later call site padding missing args from a
        # default (`def main(args=None): ...` called bare as `main()`) then
        # looked up the WRONG (inlined dependency's) arity, found nothing to
        # pad, and emitted a call with too few arguments against the real
        # (correctly-aritied) _gimple_main definition — a hard GCC compile
        # error (BUG-2026-051). An inlined dependency's own main is never
        # called by anyone under the bare name 'main' (the call-site
        # redirect logic is entirely module-local; that dependency's OWN
        # internal self-reference to its own main is compiled by its own
        # private, unshared temp_gen instance — see
        # _compile_imported_module — which has its own, unaffected
        # func_param_types/func_return_types dicts).
        #
        # `_is_foreign_main` guards ONLY the specific dict-population sites
        # below (Pass 1, Pass 1.3c, the scalar-contract rebuild) — it does
        # NOT filter `all_functions` itself. `all_functions` is also the
        # source list for the cross-call scalar-contract pass's call-site
        # scan (`_caller_bodies`, a few hundred lines down), which walks
        # every function body — including main's — looking for calls whose
        # argument types can pin down an unannotated callee parameter (e.g.
        # `jit_compile_and_execute`'s own `src` param). Self-hosting this
        # very file (do_imports=True compiling mojo.py, which imports
        # gimple_codegen.py, myinterpreter.py, driver.py, jit/arm64.py — a
        # genuinely circular dependency graph) means mojo.py's OWN real
        # `main` (the one whose body contains the ONE call site to
        # `jit_compile_and_execute`) legitimately rides along in more than
        # one of those modules' own `imported_stmts` too, structurally
        # unequal to whatever THIS particular temp_gen's own `stmts` holds
        # (each module's own compile parses/rewrites independently). Actually
        # dropping such an entry out of `all_functions` (an earlier version
        # of this fix did exactly that) starved the scalar-contract scan of
        # that one real call site in some module compiles, silently
        # regressing `jit_compile_and_execute`'s inferred `src` type back to
        # the naive `int64_t` default — caught by `make check-selfhost`
        # (`build/system.o`'s two conflicting `jit_compile_and_execute`
        # declarations). Guarding only the dict writes (which must stay
        # module-local to fix BUG-2026-051) leaves the call-site scan
        # untouched (harmless to see the same real call once per module that
        # happens to carry a copy of it — same evidence, same conclusion).
        def _is_foreign_main(s):
            return isinstance(s, FunctionDef) and s.name == 'main' and s not in stmts
        for s in all_functions:
            if _is_foreign_main(s):
                continue
            if isinstance(s, FunctionDef) and s.return_type is not None:
                self.func_return_types[s.name] = self._resolve_type(s.return_type)
            # Register parameter types (for call-site coercion via _emit_call)
            if isinstance(s, FunctionDef) and s.params:
                if any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                    self._note_vararg_trailing_param_types(s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params]
            # Record free-function param DEFAULTS keyed by the mangled name, so
            # a call site that omits an argument can pad with the real default
            # (`def greet(name: String = "world")` called as `greet()`) instead
            # of NULL/0. `param_defaults` maps param name -> default expr AST.
            if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
                _dflts = getattr(s, 'param_defaults', None) or {}
                if _dflts:
                    # `s` ranges over ALL_FUNCTIONS (this module's own stmts
                    # PLUS every transitively-inlined foreign FunctionDef —
                    # see all_functions' own construction above), not just
                    # bare-name-callable functions of THIS module. A foreign
                    # function whose bare name is _AMBIGUOUS_FUNC_HOME (two
                    # different sibling modules transitively inlined here
                    # each define a same-named top-level function — e.g.
                    # os.py inlining both posixpath.py's and ntpath.py's own
                    # `relpath(path, start=None)` via its `if 'posix' in
                    # _names: import posixpath as path / elif 'nt' in
                    # _names: import ntpath as path` branch, neither of
                    # which this prepass can statically pick between) would
                    # make `_func_csym` raise here — even though this is
                    # only building an auxiliary lookup TABLE keyed by the
                    # mangled name, not a genuine bare-name call-site
                    # reference. If `s`'s bare name is never actually called
                    # unqualified anywhere in this compile unit, this table
                    # entry is simply never looked up, so skipping it is
                    # harmless; if it IS genuinely bare-called somewhere,
                    # THAT call site's own `_func_csym`/`_func_qualifier`
                    # resolution still raises the same honest refusal (this
                    # guard does not touch that path, only this prepass's
                    # own indexing). Mirrors the identical, already-
                    # established guard on the sibling `_func_kwargs_slot`
                    # registration a few lines below.
                    try:
                        _mangled = self._func_csym(s.name)
                    except Exception:
                        _mangled = None
                    if _mangled:
                        self._func_param_defaults[_mangled] = [
                            (pn, _dv) for pn, _dv in _dflts.items()]
            # Record the `**kwargs` slot so a call site with literal keyword
            # arguments can pack them into a real dict — see _func_kwargs_slot.
            # The C-signature index is the DECLARATION index: `*args` collapses
            # to exactly one MojoList* slot when a `**kwargs` follows it (see
            # _param_ctypes_for's has_kw pass-through), so positions line up.
            if isinstance(s, FunctionDef):
                _kw_i = -1
                _ci = 0
                _seen_star = False
                for _pn, _pt in (s.params or []):
                    if _pn.startswith('**'):
                        _kw_i = _ci
                        break
                    if _pn.startswith('*'):
                        if _seen_star:
                            continue
                        _seen_star = True
                    _ci += 1
                if _kw_i >= 0:
                    self._func_kwargs_slot[s.name] = _kw_i
                    self._func_kwargs_has_vararg[s.name] = _seen_star
                    try:
                        _mangled_kw_name = self._func_csym(s.name)
                        self._func_kwargs_slot[_mangled_kw_name] = _kw_i
                        self._func_kwargs_has_vararg[_mangled_kw_name] = _seen_star
                    except Exception:
                        pass
            # A genuine user free function (FunctionDef node, not a libc extern):
            # eligible for overload-mangling its C symbol by parameter types.
            if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
                self._mangled_funcs.add(s.name)
            # @export: callable from C under its plain Mojo name — never
            # overload-mangled (mirrors the _static_methods decorator-read
            # pattern below, for the free-function case).
            if isinstance(s, FunctionDef) and 'export' in (getattr(s, 'decorators', None) or []):
                self._extra_no_mangle.add(s.name)

        # Collect "memoize on the function object" attribute assignments —
        # Python's `def f(): ...; cached = getattr(f, "_cached", None); ...;
        # f._cached = cached; return cached` idiom (jit/arm64.py's own
        # `_toolchain_id`/`_compiler_id`, first reached via BUG-2026-049's
        # fix: `import jit.arm64` is a dotted import, previously never
        # resolved/compiled at all — see that bug's fix notes). `f.attr = ..`
        # used to fall through to `_lower_MemberExpr`'s "C function name used
        # as a value" special case (a function name can't be a bare rvalue
        # under -fgimple, so it's boxed as a `void *` via a pre-declared
        # `_funcptr_...` static) — `f.attr = ..` then tried to treat that
        # `void *` as a STRUCT POINTER and write through a `.attr` member,
        # which GCC correctly rejects ("request for member in something not
        # a structure or union"): a function has no real fields to write.
        # Mirrors `_class_attrs` (StructDef class-body attributes, just
        # above) exactly, but for a FREE FUNCTION's own attribute instead of
        # a struct's: redirect to a synthesized global variable
        # (`_funcattr_{func}__{attr}`) rather than inventing a new storage
        # mechanism. Unlike `_class_attrs`, there's no class-body literal to
        # read an initial value/type from — the attribute doesn't exist
        # until the function's OWN body assigns it at runtime — so every
        # such global is simply declared `int64_t` (boxed, zero-initialized
        # by C's own static default), matching this file's existing
        # "unknown/dynamic global boxed as int64_t" convention used
        # pervasively elsewhere (see _lower_IdentExpr's global-read
        # docstring). Must recurse into EVERY body shape a function can
        # contain (If/Try/While/For), not just its top-level statements —
        # `_toolchain_id._cached = cached` sits at top level here, but the
        # general pattern (e.g. inside a `try:`) must still be found.
        _own_top_level_func_names = {s.name for s in stmts if isinstance(s, FunctionDef)}

        def _scan_func_body_for_self_attr(fname, body):
            for _fstmt in body:
                if (isinstance(_fstmt, AssignStmt)
                        and isinstance(_fstmt.target, MemberExpr)
                        and isinstance(_fstmt.target.obj, IdentExpr)
                        and _fstmt.target.obj.name == fname):
                    attr = _fstmt.target.member
                    self._func_attrs.setdefault(fname, {})
                    if attr not in self._func_attrs[fname]:
                        mangled = f"_funcattr_{fname}__{attr}"
                        self._func_attrs[fname][attr] = mangled
                        self._global_var_types.setdefault(mangled, 'int64_t')
                        self._global_c_decl_types.setdefault(mangled, 'int64_t')
                elif isinstance(_fstmt, FunctionDef):
                    pass  # a nested def's own `f.attr` (if any) is scanned when THAT def is visited below
                elif isinstance(_fstmt, IfStmt):
                    _scan_func_body_for_self_attr(fname, _fstmt.then_body)
                    for _, _eb in _fstmt.elifs:
                        _scan_func_body_for_self_attr(fname, _eb)
                    if _fstmt.else_body:
                        _scan_func_body_for_self_attr(fname, _fstmt.else_body)
                elif isinstance(_fstmt, (WhileStmt, ForStmt, TryStmt)):
                    _scan_func_body_for_self_attr(fname, _fstmt.body)

        for s in stmts:
            if isinstance(s, FunctionDef) and s.name in _own_top_level_func_names:
                _scan_func_body_for_self_attr(s.name, s.body)

        #   Pass 1b: struct method annotated return types + param types (from current + imported modules)
        all_structs_for_methods = (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
                                    + self._imported_typedef_structs)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    mangled = f"{s.name}_{m.name}"
                    if m.return_type is not None:
                        self.func_return_types[mangled] = self._resolve_type(m.return_type)
                    # Track @staticmethod methods so call sites don't pass cls arg
                    if hasattr(m, 'decorators') and 'staticmethod' in (m.decorators or []):
                        self._static_methods.add(mangled)
                    # Track REAL classmethods (explicit @classmethod, or the
                    # two dunders Python makes implicit classmethods without
                    # the decorator) — see _classmethod_names' own docstring
                    # at its declaration for why _lower_method_call needs
                    # this instead of trusting any parameter literally named
                    # `cls`.
                    if ((hasattr(m, 'decorators') and 'classmethod' in (m.decorators or []))
                            or m.name in ('__init_subclass__', '__class_getitem__')):
                        self._classmethod_names.add(mangled)
                    # Also store method param types using the mangled name (for call-site arg padding)
                    if m.params:
                        ctypes = []
                        for i, (pn, pt) in enumerate(m.params):
                            if i == 0 and pn == 'self':
                                ctypes.append(f"{s.name} *")
                            else:
                                ctypes.append(self._param_ctype(pn, pt, m))
                        # Don't overwrite hardcoded entries (e.g. Scope_define uses char* for name)
                        if mangled not in self.func_param_types:
                            self.func_param_types[mangled] = ctypes

        #   Pass 2: infer return types for unannotated functions using
        #           already-seeded func_return_types for callee types
        for s in all_functions:
            if _is_foreign_main(s):
                continue
            if isinstance(s, FunctionDef) and s.return_type is None:
                # Seed param types so _quick_type works for param names.
                # `*args`/`**kwargs` are seeded under their BARE name (the
                # body refers to `kw`, never `**kw`) and with the concrete
                # container type gen_func gives them — otherwise `return kw`
                # inferred the int64_t default and the caller read a
                # MojoDict * back as a MojoList *.
                for pname, ptype in s.params:
                    if pname.startswith('**'):
                        self.var_types[pname[2:]] = 'MojoDict *'
                    elif pname.startswith('*'):
                        self.var_types[pname[1:]] = 'MojoList *'
                    else:
                        self.var_types[pname] = self._resolve_type(ptype)
                inferred = self._infer_return_type(s.body)
                # Special case: main() should return int, not void
                if s.name == 'main' and inferred == 'void':
                    inferred = 'int64_t'
                self.func_return_types[s.name] = inferred
                self.var_types.clear()

        #   Pass 2b: infer return types for unannotated struct methods
        # Run to fixpoint: callee return types discovered in one round improve
        # inference for callers in the next round (handles forward calls like
        # Parser._parse_stmt calling Parser._parse_comptime).
        for _pass2b_iter in range(4):
            _changed = False
            for s in all_structs_for_methods:
                if isinstance(s, StructDef):
                    for m in s.methods:
                        # Real method names, straight from the struct's own
                        # AST -- the ONE authoritative "is `x` a method (not
                        # a field)" signal for this struct. Needed because
                        # `struct_field_types[name]` alone can't be trusted
                        # for that question: `_scan_body_for_local_field_
                        # access` (this same pre-pass, below) synthesizes a
                        # phantom `'int'`-typed FIELD entry for ANY
                        # `<known-struct local>.<unrecognized member>` read
                        # found anywhere in the module (dynamic-attribute
                        # support) -- including a bound-method-as-VALUE read
                        # like `getpos = self.tell`/`data.tell` (see
                        # bugs/hard/CODEGEN_generator_lambda_expr_
                        # unsupported.md), which would otherwise get
                        # mistaken for a genuine field the moment that scan
                        # runs (it always does, unconditionally, for every
                        # module). Consulted by `_cpp_expr`'s/`_cpp_stmt`'s
                        # coroutine-body bound-method-as-value handling.
                        self._struct_method_names.setdefault(s.name, set()).add(m.name)
                        if m.name == '__init__':
                            self._struct_has_init.add(s.name)
                            # Record __init__ param names (excl self) so a
                            # keyword-arg constructor call (Counter(start=...))
                            # binds kwargs to the right __init__ parameters.
                            self._struct_init_params[s.name] = [
                                pn for pn, _pt in m.params if pn != 'self']
                            _init_defaults = getattr(m, 'param_defaults', {}) or {}
                            self._struct_init_defaults[s.name] = {
                                pn: dv for pn, dv in _init_defaults.items() if pn != 'self'}
                        if m.return_type is None:
                            for i, (pname, ptype) in enumerate(m.params):
                                if pname == 'self':
                                    self.var_types[pname] = f"{s.name} *"
                                else:
                                    self.var_types[pname] = self._resolve_type(ptype)
                            inferred = self._infer_return_type(m.body)
                            key = f"{s.name}_{m.name}"
                            if self.func_return_types.get(key) != inferred:
                                self.func_return_types[key] = inferred
                                _changed = True
                            self.var_types.clear()
            if not _changed:
                break


        #   Pass 2c: infer container RETURN ELEMENT types to a fixpoint, so a
        #   call site emitted before the callee's own body (the common
        #   self-host order — lower_expr dispatches to the _lower_* helpers
        #   defined after it) still sees the callee's tuple/list return
        #   element type. Populated statically here before any body is
        #   emitted; _gen_stmt_ReturnStmt's dynamic recording stays as a
        #   fallback for shapes this syntactic scan can't resolve.
        for _pass2c_iter in range(8):
            _c_changed = False
            for s in all_functions:
                if _is_foreign_main(s) or not isinstance(s, FunctionDef):
                    continue
                _ret_elem = self._infer_return_elem_type(s.body, func_def=s)
                if _ret_elem is not None and self._return_elem_types.get(s.name) != _ret_elem:
                    self._return_elem_types[s.name] = _ret_elem
                    _c_changed = True
            for s in all_structs_for_methods:
                if isinstance(s, StructDef):
                    self._prepass_struct = s.name
                    for m in s.methods:
                        if m.name == '__init__':
                            continue
                        _ret_elem = self._infer_return_elem_type(m.body)
                        _key = f"{s.name}_{m.name}"
                        if _ret_elem is not None and self._return_elem_types.get(_key) != _ret_elem:
                            self._return_elem_types[_key] = _ret_elem
                            _c_changed = True
            self._prepass_struct = None
            if not _c_changed:
                break

        # ── Pass 2b-bis: register per-struct-method overload candidates ────
        # Static/syntactic (arity range + C param types), so no fixpoint needed —
        # a single pass over every struct's own methods (including any
        # @fieldwise_init-synthesized __init__, since that's already a real
        # FunctionDef in s.methods by the time the parser hands stmts to us).
        # Used by _lower_struct_constructor/_lower_struct_method_call to pick
        # the right overload instead of guessing an unsuffixed symbol name.
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                _moids = self._struct_method_overload_ids(s)
                for m, _oid in zip(s.methods, _moids):
                    _has_self_first = bool(m.params) and m.params[0][0] == 'self'
                    _params_no_self = m.params[1:] if _has_self_first else m.params
                    # A `*args: *Ts` pack param (single '*', not '**') consumes
                    # every call-site positional arg from its position onward —
                    # everything named after it in Mojo syntax is necessarily
                    # keyword-only. Treating it (as the old real_params filter
                    # below did) as contributing NOTHING to arity meant a call
                    # with more positional args than the struct's OTHER,
                    # non-variadic overloads could ever match would find no
                    # survivor in _resolve_overload and fall through to a bare,
                    # never-defined symbol (confirmed via String's *args:
                    # *Ts-typed Writable constructor and DeviceGraphBuilder.
                    # add_function's *Ts-typed overloads in the real stdlib).
                    _star_idx = next((i for i, (pn, _pt) in enumerate(_params_no_self)
                                       if pn.startswith('*') and not pn.startswith('**')), None)
                    # A `**kwargs`-style param (double star) MUST stay in
                    # real_params/param_names: _build_call_args_for_candidate
                    # locates its slot by scanning param_names for a '**'-
                    # prefixed entry (to pack literal keyword args into a
                    # real MojoDict there) and param_ctypes already carries
                    # a real 'MojoDict *' slot for it (_signature_ctypes
                    # only strips the *args pack's OWN sentinel, never a
                    # **kwargs one). Dropping it here (the old filter
                    # stripped ANY '*'-prefixed name, single or double star)
                    # desynced param_names/max_arity from param_ctypes by
                    # exactly one slot — the resolved overload's call sites
                    # then never emitted an argument for that trailing
                    # MojoDict* param at all, a hard "too few arguments"
                    # compile error (e.g. tkinter/font.py's `Font.__init__
                    # (self, root=None, font=None, name=None, exists=False,
                    # **options)` called as `Font(name=.., exists=True,
                    # root=..)`).
                    real_params = [(pn, pt) for pn, pt in _params_no_self
                                   if not (pn.startswith('*') and not pn.startswith('**'))]
                    _defaults = m.param_has_default or {}
                    if _star_idx is not None:
                        _pre_star = _params_no_self[:_star_idx]
                        min_arity = sum(1 for pn, _pt in _pre_star if pn not in _defaults)
                        max_arity = float('inf')
                    else:
                        # A `**kwargs` slot is never itself required (real
                        # Python: `f()` is always valid even when `f` takes
                        # `**kwargs`) — exclude it from min_arity, but it
                        # still occupies one real slot in max_arity (a
                        # concrete MojoDict* parameter in the C signature).
                        min_arity = sum(1 for pn, _pt in real_params
                                         if pn not in _defaults and not pn.startswith('**'))
                        max_arity = len(real_params)
                    _all_ctypes = self._signature_ctypes(m.params, m, s.name)
                    param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                    if _star_idx is not None:
                        # Drop the pack's own sentinel entry ('...', from the
                        # default _signature_ctypes sentinel) so param_ctypes
                        # stays aligned with param_names/real_params, which
                        # already exclude the pack's own name.
                        param_ctypes = [c for c in param_ctypes if c != '...']
                    # Compute this overload's own return type here, rather than
                    # reading func_return_types[f"{struct}_{method}{overload_id}"]
                    # at the call site later: that key is only populated when
                    # THIS overload's own body gets emitted (Phase 2a, in
                    # declaration order), so a call from an earlier-processed
                    # sibling overload's body into this one would see nothing
                    # yet and silently default to int64_t. Mirrors the logic
                    # in _gen_struct_method (return-type resolution + the
                    # pointer-family self-referencing-generic special case).
                    if m.return_type is not None:
                        _ret_base = m.return_type.split('[', 1)[0].strip() if isinstance(m.return_type, str) else ''
                        if (_ret_base == s.name
                                and s.name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer')):
                            _ret_type = f"{s.name} *"
                        else:
                            _ret_type = self._resolve_type(m.return_type)
                    else:
                        _saved_var_types = dict(self.var_types)
                        self.var_types['self'] = f"{s.name} *"
                        for _pn, _pt in real_params:
                            self.var_types[_pn] = self._resolve_type(_pt)
                        _ret_type = self._infer_return_type(m.body)
                        self.var_types = _saved_var_types
                    key = (s.name, m.name)
                    self._struct_method_signatures.setdefault(key, []).append({
                        'overload_id': _oid,
                        'param_names': [pn for pn, _pt in real_params],
                        'param_ctypes': param_ctypes,
                        'min_arity': min_arity,
                        'max_arity': max_arity,
                        'ret_type': _ret_type,
                        'has_varargs': _star_idx is not None,
                        'pre_star_count': _star_idx if _star_idx is not None else None,
                    })
                    # Also register this overload's full param signature (incl.
                    # self) in _mangled_signature_ctypes — NOT func_param_types
                    # (see that dict's own comment for why: writing this same
                    # info into func_param_types early was tried and reverted,
                    # confirmed to change codegen elsewhere in ways not limited
                    # to argument coercion). _emit_call reads this dict as a
                    # fallback so a call to a not-yet-emitted sibling overload
                    # (Phase 2a processes s.methods in declaration order) still
                    # gets its arguments coerced correctly — confirmed fixing
                    # std/ffi/__init__.mojo's DLHandle.get_symbol
                    # kwarg-forwarding call, which regressed without this.
                    self._mangled_signature_ctypes[f"{s.name}_{m.name}{_oid}"] = _all_ctypes

        # Imported structs (_register_imported_structs): no body is emitted for
        # these here — the real definition lives in the struct's home module,
        # compiled separately (e.g. into build/libmojostdlib.dylib). Emit an
        # `extern` for each of their methods now that the loop above has
        # resolved its real mangled name/return type/param types, so calls
        # route to the actual linked symbol instead of the generic scalar-
        # method stub in _lower_struct_method_call.
        for s in self._imported_typedef_structs:
            if not s.methods:
                continue
            for _oid, m in zip(self._struct_method_overload_ids(s), s.methods):
                bare_mangled = f"{s.name}_{m.name}{_oid}"
                mangled = self._struct_method_csym(s.name, m.name, _oid)
                # _mangled_signature_ctypes is keyed by the BARE form (Pass
                # 2b-bis populates it before any qualifier is known) — look
                # up under that key regardless of what mangled resolved to.
                param_ctypes = self._mangled_signature_ctypes.get(bare_mangled)
                if param_ctypes is None:
                    continue
                # The suffixed func_return_types[mangled] key is only ever
                # populated when a struct's OWN method body is emitted
                # (Phase 2a) — which never happens here, since no body is
                # available for an imported struct. Pull the return type from
                # _struct_method_signatures instead (populated for every
                # struct in all_structs_for_methods regardless of emission).
                ret_type = None
                for _cand in self._struct_method_signatures.get((s.name, m.name), []):
                    if _cand.get('overload_id') == _oid:
                        ret_type = _cand.get('ret_type')
                        break
                if ret_type is None:
                    ret_type = self.func_return_types.get(f"{s.name}_{m.name}", 'void' if m.name == '__init__' else 'int64_t')
                # A "..." entry mid-list (e.g. a *args/**kwargs-style param)
                # is a bookkeeping placeholder in _mangled_signature_ctypes,
                # not literal C — splicing it in as-is produces invalid syntax
                # like `(T *, ..., int64_t)`. Fall back to a fully variadic
                # signature whenever that marker appears anywhere.
                if any('...' in p for p in param_ctypes):
                    params_str = '...'
                else:
                    params_str = ', '.join(param_ctypes) or 'void'
                sig = f"{ret_type} {mangled} ({params_str})"
                guard = _stub_guard_name(mangled)
                decl = f"#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif"
                if decl not in self._elaborated_externs:
                    self._elaborated_externs.append(decl)
                # Call-site overload resolution (_resolve_overload) can fail
                # to confidently pick a candidate (e.g. a bracketed type
                # argument like get_symbol[NoneType] it can't match) and
                # falls back to the bare, unsuffixed mangled name even when
                # the method IS overloaded — declare that variadic fallback
                # too, mirroring the auto-stub pattern _lower_struct_method_call
                # already uses elsewhere for genuinely-unknown methods.
                if _oid:
                    # "bare" here means no OVERLOAD-HASH suffix (the call
                    # site's own unresolved-overload fallback, per
                    # _lower_struct_method_call's `self._struct_method_csym(
                    # struct_name, method, '')`) — still module-qualified,
                    # for the same reason every other decl in this loop is.
                    no_oid = self._struct_method_csym(s.name, m.name, '')
                    bare_guard = _stub_guard_name(no_oid)
                    bare_decl = f"#ifndef {bare_guard}\n#define {bare_guard}\nextern {ret_type} {no_oid} (...);\n#endif"
                    if bare_decl not in self._elaborated_externs:
                        self._elaborated_externs.append(bare_decl)

        # ── Pass 1.3: Infer parameter types from usage ─────────────────────
        # For parameters without type annotations, infer from member accesses
        self._inferred_param_types: dict[str, dict[str, str]] = {}  # func_name -> {param_name -> type}
        for s in all_functions:
            if isinstance(s, FunctionDef):
                self._inferred_param_types[s.name] = self._infer_param_types(s)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    key = f"{s.name}_{m.name}"
                    self._inferred_param_types[key] = self._infer_param_types(m)

        # ── Pass 1.3b: Infer local variable types from assignments ──────────
        # Scan all assignments to determine variable types; use int64_t for
        # variables that receive 64-bit values (list elements, arithmetic results)
        self._inferred_var_types: dict[str, dict[str, str]] = {}  # func_name -> {var_name -> type}
        for s in all_functions:
            if isinstance(s, FunctionDef):
                self._inferred_var_types[s.name] = self._infer_local_var_types(s)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    key = f"{s.name}_{m.name}"
                    self._inferred_var_types[key] = self._infer_local_var_types(m)

        # ── Pass 1.3c: Populate func_param_types for all user functions ────────
        # CRITICAL: Must happen before Phase 2a (code generation) so that call-site
        # argument coercion has the correct expected parameter types. Otherwise,
        # _emit_call defaults to converting pointers to int64_t, losing type info.
        for s in all_functions:
            if _is_foreign_main(s):
                continue
            if isinstance(s, FunctionDef):
                if s.params and any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                    self._note_vararg_trailing_param_types(s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    method_full_name = f"{s.name}_{m.name}"
                    # Don't clobber a deliberately-hardcoded entry (see
                    # `_selfhost_locked_param_types`'s own comment) with
                    # this pass's own weaker signature inference.
                    if method_full_name in self._selfhost_locked_param_types:
                        continue
                    if m.params and any(pn.startswith('*') for pn, _ in m.params):
                        self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, s.name)
                    else:
                        param_ctypes = []
                        for i, (pname, ptype) in enumerate(m.params):
                            if pname.startswith('**'):
                                continue  # skip **kwargs
                            if pname == 'self':
                                param_ctypes.append(f"{s.name} *")
                            else:
                                param_ctypes.append(self._param_ctype(pname, ptype, m))
                        self.func_param_types[method_full_name] = param_ctypes

        # ── Pass 1.3c2: Patch GimpleGen func_param_types from inference ─────
        # _param_ctype uses bare method name as key for _inferred_param_types,
        # but struct methods are keyed by "{struct}_{method}".  Fixup: scan
        # GimpleGen methods and upgrade stale int64_t entries where inference
        # knows a pointer type.  Scoped to GimpleGen only — other struct
        # inferences may be wrong.
        for s in all_structs_for_methods:
            if not (isinstance(s, StructDef) and s.name == 'GimpleGen'):
                continue
            for m in s.methods:
                mangled = f"GimpleGen_{m.name}"
                fpt = self.func_param_types.get(mangled)
                inferred = self._inferred_param_types.get(mangled)
                if not fpt or not inferred:
                    continue
                idx = 0
                for pname, ptype in (m.params or []):
                    if pname.startswith('**') or pname.startswith('*') and pname != 'self':
                        continue
                    if pname == 'self':
                        idx += 1
                        continue
                    if idx < len(fpt) and pname in inferred and fpt[idx] == 'int64_t':
                        fpt[idx] = inferred[pname]
                    idx += 1

        # ── Pass 1.3d: cross-call element-type contract ────────────────────
        # A container's element type lives in side-tables keyed by SSA name and
        # does not survive a call boundary, so a callee that indexes a passed-in
        # container falls back to int getters and silently corrupts non-int
        # payloads. Propagate it: where a caller passes a container whose element
        # types we can derive, record them onto the callee's parameter. Free
        # functions only for now (methods carry a `self` and are handled via
        # struct fields). Conflicting call sites collapse to unknown.
        self._param_elem_types: dict[str, dict[str, tuple]] = {}
        _free_params = {s.name: [pn for pn, _ in (s.params or []) if not pn.startswith('*')]
                        for s in all_functions if isinstance(s, FunctionDef)}

        def _record_param_elem(callee, pname, e, ne):
            d = self._param_elem_types.setdefault(callee, {})
            if pname in d and d[pname] != (e, ne):
                d[pname] = (None, None)   # conflicting call sites → unknown
            else:
                d[pname] = (e, ne)

        # Cross-call scalar contract: an unannotated scalar param defaults to the
        # int64_t machine word, so passing a double silently truncates (bnbody's
        # dt=0.01 -> 0 froze the sim). Observe each call argument's scalar type and
        # propagate a unanimous concrete one (double) onto the callee's param. A
        # function name -> def map lets us skip annotated params.
        #
        # Same mechanism also carries pointer-shaped evidence (char *) — an
        # unannotated param that is merely held/returned (no body-usage evidence
        # at all, e.g. `def g(a): return a`) got no entry from _infer_param_types
        # above and defaulted to int64_t, so calling it with a string argument
        # (`g("ab")`) compiled the identity function as returning int64_t: the
        # correct char* pointer value silently reinterpreted as an integer and
        # printed as garbage. See bugs/CODEGEN_untyped_param_string_passthrough_wrong.md.
        # Reuses this exact observe-per-call-site/apply-if-unanimous contract
        # (rather than adding a third narrow body-usage special case alongside
        # the map() one above) since the evidence here is inherently about the
        # CALL SITE, not the function body.
        _fn_by_name = {s.name: s for s in all_functions if isinstance(s, FunctionDef)}
        _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}

        def _arg_scalar_type(caller_name, a):
            if isinstance(a, FloatLiteral):
                return 'double'
            if isinstance(a, StringLiteral):
                return 'char *'
            if isinstance(a, IdentExpr):
                t = (self._inferred_var_types.get(caller_name, {}).get(a.name)
                     or self._inferred_param_types.get(caller_name, {}).get(a.name))
                return t
            return None

        # Observe call sites both inside every function body AND at module top
        # level (`_TOPLEVEL_CALLER`) — a call like `print(g("ab"))` sitting
        # directly in module-level code (not inside any `def`) is otherwise
        # invisible to this analysis entirely, since it only walked
        # `all_functions`' bodies. `_TOPLEVEL_CALLER` is a name no real Mojo
        # function can have (leading `<`), so _inferred_var_types/_inferred_
        # param_types lookups for it simply miss (harmless) rather than
        # colliding with a real function's per-name entries.
        _TOPLEVEL_CALLER = '<toplevel>'
        _caller_bodies = [(s.name, s.body) for s in all_functions if isinstance(s, FunctionDef)]
        _caller_bodies.append((_TOPLEVEL_CALLER, stmts))
        for caller_name, body in _caller_bodies:
            elem, nested, _ = self._scan_container_elems(body)
            calls = []
            self._calls_in_stmts(body, calls)
            for call in calls:
                if not isinstance(call.func, IdentExpr):
                    continue
                callee = call.func.name
                pnames = _free_params.get(callee)
                if not pnames:
                    continue
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    if isinstance(a, IdentExpr) and a.name in elem:
                        _record_param_elem(callee, pnames[i],
                                            elem[a.name], nested.get(a.name))
                    st = _arg_scalar_type(caller_name, a)
                    if st:
                        _scalar_obs.setdefault(callee, {}).setdefault(pnames[i], set()).add(st)

        # Apply: a unanimous concrete double (or char *) observed across all call
        # sites of an unannotated, weakly-defaulted param becomes that param's type.
        for callee, pmap in _scalar_obs.items():
            fn = _fn_by_name.get(callee)
            if not fn:
                continue
            ann = {pn: pt for pn, pt in (fn.params or [])}
            for pname, types in pmap.items():
                if types not in ({'double'}, {'char *'}):
                    continue                         # not unanimous double / char *
                if ann.get(pname) is not None:
                    continue                         # respect explicit annotation
                cur = self._inferred_param_types.get(callee, {}).get(pname)
                if cur in (None, 'int', 'int64_t'):
                    # types is exactly {'double'} or {'char *'} here (checked
                    # above) — pick without next(iter(...)): a self-hosted
                    # build of this very file (`make check-selfhost`) failed to
                    # link with an undefined `_next` symbol when this used
                    # `next(iter(types))`, since gimple_codegen.py's own
                    # compiled-path lowering of the `next()` builtin over a
                    # freshly-constructed set iterator doesn't cover this
                    # shape.
                    resolved_type = 'double' if types == {'double'} else 'char *'
                    self._inferred_param_types.setdefault(callee, {})[pname] = resolved_type

        # Rebuild free-function param-type signatures so call-site coercion sees
        # the propagated scalar types (this must follow the propagation above).
        for s in all_functions:
            if _is_foreign_main(s):
                continue
            if isinstance(s, FunctionDef):
                if s.params and any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                    self._note_vararg_trailing_param_types(s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []

        # ── Pass 1.3d-ctor: constructor call-site scalar contract, IdentExpr
        # args (bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
        # int64.md). The EARLY pass above (self._ctor_lit_param_types, run
        # before the struct-field-collection loop that locks in every field's
        # C type) only sees DIRECT LITERAL constructor arguments
        # (`Widget("hello")`), because it necessarily runs before
        # self._inferred_var_types exists — a variable-argument call site
        # (`s = "hello"; w = Widget(s)`) was invisible to it, leaving the
        # field wrongly typed int64_t (a raw pointer printed as a decimal
        # integer). Now that Pass 1.3b (above) has populated
        # self._inferred_var_types, redo the same observe/apply contract,
        # reusing `_arg_scalar_type`/`_caller_bodies` (the exact helpers
        # Pass 1.3d's free-function version just above used) so IdentExpr
        # arguments contribute real evidence too. This is a RECONCILIATION,
        # not a reorder of the earlier, already-working pass: it runs before
        # any C struct typedef / code text has been emitted (typedef
        # emission is Phase 2, well below in this method), so patching
        # self.struct_field_types here still lands before that dict is ever
        # read for codegen — there is no already-emitted C text to fix up.
        _ctor_scalar_obs: dict[str, dict[str, set]] = {}   # struct -> {pname -> {types}}
        for caller_name, body in _caller_bodies:
            calls = []
            self._calls_in_stmts(body, calls)
            for call in calls:
                if not isinstance(call.func, IdentExpr):
                    continue
                struct_name = call.func.name
                pnames = _ctor_init_params.get(struct_name)
                if not pnames:
                    continue
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    st = _arg_scalar_type(caller_name, a)
                    if st:
                        _ctor_scalar_obs.setdefault(struct_name, {}).setdefault(
                            pnames[i], set()).add(st)

        for struct_name, pmap in _ctor_scalar_obs.items():
            _init = _ctor_init_methods.get(struct_name)
            if not _init:
                continue
            _ann = {pn: pt for pn, pt in (_init.params or [])}
            _init_defaults = getattr(_init, 'param_defaults', {}) or {}
            for pname, types in pmap.items():
                if types not in ({'double'}, {'char *'}):
                    continue                        # not unanimous double / char *
                if _ann.get(pname) is not None:
                    continue                        # respect explicit annotation
                if pname in _init_defaults:
                    continue                        # respect default-value inference
                resolved_type = 'double' if types == {'double'} else 'char *'
                self._ctor_lit_param_types.setdefault(struct_name, {})[pname] = resolved_type
                # Patch the struct field(s) this param feeds via a direct
                # `self.field = param` assignment in __init__'s own body —
                # avoid `next(gen, default)` here for the exact same reason
                # the neighboring passes' comments already document (a
                # self-hosted build failed to link with an undefined `_next`
                # symbol the last time that pattern was used over a freshly-
                # built generator); use an explicit loop instead.
                for node in _walk_ast(_init.body):
                    if not isinstance(node, AssignStmt):
                        continue
                    tgt = node.target
                    if not (isinstance(tgt, MemberExpr) and isinstance(tgt.obj, IdentExpr)
                            and tgt.obj.name == 'self'):
                        continue
                    v = node.value
                    if isinstance(v, IdentExpr) and v.name == pname:
                        _fld_types = self.struct_field_types.setdefault(struct_name, {})
                        if _fld_types.get(tgt.member) in (None, 'int', 'int64_t'):
                            _fld_types[tgt.member] = resolved_type

        # ── Pass 1.3d-gen: compiled-generator eligibility/compile attempt ──
        # Deliberately placed HERE — after the cross-call scalar contract
        # above has fully populated self._inferred_param_types — rather than
        # at the top of gen_module where an earlier revision of this pass
        # used to run. _gen_cpp_generator_unit's parameter-type refusal check
        # (`ctype not in ('int64_t', 'double', '_Bool')`) calls
        # self._param_ctype for each unannotated parameter, which itself
        # consults self._inferred_param_types when present (see
        # _param_ctype's "Check inferred parameter types first" branch) —
        # but running the generator compile attempt before that dict even
        # existed meant every unannotated generator parameter fell straight
        # through to _resolve_type(None)'s naive int64_t default with NO
        # cross-call-site evidence at all, unlike every ordinary (non-
        # generator) unannotated parameter, which already benefits from this
        # exact inference. A generator like `def g(s): yield s` called as
        # `g("hi")` was silently compiled with `s` (and the coroutine
        # promise's `current_value`) typed `int64_t` instead of being
        # honestly refused — a char*/MojoStr* pointer value stored into and
        # read back out of an int64_t slot, surviving only by platform-ABI
        # luck since it was never arithmetically touched. See
        # bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md.
        # Moving the compile attempt to after Pass 1.3d means an unanimous
        # non-scalar (`char *`) cross-call observation for an unannotated
        # generator parameter now lands in self._inferred_param_types before
        # _gen_cpp_generator_unit ever looks, so _param_ctype resolves it to
        # `char *`, which the existing refusal check already rejects —
        # reusing that check exactly as before, with no new logic. A
        # scalar-only (int64_t/double/_Bool) unannotated parameter, or one
        # with no call-site scalar evidence either way (still defaults to
        # int64_t, matching every other unannotated scalar parameter in this
        # codegen), continues to compile exactly as it did before this move.
        # Deferring this far also means _gen_cpp_generator_unit's body
        # emission (_cpp_stmt) now runs with func_param_types/func_return_
        # types/struct registries/imported-symbol tables/_inferred_var_types
        # etc. already fully populated by the passes above, instead of the
        # much sparser state that existed at the top of gen_module — a
        # strict improvement, not a new dependency risk, since ordinary
        # (non-generator) function bodies were always emitted this late
        # already (Phase 2a, further below).
        #
        # A generator BODY can reference module-level globals (`sys`, `os`,
        # `_flags`, ...) and module-level functions (`detect_encoding`,
        # ...). The full global pre-scan (Phase 1.7) runs later in gen_module,
        # AFTER this loop, so a lightweight name-only pre-scan of module-level
        # assignments and imports is run here first — enough for _cpp_expr to
        # resolve a bare name as a module global (vs. a genuinely-undeclared
        # local) and to register the symbol for the .cpp preamble's extern
        # declarations.
        for _gm_stmt in stmts:
            if isinstance(_gm_stmt, AssignStmt) and isinstance(_gm_stmt.target, IdentExpr):
                self._cpp_early_global_names.add(_gm_stmt.target.name)
            elif isinstance(_gm_stmt, ImportStmt):
                for _tm, _ta in _import_targets(_gm_stmt):
                    # `import os.path` (no alias) binds the TOP-LEVEL
                    # package name `os` in real Python, not the literal
                    # dotted string "os.path" -- registering the latter
                    # left bare `os` references in the generator body
                    # unrecognized as a known global, falling through to
                    # an undeclared C++ identifier ("'os' was not declared
                    # in this scope") for any `os.replace(...)`-style call
                    # not already special-cased as `os.path.*`. Found via
                    # Tools/build/update_file.py's own `import os.path`.
                    self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
            elif isinstance(_gm_stmt, FromImportStmt):
                for _nm in getattr(_gm_stmt, 'names', []) or []:
                    self._cpp_early_global_names.add(_nm)
            elif isinstance(_gm_stmt, FunctionDef):
                self._cpp_early_global_names.add(_gm_stmt.name)
                self._cpp_module_fn_names.add(_gm_stmt.name)

        # Imports nested inside module-scope try/if bodies (`try: import
        # winreg as _winreg` — mimetypes.py's own shape; a `try:` around a
        # platform-specific import) are module globals too, but the flat scan
        # above misses them. Also collect module-level ASSIGNMENTS nested in
        # try/if bodies (locale.py's `except ImportError: CHAR_MAX = 127`
        # fallback constants). Walk one level of try/if bodies.
        def _scan_cpp_nested_imports(stmt_list):
            for _gi in stmt_list:
                if isinstance(_gi, (ImportStmt, FromImportStmt)):
                    if isinstance(_gi, ImportStmt):
                        for _tm, _ta in _import_targets(_gi):
                            # Same `import a.b` (no alias) top-level-name
                            # fix as the flat scan above.
                            self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
                    else:
                        for _nm in getattr(_gi, 'names', []) or []:
                            self._cpp_early_global_names.add(_nm)
                elif isinstance(_gi, AssignStmt) and isinstance(_gi.target, IdentExpr):
                    self._cpp_early_global_names.add(_gi.target.name)
                elif isinstance(_gi, TryStmt):
                    _scan_cpp_nested_imports(_gi.body or [])
                    for _h in (_gi.handlers or []):
                        _scan_cpp_nested_imports(getattr(_h, 'body', []) or [])
                    if isinstance(getattr(_gi, 'finally_body', None), list):
                        _scan_cpp_nested_imports(_gi.finally_body)
                elif isinstance(_gi, IfStmt):
                    _scan_cpp_nested_imports(_gi.then_body or [])
                    if isinstance(_gi.else_body, list):
                        _scan_cpp_nested_imports(_gi.else_body)
        _scan_cpp_nested_imports(stmts)
        for s in stmts:
            if not (isinstance(s, FunctionDef) and id(s) in _generator_fns
                    and id(s) not in _async_fns):
                continue
            # Skip generator METHODS (they have 'self', or 'cls' for a
            # @classmethod generator, as first param) — the dedicated
            # method loop at Phase 2 handles those with the correct
            # struct_name. Widening this to also recognize 'cls' matters
            # even though this particular loop only ever sees TOP-LEVEL
            # `stmts` (a real struct method can't appear here) — kept in
            # sync with the identical check in the "second + third passes"
            # loop below purely so the two don't silently diverge; see that
            # loop's own comment for why the 'cls' case is load-bearing
            # THERE (that loop iterates ALL of `_generator_fns`, including
            # nested struct methods, by identity — see
            # CODEGEN_generator_classmethod_first_param_must_be_self.md).
            if s.params and s.params[0][0] in ('self', 'cls'):
                continue
            if not _generator_quick_eligible(s):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'generator {s.name!r} not eligible for C++ '
                            'coroutine path, falling back to honest refusal', e)
                continue
            self._supported_generators[s.name] = s
            self._generator_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                # None for every generator except a tuple-valued one
                # (`yield a, b, ...`) — see _cpp_yield_tuple's producer-
                # side boxing and _gen_for_generator_iter's/next()'s
                # consumer-side unpacking, both keyed off this.
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            # <base>_start's real C parameter types, registered the exact
            # same way an ordinary function's signature is registered — this
            # is what lets _emit_call's existing argument-coercion machinery
            # (int-literal-to-int64_t, etc.) apply to a generator call's
            # arguments for free, with no separate coercion logic written
            # for this path.
            self.func_param_types[f"{base}_start"] = param_ctypes
            _gen_dflts = getattr(s, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f"{base}_start"] = [
                    (pn, dv) for pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _generator_fns.pop(id(s), None)

        # Second + third passes: try remaining generators (some may have had
        # yield-from dependencies that weren't compiled yet in the first pass).
        for _pass in range(3):
            if not _generator_fns:
                break
            for _gm_id, s in list(_generator_fns.items()):
                if _gm_id in _async_fns:
                    continue
                # Skip generator METHODS (handled by the dedicated method
                # loop) — this loop iterates `_generator_fns` directly
                # (built from a DEEP `_walk_ast(stmts)` scan, keyed by
                # object identity), so unlike the first-pass loop above
                # (which only ever sees top-level `stmts`), this one DOES
                # see nested struct methods, including @classmethod
                # generators whose first param is conventionally `cls`, not
                # `self`. Before this widened to also recognize 'cls', a
                # @classmethod generator method slipped past this "skip"
                # check, got compiled HERE as if it were an ordinary
                # free function (struct_name=None, `cls` treated as a
                # plain scalar parameter, popped out of `_generator_fns`
                # before the dedicated per-struct method loop ever got a
                # turn) — silently wrong for two reasons: (1) it registers
                # under the bare function name in `_generator_api`, which
                # a `ClassName.method(...)` call site never looks up (call
                # sites for a generator METHOD only ever consult
                # `_generator_method_api`, keyed by (struct_name, method)),
                # so the compiled unit was simply dead code; worse, (2) if
                # the body ever read `cls.<attr>` (a real shape — see
                # Lib/test/test_finalization.py's `test`), `_cpp_expr`'s
                # MemberExpr case falls to its "non-self member access"
                # branch (obj_expr.member) since the receiver isn't
                # literally named `self`, emitting `cls.attr` on a plain
                # `int64_t cls` parameter — invalid C++, a hard g++
                # compile failure instead of a graceful source fallback.
                # See CODEGEN_generator_classmethod_first_param_must_be_
                # self.md for the full root-cause writeup.
                if s.params and s.params[0][0] in ('self', 'cls'):
                    continue
                if not _generator_quick_eligible(s):
                    continue
                try:
                    cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'generator {s.name!r} not eligible for C++ '
                                f'coroutine path (pass {_pass+2}), falling back', e)
                    continue
                self._supported_generators[s.name] = s
                self._generator_api[s.name] = {
                    'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                    'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                _gen_dflts = getattr(s, 'param_defaults', None) or {}
                if _gen_dflts:
                    self._func_param_defaults[f"{base}_start"] = [
                        (pn, dv) for pn, dv in _gen_dflts.items()]
                self._generator_cpp_units.append(cpp_text)
                _generator_fns.pop(_gm_id, None)

        # ── Final step: combined async-generator eligibility/compile attempt ──
        # `async def f(): ... yield ... ...` (is_async AND is_generator both
        # true — the ONE category the plain-generator loop just above and
        # the plain-async loop just below deliberately exclude via their own
        # `id(s) not in _async_fns` / `id(s) not in _generator_fns` guards).
        # Runs BEFORE the plain-async loop below, not after — deliberately:
        # this step's target shape has a plain `async def` (e.g.
        # `main_driver`) consume an async GENERATOR (e.g. `f`) via `async
        # for`, which needs `f`'s own `_mojoasyncgen_f_handle`/`_impl`/
        # `_AnextAwaiter` C++ types already TEXTUALLY DEFINED, earlier in
        # the one concatenated .cpp translation unit (`_generator_cpp_units`
        # — see gen_module's docstring), before `main_driver`'s own cpp text
        # uses them (same-translation-unit composition, exactly like an
        # ordinary async-awaits-async call — see `_is_async_call_to_known_fn`
        # 's docstring for the identical "callee compiled first" source-
        # order constraint) — so `f` must be compiled (and registered in
        # `self._async_gen_api`) before `main_driver` is even attempted, not
        # after. Same late-running shape as the other two loops (after the
        # cross-call scalar-contract inference), keyed off membership in
        # BOTH `_generator_fns` and `_async_fns`, via
        # `_async_gen_quick_eligible`/`_gen_cpp_async_generator_unit`
        # instead of either single-purpose pair. On success, popped from
        # BOTH dicts so it's correctly excluded from every one of the three
        # mutually-exclusive category computations further below (this
        # function is no longer "still unsupported" in any of them).
        for s in stmts:
            if not (isinstance(s, FunctionDef) and id(s) in _async_fns
                    and id(s) in _generator_fns):
                continue
            if not _async_gen_quick_eligible(s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = \
                    self._gen_cpp_async_generator_unit(s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'async generator {s.name!r} not eligible for '
                            'C++ coroutine path, falling back to honest '
                            'refusal', e)
                continue
            self._supported_async_gen[s.name] = s
            self._async_gen_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _async_fns.pop(id(s), None)
            _generator_fns.pop(id(s), None)

        # Second pass for async generators not in top-level stmts (nested in
        # module-scope if/else/try bodies — types.py's `async def _ag():
        # yield` inside an `except ImportError:` handler).
        if _async_fns:
            for _gm_id, s in list(_async_fns.items()):
                if _gm_id not in _generator_fns:
                    continue
                if not _async_gen_quick_eligible(s, frozenset(self._async_api.keys())):
                    continue
                try:
                    cpp_text, value_ctype, base, param_ctypes = \
                        self._gen_cpp_async_generator_unit(s)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'async generator {s.name!r} not eligible '
                                '(pass 2)', e)
                    continue
                self._supported_async_gen[s.name] = s
                self._async_gen_api[s.name] = {
                    'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                    'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _async_fns.pop(_gm_id, None)
                _generator_fns.pop(_gm_id, None)

        # ── Step B: compiled-async-function eligibility/compile attempt ────
        # Same shape as the generator loop just above (run this late, after
        # the cross-call scalar-contract inference, for the identical reason
        # — an unannotated local's/return's real type benefits from the same
        # inference an ordinary function already gets), but keyed off
        # `_async_fns` and _async_quick_eligible/_gen_cpp_async_unit instead.
        # `id(s) not in _generator_fns` excludes an `async def f(): yield x`
        # async generator — that's its own combined-refusal category,
        # reported by the honest-fallback raise further below, never
        # silently compiled via either single-purpose path.
        for s in stmts:
            if not (isinstance(s, FunctionDef) and id(s) in _async_fns
                    and id(s) not in _generator_fns):
                continue
            # See _inline_single_use_task_composition's/_normalize_await_
            # kwargs's own docstrings — must run BEFORE the eligibility
            # check below (mirrors the identical calls in
            # _compile_nested_async_functions).
            s.body = self._inline_single_use_task_composition(s.body)
            self._normalize_await_kwargs(s.body)
            if not _async_quick_eligible(s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_async_unit(s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'async function {s.name!r} not eligible for '
                            'C++ coroutine path, falling back to honest '
                            'refusal', e)
                continue
            self._supported_async[s.name] = s
            self._async_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _async_fns.pop(id(s), None)
        # Second pass for async functions NOT in top-level stmts (nested in
        # if/else/try bodies at module scope — e.g. types.py's `async def
        # _c(): pass` inside an `except ImportError:` handler). Iterate
        # _async_fns directly, mirroring the generator multi-pass. MUST
        # exclude any async def nested INSIDE an ordinary top-level
        # function's own body — those belong exclusively to the dedicated
        # Step I (_compile_nested_async_functions) and async-closure
        # discovery passes further below, which thread the enclosing
        # function's scope, comptime bracket parameters, and captured free
        # variables into _gen_cpp_async_unit. Compiling one here as a bare
        # top-level-style unit silently drops all of that context (a real,
        # hand-verified regression: this pass claimed test_asyncrt.mojo's
        # comptime-parametrized `test_asyncrt_add[lhs: Int]` before the
        # closure pass could, registering a wrong, param-less unit under
        # the bare name and popping it out of `_async_fns`, so the closure
        # pass never populated `_async_closure_api` and `await
        # create_task(test_asyncrt_add[1](a))` fell through to the honest
        # whole-module refusal).
        #
        # MUST equally exclude any async def nested INSIDE A STRUCT
        # METHOD's own body — device_context.mojo's `async def wrapper(...)
        # capturing -> None:` shape, owned exclusively by the dedicated
        # "Async closures NESTED INSIDE A METHOD" pass further below (keyed
        # by (struct_name, method_name), threading `self`/method params/
        # threaded comptime function-typed params as captures). Originally
        # this set was only ever built by walking top-level FunctionDefs
        # (`_st in stmts`), never StructDefs — so a nested-in-a-METHOD async
        # def's id was never added here, and this pass (running BEFORE the
        # dedicated method-nested pass) claimed it first: compiled as a bare
        # top-level-style unit with `extra_captures=None`, silently dropping
        # every captured free variable (e.g. `func`), and popped it out of
        # `_async_fns` so the dedicated pass never got a turn. The generated
        # C++ body then referenced the captured name directly (`func()`)
        # with no parameter/local ever declaring it — a real, hand-verified
        # `'func' was not declared in this scope` g++ compile failure (see
        # test_async_void_return.py's test_device_context_shaped_repro_
        # end_to_end / test_enqueue_cpu_range_shaped_repro_multiple_
        # handles). Fixed by ALSO walking every struct method's body here,
        # exactly mirroring the top-level-FunctionDef loop just above.
        _nested_in_fn_ids: set = set()
        for _st in stmts:
            if not (isinstance(_st, FunctionDef)
                    and id(_st) not in _async_fns
                    and id(_st) not in _generator_fns):
                continue
            for _nf in _walk_ast(_st):
                if isinstance(_nf, FunctionDef):
                    _nested_in_fn_ids.add(id(_nf))
        for _st in stmts:
            if not isinstance(_st, StructDef):
                continue
            for _sm in _st.methods:
                if not isinstance(_sm, FunctionDef):
                    continue
                for _nf in _walk_ast(_sm.body):
                    if isinstance(_nf, FunctionDef):
                        _nested_in_fn_ids.add(id(_nf))
        if _async_fns:
            for _gm_id, s in list(_async_fns.items()):
                if _gm_id in _generator_fns:
                    continue  # async generator — separate path
                if _gm_id in _nested_in_fn_ids:
                    continue  # nested-in-function — Step I/closure pass's job
                s.body = self._inline_single_use_task_composition(s.body)
                self._normalize_await_kwargs(s.body)
                if not _async_quick_eligible(s, frozenset(self._async_api.keys())):
                    continue
                try:
                    cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_async_unit(s)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'async function {s.name!r} not eligible '
                                '(pass 2)', e)
                    continue
                self._supported_async[s.name] = s
                self._async_api[s.name] = {
                    'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _async_fns.pop(_gm_id, None)

        # Step I (create_task/Task/TaskGroup/RaisingTask project): async
        # functions NESTED inside an ordinary top-level function's own body
        # (real Mojo's own idiom: `@parameter async def wrapper(): ...`
        # scoped inside the test function that uses it, never a bare
        # top-level `async def`) — the loop just above only ever iterates
        # top-level `stmts`, so a nested one is otherwise always left
        # uncompiled in `_async_fns`, tripping the final "unhandled async
        # function(s)" whole-module refusal below. Must run BEFORE that
        # final check (not deferred to the later per-statement body-compile
        # loop, which runs much further down) — see
        # _compile_nested_async_functions's own docstring for the full
        # design (qualified-key registration into self._nested_async_api,
        # scoped push/pop into self._async_api done later, per enclosing
        # function, by the per-statement loop). Only ordinary (not
        # themselves async/generator) top-level FunctionDefs are scanned —
        # an async/generator top-level function's own body was already
        # fully handled by its own dedicated `_gen_cpp_*_unit` pass above,
        # which has no nested-def support of its own (out of scope: no
        # target file needs a doubly-nested async def).
        for s in stmts:
            if not (isinstance(s, FunctionDef) and id(s) not in _async_fns
                    and id(s) not in _generator_fns):
                continue
            self._compile_nested_async_functions(s, _async_fns)

        # Milestone C step 3: generator METHODS on structs — same eligibility/
        # compile-attempt shape as the free-function loop just above, keyed
        # by (struct_name, method_name) rather than by bare name (see
        # _supported_generator_methods' docstring). Runs in the same
        # struct-declaration order as everything else in this file, after
        # the identical Pass-1.3d cross-call inference the free-function
        # loop above depends on, for the same reason (an unannotated scalar
        # parameter of a generator method benefits from the exact same
        # cross-call-site scalar inference an ordinary method's unannotated
        # parameter already gets).
        for _sd in stmts:
            if not isinstance(_sd, StructDef):
                continue
            for m in _sd.methods:
                if not (isinstance(m, FunctionDef) and id(m) in _generator_fns
                        and id(m) not in _async_fns):
                    continue
                if not _generator_quick_eligible(m):
                    continue
                try:
                    cpp_text, value_ctype, base, param_ctypes = \
                        self._gen_cpp_generator_unit(m, struct_name=_sd.name)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'generator method {_sd.name}.{m.name!r} not '
                                'eligible for C++ coroutine path, falling '
                                'back to honest refusal', e)
                    continue
                key = (_sd.name, m.name)
                self._supported_generator_methods[key] = m
                self._generator_method_api[key] = {
                    'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                    'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                _gen_dflts = getattr(m, 'param_defaults', None) or {}
                if _gen_dflts:
                    self._func_param_defaults[f"{base}_start"] = [
                        (pn, dv) for pn, dv in _gen_dflts.items()]
                self._generator_cpp_units.append(cpp_text)
                _generator_fns.pop(id(m), None)

        # Second pass for generator methods (yield-from dependencies)
        for _sd in stmts:
            if not isinstance(_sd, StructDef):
                continue
            for m in _sd.methods:
                if not (isinstance(m, FunctionDef) and id(m) in _generator_fns
                        and id(m) not in _async_fns):
                    continue
                if not _generator_quick_eligible(m):
                    continue
                try:
                    cpp_text, value_ctype, base, param_ctypes = \
                        self._gen_cpp_generator_unit(m, struct_name=_sd.name)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'generator method {_sd.name}.{m.name!r} not '
                                'eligible (pass 2)', e)
                    continue
                key = (_sd.name, m.name)
                self._supported_generator_methods[key] = m
                self._generator_method_api[key] = {
                    'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                    'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                _gen_dflts = getattr(m, 'param_defaults', None) or {}
                if _gen_dflts:
                    self._func_param_defaults[f"{base}_start"] = [
                        (pn, dv) for pn, dv in _gen_dflts.items()]
                self._generator_cpp_units.append(cpp_text)
                _generator_fns.pop(id(m), None)

        # Async closures/functions NESTED INSIDE A TOP-LEVEL FUNCTION (not a
        # method) — test_asyncrt.mojo's/test_tracing.mojo's own shape:
        # `@parameter async def test_asyncrt_add[lhs: Int](rhs: Int) -> Int:
        # ...` defined inside an ordinary `def test_runtime_task() raises:`.
        # Comptime bracket parameters on a NESTED async function are
        # threaded through as ordinary trailing parameters exactly like
        # _method_threaded_comptime_params does for a function-TYPED
        # comptime method parameter (see that mechanism's own docstring) —
        # but here unconditionally, for EVERY comptime param regardless of
        # its annotated type (Int, Bool, ...), because this reasoning
        # applies more broadly than just function-typed values: _gen_cpp_
        # async_unit never does any compile-time folding/specialization on
        # a comptime parameter's VALUE at all (it just compiles one
        # coroutine body per Mojo function definition and threads whatever
        # scalar arguments a call site supplies) — so `test_asyncrt_add[1]
        # (10)` and `test_asyncrt_add[2](20)` calling the SAME compiled
        # coroutine unit with `lhs` passed as an ordinary 1/2 argument is
        # exactly equivalent to real per-call-site monomorphization for
        # this codegen's own (non-branching-on-comptime-ness) purposes —
        # unlike the general (non-async) free-function/struct-method paths
        # elsewhere in this file, which DO need real per-call-site
        # elaboration (see bugs/CODEGEN_comptime_bracket_parametrized_
        # function_calls_silently_wrong.md) because those bodies CAN
        # observe comptime-ness (e.g. `@parameter if`, static array sizes)
        # — no compiled async function anywhere in this codebase does that.
        if _gsrc:
            for _od in stmts:
                if not isinstance(_od, FunctionDef):
                    continue
                _outer_scope2 = {}
                for _pname, _ptype in (_od.params or []):
                    _outer_scope2[_pname] = self._resolve_type(_ptype)
                for _inner in _od.body:
                    if not (isinstance(_inner, FunctionDef) and id(_inner) in _async_fns):
                        continue
                    _cp_ctypes = {}
                    if _inner.comptime_params:
                        _bp_types2 = _bracket_param_type_annotations(_gsrc, _inner.name)
                        for _cp in _inner.comptime_params:
                            _ann = _bp_types2.get(_cp, '')
                            _cp_ctypes[_cp] = ('int64_t' if _ann.startswith('def')
                                               else self._resolve_type(_ann))
                    if not _async_quick_eligible(_inner, frozenset(self._async_api.keys())):
                        continue
                    _captures2 = self._compute_nested_closure_captures(_inner, _outer_scope2)
                    _extra2 = [(cp, _cp_ctypes.get(cp, 'int64_t')) for cp in _inner.comptime_params] + _captures2
                    _base_override2 = f"{_od.name}_{_inner.name}"
                    try:
                        cpp_text, value_ctype, base, param_ctypes = \
                            self._gen_cpp_async_unit(_inner, extra_captures=_extra2,
                                                     base_name_override=_base_override2,
                                                     enclosing_scope=_od.name)
                    except _UnsupportedGeneratorShape as e:
                        _debug_note(f'nested async function {_od.name}.'
                                    f'{_inner.name!r} not eligible for C++ '
                                    'coroutine path, falling back to honest '
                                    'refusal', e)
                        continue
                    key = (_od.name, _inner.name)
                    self._supported_async_closures[key] = _inner
                    self._async_closure_api[key] = {
                        'base': base, 'value_ctype': value_ctype,
                        'params': param_ctypes, 'captures': _extra2,
                        'comptime_params': list(_inner.comptime_params),
                    }
                    self.func_param_types[f"{base}_start"] = param_ctypes
                    self._generator_cpp_units.append(cpp_text)
                    _async_fns.pop(id(_inner), None)

        # Async closures NESTED INSIDE A METHOD (not themselves a method,
        # and not a top-level function either) — device_context.mojo's
        # `async def wrapper(...) capturing -> None:` shape, defined inside
        # `enqueue_cpu_function`/`enqueue_cpu_range`. Neither the free-
        # function loop above (only scans top-level `stmts`) nor the
        # generator/async-METHOD loops (only scan `_sd.methods` themselves,
        # one level deep) ever attempt a doubly-nested async def like this
        # one — confirmed via a hand-written repro that reached this file's
        # final "still unsupported" refusal even after `_async_quick_
        # eligible` itself was widened to accept parameterized async defs
        # (Step H's merge) — `wrapper` is never even OFFERED to that
        # eligibility check by any existing pass. This is a NEW pass, not a
        # widening of an existing one, run in the same struct-declaration
        # order as everything else in this file, one level deeper (struct
        # -> method -> nested async def).
        for _sd in stmts:
            if not isinstance(_sd, StructDef):
                continue
            _moids_ac = self._struct_method_overload_ids(_sd)
            for _m, _oid in zip(_sd.methods, _moids_ac):
                # The same outer scope Pass 3 (_scan_for_closures, below)
                # would build for this method: self, its own params, and
                # any function-typed comptime bracket parameter threaded
                # through as an ordinary trailing parameter (see
                # _method_threaded_comptime_params) — the only kinds of
                # free variable a nested async closure could actually
                # capture here.
                _outer_scope = {_sd.name.lower(): f"{_sd.name} *",
                                 'self': f"{_sd.name} *"}
                for _pname, _ptype in _m.params:
                    if _pname != 'self':
                        _outer_scope[_pname] = self._resolve_type(_ptype)
                for _cp_name in self._method_threaded_comptime_params.get(
                        (_sd.name, _m.name), {}).get(_oid, []):
                    _outer_scope[_cp_name] = 'int64_t'
                for _inner in _m.body:
                    if not (isinstance(_inner, FunctionDef) and id(_inner) in _async_fns):
                        continue
                    if not _async_quick_eligible(_inner, frozenset(self._async_api.keys())):
                        continue
                    _captures = self._compute_nested_closure_captures(_inner, _outer_scope)
                    _base_override = f"{_sd.name}_{_m.name}{_oid}_{_inner.name}"
                    try:
                        cpp_text, value_ctype, base, param_ctypes = \
                            self._gen_cpp_async_unit(_inner, extra_captures=_captures,
                                                     base_name_override=_base_override)
                    except _UnsupportedGeneratorShape as e:
                        _debug_note(f'nested async closure {_sd.name}.{_m.name}.'
                                    f'{_inner.name!r} not eligible for C++ '
                                    'coroutine path, falling back to honest '
                                    'refusal', e)
                        continue
                    outer_ctx = f"{_sd.name}_{_m.name}{_oid}"
                    key = (outer_ctx, _inner.name)
                    self._supported_async_closures[key] = _inner
                    self._async_closure_api[key] = {
                        'base': base, 'value_ctype': value_ctype,
                        'params': param_ctypes, 'captures': _captures,
                    }
                    self.func_param_types[f"{base}_start"] = param_ctypes
                    self._generator_cpp_units.append(cpp_text)
                    _async_fns.pop(id(_inner), None)

        # Plain for-loops (not comprehensions) building plain lists, then
        # sorted — deliberately avoiding a `for i, fn in ...items()` set/
        # dict comprehension here: this project's OWN self-hosting compiler
        # flattens gen_module into one giant C function sharing a single
        # flat per-name variable-type namespace (see the rename note on
        # `_generator_fns`/`_async_fns` above), and the extremely common
        # 2-letter name `fn` is ALREADY reused elsewhere in this same
        # method for a plain field-name STRING (not a FunctionDef) — a
        # comprehension-based version of this exact loop produced a real
        # "assignment to 'char' from 'char *'" self-host compile error
        # (confirmed via `make check-selfhost`), so this uses an
        # unambiguous, never-reused local name and an ordinary loop instead.
        _gen_only_names: list = []
        for _gm_id, _gm_fn in _generator_fns.items():
            if _gm_id not in _async_fns:
                _gen_only_names.append(_gm_fn.name)
        _async_only_names: list = []
        for _gm_id, _gm_fn in _async_fns.items():
            if _gm_id not in _generator_fns:
                _async_only_names.append(_gm_fn.name)
        _async_gen_names: list = []
        for _gm_id, _gm_fn in _generator_fns.items():
            if _gm_id in _async_fns:
                _async_gen_names.append(_gm_fn.name)
        _gen_only = sorted(_gen_only_names)
        _async_only = sorted(_async_only_names)
        _async_gen = sorted(_async_gen_names)
        if _gen_only or _async_only or _async_gen:
            _categories = []
            if _gen_only:
                _categories.append(
                    f"{', '.join(_gen_only)} (generator function(s), contain "
                    "a `yield`/`yield from`)")
            if _async_only:
                _categories.append(
                    f"{', '.join(_async_only)} (async function(s), declared "
                    "`async def`)")
            if _async_gen:
                _categories.append(
                    f"{', '.join(_async_gen)} (async generator function(s), "
                    "declared `async def` AND contain a `yield`/`yield from`)")
            if self.relaxed_imports:
                _debug_note('relaxed_imports: skipping unsupported functions',
                            '; '.join(_categories))
                # Register stub extern declarations for skipped functions so
                # importing modules can at least reference them (they'll print
                # a warning if actually called at runtime).
                for _fn_name in _gen_only + _async_only + _async_gen:
                    _csym = self._func_csym(_fn_name)
                    _g = _stub_guard_name(_csym)
                    _stub = f'#ifndef {_g}\n#define {_g}\nint64_t {_csym} (...);\n#endif'
                    if _stub not in self._elaborated_externs:
                        self._elaborated_externs.append(_stub)
                    # See _unsupported_generator_names's docstring: Phase 2a
                    # must not ALSO compile this name as an ordinary function.
                    self._unsupported_generator_names.add(_fn_name)
            else:
                raise RuntimeError(
                    "cannot compile module: function(s) "
                    + "; ".join(_categories) +
                    " — this codegen compiles every function into a single "
                    "straight-line C function and has no suspend/resume "
                    "state-machine transform for generators, nor an event loop "
                    "/ suspend-resume codegen for async functions, yet, so "
                    "these cannot be represented as compiled C without "
                    "emitting silently wrong or broken code; falling back to "
                    "interpreting this module from source instead")

        # ── Pass 1.3e: refresh return types now that param inference is final ──
        # "Pass 2" (above, executed earlier despite the lower number — it seeds
        # func_return_types before _infer_param_types/Pass 1.3d even run) infers
        # each unannotated function's return type by seeding its unannotated
        # params with the naive int64_t default, since neither the body-usage
        # pass (1.3) nor the cross-call contract (1.3d, just above) had run yet.
        # A function whose real parameter shape only became known from body
        # usage or from a call site's argument type — e.g. `def g(a): return a`
        # called as `g("ab")`, whose `a`/return only resolve to char* via
        # 1.3d's cross-call observation — was frozen here with the wrong
        # int64_t return type. That stayed wrong for every caller compiled
        # before g's own gen_func happened to re-sync func_return_types in
        # Phase 2a (gen_func's "Sync so forward declarations match Phase 2a
        # inference") — in particular a module-level statement like
        # `y = g("a", "b")` (scanned further below, before Phase 2a) and any
        # other function's local-variable type inference (Pass 1.3b above,
        # which itself ran before this correction). Re-run the same
        # inference here with the now-final param types as the seed, rather
        # than adding a parallel special case. See
        # bugs/CODEGEN_untyped_param_string_passthrough_wrong.md.
        for s in all_functions:
            if isinstance(s, FunctionDef) and s.return_type is None:
                _saved_vt_23e = self.var_types
                self.var_types = dict(_saved_vt_23e)
                for pname, ptype in s.params:
                    bare = pname.lstrip('*')
                    if pname.startswith('*'):
                        self.var_types[bare] = 'MojoList *'
                    elif ptype is None:
                        self.var_types[bare] = (self._inferred_param_types.get(s.name, {}).get(bare)
                                                 or self._resolve_type(ptype))
                    else:
                        self.var_types[bare] = self._resolve_type(ptype)
                inferred = self._infer_return_type(s.body)
                if s.name == 'main' and inferred == 'void':
                    inferred = 'int64_t'
                self.var_types = _saved_vt_23e
                self.func_return_types[s.name] = inferred

        # ── Pass 1.3f: re-run local-variable type inference ────────────────
        # Pass 1.3b (above) computed _inferred_var_types using the func_return_types
        # in effect at the time — stale for any unannotated callee just corrected
        # by Pass 1.3e. A local assigned straight from such a call (`y = g("a",
        # "b")`) needs the refreshed callee return type to be typed as the real
        # pointer instead of int64_t. Cheap to redo in full (same pass, same cost
        # as Pass 1.3b already paid) rather than special-casing which functions
        # need it recomputed.
        for s in all_functions:
            if isinstance(s, FunctionDef):
                self._inferred_var_types[s.name] = self._infer_local_var_types(s)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    key = f"{s.name}_{m.name}"
                    self._inferred_var_types[key] = self._infer_local_var_types(m)

        # ── Pass 1.3f-gen: cross-call generator-value contract ─────────────
        # A compiled generator's `MojoGenerator *` result is only typed
        # correctly for a LOCAL variable once Pass 1.3d-gen has populated
        # self._generator_api AND Pass 1.3f has re-run local-variable type
        # inference (see `_quick_type`'s generator-call branch) — Pass 1.3d's
        # cross-call scalar contract ran BEFORE both, so a call site that
        # passes a stored generator as an argument (`consume(g)` where
        # `g = counter(3)`) observed `g`'s stale int64_t inference there and
        # left the callee's unannotated param defaulted to int64_t (a `for x
        # in g:` inside the callee then hit the unsupported-iterable
        # fallback). Re-observe those call sites here with the corrected
        # _inferred_var_types, and:
        #   (a) propagate the unanimous `MojoGenerator *` type onto the
        #       callee's unannotated param, mirroring exactly how Pass 1.3d
        #       already propagates a unanimous `char *`/`double` (same
        #       observe-per-call-site/apply-if-unanimous contract, run again
        #       rather than added as a parallel narrow special case), AND
        #   (b) record WHICH generator function made the value (provenance,
        #       walked from the caller's own assignment statements, or
        #       chained through a caller param a previous round already
        #       resolved) so the callee's body can recover the concrete
        #       `base`/`value_ctype` extern "C" API for `for x in g:` /
        #       `next(g)`. The api is keyed per generator FUNCTION in
        #       `self._generator_api`; a param crossing a call boundary has
        #       no `_generator_var_api` entry of its own (that dict is only
        #       populated at construction/assignment sites — see its
        #       docstring), so the provenance is what lets gen_func seed one
        #       for the param. Also records which functions RETURN a
        #       generator (`def mk(): return counter(3)`) so a call to such a
        #       function gets a `_generator_var_api` entry on its result too
        #       (stored-generator/for-loop over `mk()` and `g = mk()` both
        #       then work exactly like `counter(3)` itself). See
        #       bugs/CODEGEN_compiled_generator_not_first_class_value.md.
        self._param_generator_api: dict[str, dict[str, str]] = {}
        self._fn_returns_generator: dict[str, str] = {}

        def _walk_gen_prov(body, target_name, known_params):
            """Return the single generator function name assigned to
            `target_name` anywhere in `body` (recursively, skipping nested
            defs), or None (never assigned a generator, or a conflict — two
            different generator functions assigned to the same variable, or a
            pass-through of a param whose own provenance is unresolved).
            `known_params` maps a caller param already proven to hold a
            generator to its function name, for the chained shape
            `def outer(g): consume(g)`."""
            found = None

            def _scan(stmts):
                nonlocal found
                for st in stmts:
                    val = None
                    if isinstance(st, AssignStmt) and isinstance(st.target, IdentExpr):
                        if st.target.name == target_name:
                            val = st.value
                    elif isinstance(st, VarDecl) and st.name == target_name:
                        val = st.value
                    if val is not None:
                        prov = None
                        if isinstance(val, CallExpr) and isinstance(val.func, IdentExpr):
                            if val.func.name in self._generator_api:
                                prov = val.func.name
                            else:
                                prov = self._fn_returns_generator.get(val.func.name)
                        elif isinstance(val, IdentExpr):
                            prov = known_params.get(val.name)
                        if prov is not None:
                            if found is None:
                                found = prov
                            elif found != prov:
                                found = '<conflict>'
                        continue
                    if isinstance(st, FunctionDef):
                        continue
                    for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                        sub = getattr(st, attr, None)
                        if isinstance(sub, list):
                            _scan(sub)
                    for _eb_cond, _eb_body in (getattr(st, 'elifs', None) or []):
                        _scan(_eb_body)
                    for _h in (getattr(st, 'handlers', None) or []):
                        hb = getattr(_h, 'body', None)
                        if isinstance(hb, list):
                            _scan(hb)

            _scan(body)
            return found

        def _arg_generator_prov(caller_name, arg):
            """The generator function name behind call-site argument `arg`
            (typed `MojoGenerator *` in the caller), or None."""
            if isinstance(arg, IdentExpr):
                t = (self._inferred_var_types.get(caller_name, {}).get(arg.name)
                     or self._inferred_param_types.get(caller_name, {}).get(arg.name))
                if t != 'MojoGenerator *':
                    return None
                fn = _fn_by_name.get(caller_name)
                if fn is not None:
                    p = _walk_gen_prov(fn.body, arg.name,
                                       self._param_generator_api.get(caller_name, {}))
                    if p is not None:
                        return p
                # Not assigned in the caller's own body → a pass-through of
                # one of the caller's own params (a prior round's provenance).
                return self._param_generator_api.get(caller_name, {}).get(arg.name)
            if isinstance(arg, CallExpr) and isinstance(arg.func, IdentExpr):
                if arg.func.name in self._generator_api:
                    return arg.func.name
                return self._fn_returns_generator.get(arg.func.name)
            return None

        # Functions whose EVERY value-return is a known generator call
        # (`def mk(): return counter(3)`) — used as provenance at call sites
        # AND by _lower_named_call to seed a _generator_var_api entry on the
        # call's result. Skipping nested FunctionDef bodies: only the
        # function's OWN returns count.
        for _rf in all_functions:
            if not isinstance(_rf, FunctionDef):
                continue
            acc_rt = []

            def _collect_rt(stmts2):
                for _st in stmts2:
                    if isinstance(_st, FunctionDef):
                        continue
                    if isinstance(_st, ReturnStmt) and _st.value is not None:
                        acc_rt.append(_st.value)
                    else:
                        for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                            sub = getattr(_st, attr, None)
                            if isinstance(sub, list):
                                _collect_rt(sub)
                        for _eb_cond, _eb_body in (getattr(_st, 'elifs', None) or []):
                            _collect_rt(_eb_body)
                        for _h in (getattr(_st, 'handlers', None) or []):
                            hb = getattr(_h, 'body', None)
                            if isinstance(hb, list):
                                _collect_rt(hb)

            _collect_rt(_rf.body)
            rt_prov = None
            for _rv in acc_rt:
                if (isinstance(_rv, CallExpr) and isinstance(_rv.func, IdentExpr)
                        and _rv.func.name in self._generator_api):
                    if rt_prov is None:
                        rt_prov = _rv.func.name
                    elif rt_prov != _rv.func.name:
                        rt_prov = '<conflict>'
                else:
                    rt_prov = '<conflict>'
            if rt_prov not in (None, '<conflict>'):
                self._fn_returns_generator[_rf.name] = rt_prov

        _param_gen_obs: dict[str, dict[str, dict]] = {}  # callee -> {pname -> {fname: count}}
        for _round in range(4):
            _changed = False
            for _cl_name, _cl_body in _caller_bodies:
                _calls = []
                self._calls_in_stmts(_cl_body, _calls)
                for _call in _calls:
                    if not isinstance(_call.func, IdentExpr):
                        continue
                    _callee = _call.func.name
                    _pnames = _free_params.get(_callee)
                    if not _pnames:
                        continue
                    for _i, _a in enumerate(_call.args):
                        if _i >= len(_pnames):
                            break
                        prov = _arg_generator_prov(_cl_name, _a)
                        if prov is None:
                            continue
                        _pobs = _param_gen_obs.setdefault(_callee, {})
                        _fmap = _pobs.setdefault(_pnames[_i], {})
                        _fmap[prov] = _fmap.get(prov, 0) + 1
            for _callee, _pmap in _param_gen_obs.items():
                _fn = _fn_by_name.get(_callee)
                if _fn is None:
                    continue
                for _pname, _fmap in _pmap.items():
                    _keys = []
                    for _k in _fmap:
                        _keys.append(_k)
                    # Any generator-valued observation makes the param
                    # genuinely `MojoGenerator *` (provenance is only ever
                    # non-None for generator-typed call-site arguments), so
                    # type it regardless of unanimity — a `for x in g:`
                    # inside the callee will then dispatch on the right type
                    # and (when no single provenance exists) refuse honestly
                    # with "no known API" instead of the misleading int64_t
                    # unsupported-iterable. Provenance is recorded ONLY for
                    # a unanimous single generator function.
                    _annot = None
                    for _p, _pt in (_fn.params or []):
                        if _p == _pname:
                            _annot = _pt
                            break
                    if _annot is not None:
                        continue  # respect an explicit annotation
                    _cur = self._inferred_param_types.get(_callee, {}).get(_pname)
                    # `MojoList *` is included here alongside the int64_t
                    # default: `_infer_param_types`'s generic body-usage scan
                    # (run BEFORE this pass) has no visibility into call-site
                    # argument types, so a param consumed only via `for x in
                    # g:` (with no subscript) is guessed `MojoList *` purely
                    # from `is_iterated` — the same syntactic shape a param
                    # consuming a generator has. That guess is exactly wrong
                    # when every real call-site argument we observed here is
                    # generator-provenanced (`prov is not None`, checked
                    # above the observation loop this dict is built from),
                    # which is strictly stronger evidence than the body
                    # scan's blind guess: it traced the actual value
                    # flowing in. Found via `consume(g)`/`consume(mk())`
                    # (bugs/CODEGEN_compiled_generator_not_first_class_
                    # value.md's composed boundary shapes): `consume`'s
                    # param `g` was pre-typed `MojoList *` by the body scan,
                    # this pass's guard then skipped it as "already picked a
                    # real type", so the caller's real `MojoGenerator *` got
                    # force-cast to `MojoList *` at the call site and every
                    # `for x in g:` inside `consume` read the coroutine
                    # frame's raw bytes through `mojo_list_len`/
                    # `mojo_list_get_int` as if it were a MojoList struct —
                    # a silent miscompile (no error, no crash at compile
                    # time) producing garbage int64 values instead of a hard
                    # failure.
                    if _cur not in (None, 'int', 'int64_t', 'MojoList *'):
                        continue  # body evidence already picked a real type
                    self._inferred_param_types.setdefault(_callee, {})[_pname] = 'MojoGenerator *'
                    if len(_keys) == 1 and _keys[0] != '<conflict>':
                        self._param_generator_api.setdefault(_callee, {})[_pname] = _keys[0]
                    _changed = True
            if not _changed:
                break

        # Rebuild free-function param-type signatures so call-site coercion
        # (and the emitted declarations) see the propagated MojoGenerator *
        # param types — must follow the propagation above, exactly like Pass
        # 1.3d's own identical rebuild (gen_func's `_param_ctype` consults
        # _inferred_param_types, so the emitted signature is right, but
        # func_param_types is what _emit_call's argument coercion reads).
        for s in all_functions:
            if _is_foreign_main(s):
                continue
            if isinstance(s, FunctionDef):
                if s.params and any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                    self._note_vararg_trailing_param_types(s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []

        # ── Phase 1.5: dispatch solving (static dispatch table planning) ───
        # Run DispatchSolver to identify dynamic dispatch patterns and plan
        # virtual method tables before generating code. This enables static
        # dispatch instead of dynamic getattr/dict lookups.
        if self.emit_struct_defs:  # Only main module does dispatch solving
            self._dispatch_solver = DispatchSolver(
                self.struct_field_types, self.func_return_types,
                allow_assume_all_methods=_is_selfhost_file,
                generator_method_api=self._generator_method_api)
            all_stmts_for_dispatch = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
            self._dispatch_solver.analyze(all_stmts_for_dispatch)
            self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()

        # ── Pass 3: collect closures (nested FunctionDef nodes) ──────────
        self._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}

        def _scan_for_closures(outer_name: str, outer_scope: dict, body: list):
            """Scan a function/method body for nested FunctionDefs and register them as closures."""
            def _all_stmts_nonfunc(stmts):
                """Return a list of statements recursively through control flow, not entering FunctionDef bodies."""
                result = []
                for s in stmts:
                    result.append(s)
                    if isinstance(s, FunctionDef):
                        continue
                    for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                        sub = getattr(s, attr, None)
                        if isinstance(sub, list):
                            result.extend(_all_stmts_nonfunc(sub))
                    for _cond, elif_body in getattr(s, 'elifs', []):
                        result.extend(_all_stmts_nonfunc(elif_body))
                    for handler in getattr(s, 'handlers', []):
                        if hasattr(handler, 'body') and isinstance(handler.body, list):
                            result.extend(_all_stmts_nonfunc(handler.body))
                return result

            # Enrich outer_scope with local variable assignments/declarations for capture detection.
            enriched_scope = dict(outer_scope)
            _saved_vt2 = dict(self.var_types)
            self.var_types.update(outer_scope)
            for bstmt in _all_stmts_nonfunc(body):
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    name = bstmt.target.name
                    if name not in enriched_scope:
                        t = self._quick_type(bstmt.value)
                        enriched_scope[name] = t
                        self.var_types[name] = t
                elif isinstance(bstmt, VarDecl):
                    if bstmt.name not in enriched_scope:
                        t = self._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                        enriched_scope[bstmt.name] = t
                        self.var_types[bstmt.name] = t
            self.var_types = _saved_vt2
            for stmt in _all_stmts_nonfunc(body):
                if not isinstance(stmt, FunctionDef):
                    continue
                # Step I (create_task/Task/TaskGroup/RaisingTask project):
                # a nested `async def` (not an async GENERATOR — those stay
                # on this ordinary closure-lifting path unchanged, out of
                # this step's scope) was already compiled, if eligible, via
                # the dedicated C++20-coroutine path by gen_module's own
                # _compile_nested_async_functions pre-pass (which runs
                # BEFORE this closure scan — see gen_module for the pass
                # ordering) — it must NOT also be lifted into an ordinary
                # plain-C closure function here, which would either
                # silently shadow/duplicate it or (since no ordinary,
                # non-coroutine lowering anywhere in this file has ever
                # handled `await` — confirmed via grep) simply re-hit the
                # same "unsupported expression" refusal an ordinary
                # lowering attempt of an `await`-containing body always
                # already did before this project's async codegen existed
                # at all. Skipping it here is therefore never a regression
                # (a nested async def with `await` in its body could not
                # have compiled via this ordinary path either way) and is
                # required for a genuinely ELIGIBLE one (skipping it here
                # is what lets the C++ coroutine unit be the only
                # definition anyone calls into).
                if stmt.is_async and not stmt.is_generator:
                    continue
                inner     = stmt
                lifted    = f"{outer_name}_{inner.name}"
                # Compute free variables: used in inner body minus inner scope
                used      = set()
                for body_node in inner.body:
                    used |= _used_idents_node(body_node)
                # Include AssignStmt targets in declared vars (they're local to inner).
                # Recurse into for/if/while bodies since Python scoping is function-wide.
                inner_assign_targets = set()
                for bstmt in _all_stmts_nonfunc(inner.body):
                    if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                        inner_assign_targets.add(bstmt.target.name)
                    elif isinstance(bstmt, ForStmt):
                        tgt = bstmt.target
                        if isinstance(tgt, str):
                            inner_assign_targets.add(tgt)
                        elif hasattr(tgt, 'name'):
                            inner_assign_targets.add(tgt.name)
                inner_declared = ({pn for pn, _ in inner.params}
                                  | _declared_vars_body(inner.body)
                                  | inner_assign_targets)
                # Exclude known globals/imported functions from capture — but NOT if
                # the outer function has a PARAMETER with the same name (parameter
                # shadows the global and must be captured, not treated as a global ref).
                # We use outer_scope (parameters only) not enriched_scope (which includes
                # local assignments like module imports that should NOT be captured).
                outer_params = set(outer_scope.keys())
                free_globals = set(self.func_return_types.keys()) - outer_params
                free         = used - inner_declared - free_globals
                captures     = [(v, enriched_scope[v]) for v in sorted(free)
                                if v in enriched_scope]
                # Transitively union in the captures of any REGISTERED
                # nested async unit THIS closure's body calls BY NAME
                # (test_locks.mojo's `test_atomic()` calling `inc()`
                # without itself ever textually referencing `inc()`'s own
                # captured `lock`/`rawCounter` -- gap (1) of bugs/CODEGEN_
                # comptime_bracket_parametrized_function_calls_silently_
                # wrong.md's test_locks.mojo analysis). `self.
                # _nested_async_api` (keyed `f"{enclosing}::{name}"`) is
                # already fully populated for `outer_name` by gen_module's
                # own `_compile_nested_async_functions` pass, which always
                # runs BEFORE this scan (see that method's own docstring
                # for the pass ordering) -- a flat "does this closure call
                # that async unit's name" lookup, not general call-graph
                # analysis, since the async registration already gives an
                # exact, flat name -> captures lookup.
                _cap_names_so_far = {_cn for _cn, _ in captures}
                _called_names = {nd.func.name for nd in _walk_ast(inner.body)
                                  if isinstance(nd, CallExpr) and isinstance(nd.func, IdentExpr)}
                _transitive_mut: set = set()
                for _called in _called_names:
                    _t_api = self._nested_async_api.get(f"{outer_name}::{_called}")
                    if _t_api is None:
                        continue
                    for _tn, _tt in (_t_api.get('captures') or []):
                        if _tn not in _cap_names_so_far and _tn in enriched_scope:
                            captures.append((_tn, enriched_scope[_tn]))
                            _cap_names_so_far.add(_tn)
                        if _tn in (_t_api.get('mut_capture_names') or frozenset()):
                            _transitive_mut.add(_tn)
                env_struct   = f"{lifted}_env" if captures else ""
                ci           = ClosureInfo(lifted, env_struct, captures, inner)
                # Register this closure's own param defaults keyed by its
                # lifted name, mirroring the top-level free-function
                # registration a few hundred lines up (`all_functions` only
                # covers MODULE-LEVEL FunctionDefs, so a nested closure like
                # `def _inject(iterator=iterator, suffix=suffix): ...`
                # never got an entry there at all) -- without this,
                # _lower_closure_call had no default values to pad with
                # when a call site omits args relying on them (e.g. bare
                # `_inject()`), producing a hard "too few arguments" C
                # compile error instead of a working call.
                # Loop variable deliberately NOT named `_dv`: `gen_module`
                # (this method's enclosing scope) already uses `_dv` as a
                # comprehension loop variable for the identical pattern a
                # few hundred lines up (top-level free-function default
                # registration) -- see this file's own documented self-
                # host gotcha a few lines above (`v` reuse across two
                # comprehensions in the same enclosing function breaks
                # self-hosted compilation, confirmed here by an identical
                # '_dv' undeclared error during make check-selfhost).
                _inner_dflts = getattr(inner, 'param_defaults', None) or {}
                if _inner_dflts:
                    self._func_param_defaults[lifted] = [
                        (_pn2, _dv2) for _pn2, _dv2 in _inner_dflts.items()]
                # `{mut}`-capture-spec closures (`def inc() {mut}: counter
                # += 1`) reassign a captured free variable -- detected the
                # same way the async mutable-capture mechanism detects it
                # (_mutated_free_names, a static "does the body ever
                # reassign this name" scan; the parser discards the actual
                # `{mut}` capture-spec text today, so this is the only
                # signal available) -- see ClosureInfo.mut_names. Unioned
                # with `_transitive_mut` (above) so a captured name that's
                # only mutated INSIDE the called async unit's own body
                # (never textually reassigned by THIS closure itself) still
                # gets threaded through by reference, not by value.
                # Loop variable deliberately NOT named `v`: this file is
                # itself self-hosted, and re-using a name already bound by
                # an EARLIER comprehension in this same enclosing function
                # (the `captures = [(v, ...) for v in ...]` a few lines up)
                # in a SECOND, later comprehension hit a real self-host
                # compile error ('v' undeclared) -- gimple_codegen.py's own
                # comprehension-loop lowering doesn't give each
                # comprehension a properly independent C-level loop
                # variable when the same source name is reused. Not
                # investigated further here (see the async path's
                # identical `_cn`-named sibling below for why `_cn`, not
                # `v`, is this project's established safe convention).
                ci.mut_names = self._mutated_free_names(inner, _cap_names_so_far) | _transitive_mut
                if outer_name not in self._all_closures:
                    self._all_closures[outer_name] = {}
                self._all_closures[outer_name][inner.name] = ci
                # Register lifted name so callers can resolve its return type
                if inner.return_type is not None:
                    self.func_return_types[lifted] = self._resolve_type(inner.return_type)
                else:
                    # Quick inference for unannotated inner
                    for pname, ptype in inner.params:
                        self.var_types[pname] = self._resolve_type(ptype)
                    self.func_return_types[lifted] = self._infer_return_type(inner.body)
                    self.var_types.clear()
                # Also recursively scan inner body for doubly-nested closures.
                # Build inner_scope from enriched_scope + inner params + inner local assignments.
                inner_scope = dict(enriched_scope)
                for pn, pt in inner.params:
                    inner_scope[pn] = self._resolve_type(pt)
                for bstmt in inner.body:
                    if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                        name = bstmt.target.name
                        if name not in inner_scope:
                            inner_scope[name] = self._quick_type(bstmt.value)
                _scan_for_closures(lifted, inner_scope, inner.body)

            # After registering all closures for this outer function, detect re.sub callbacks.
            # Pattern: re.sub(pattern, callback_name, src) where callback_name is a registered inner.
            def _find_re_sub_callbacks(search_body, context_outer):
                for stmt in search_body:
                    stmts_to_check = []
                    if isinstance(stmt, AssignStmt):
                        stmts_to_check.append(stmt.value)
                    elif isinstance(stmt, ExprStmt):
                        stmts_to_check.append(stmt.value)  # ExprStmt uses .value
                    elif hasattr(stmt, 'body'):
                        _find_re_sub_callbacks(getattr(stmt, 'body', []), context_outer)
                        for clause in ('orelse', 'handlers', 'finalbody'):
                            _find_re_sub_callbacks(getattr(stmt, clause, []), context_outer)
                    for expr in stmts_to_check:
                        if not isinstance(expr, CallExpr):
                            continue
                        func = expr.func
                        # re.sub(pat, callback, src)
                        if (isinstance(func, MemberExpr)
                                and isinstance(func.obj, IdentExpr)
                                and func.obj.name == 're'
                                and func.member == 'sub'
                                and len(expr.args) >= 2):
                            cb_arg = expr.args[1]
                            if isinstance(cb_arg, IdentExpr):
                                inner_map = self._all_closures.get(context_outer, {})
                                if cb_arg.name in inner_map:
                                    inner_map[cb_arg.name].is_re_sub_callback = True
            _find_re_sub_callbacks(body, outer_name)

        for s in stmts:
            if isinstance(s, FunctionDef):
                # Build outer scope: params + VarDecl locals + untyped assignment targets
                outer_scope: dict = {}
                for pname, ptype in s.params:
                    outer_scope[pname] = self._resolve_type(ptype)
                # Seed var_types so _quick_type can resolve calls on typed parameters
                _saved_vt = dict(self.var_types)
                self.var_types.update(outer_scope)
                for stmt in s.body:
                    if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                        t = _mojo_type(stmt.type_ann)
                        outer_scope[stmt.name] = t
                        self.var_types[stmt.name] = t
                    elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                        if stmt.target.name not in outer_scope:
                            t = self._quick_type(stmt.value)
                            outer_scope[stmt.target.name] = t
                            self.var_types[stmt.target.name] = t
                self.var_types = _saved_vt
                _scan_for_closures(s.name, outer_scope, s.body)
            elif isinstance(s, StructDef):
                # Also scan struct methods for nested functions
                _moids = self._struct_method_overload_ids(s)
                for method, _oid in zip(s.methods, _moids):
                    outer_name = f"{s.name}_{method.name}{_oid}"
                    outer_scope = {s.name.lower(): f"{s.name} *"}  # struct instance
                    for pname, ptype in method.params:
                        if pname == 'self':
                            outer_scope['self'] = f"{s.name} *"
                        else:
                            outer_scope[pname] = self._resolve_type(ptype)
                    # Function-typed, actually-used comptime bracket parameters
                    # are threaded through as ordinary trailing parameters (see
                    # _method_threaded_comptime_params) — include them in
                    # outer_scope too, so a nested closure that references one
                    # (e.g. device_context.mojo's `wrapper` calling the
                    # enclosing method's own `func` bracket parameter) is
                    # correctly detected as a free variable and captured,
                    # instead of falling through as an unresolved bare
                    # identifier.
                    for _cp_name in self._method_threaded_comptime_params.get((s.name, method.name), {}).get(_oid, []):
                        outer_scope[_cp_name] = 'int64_t'
                    # Seed var_types so _quick_type can resolve method calls on self/params
                    _saved_vt = dict(self.var_types)
                    self.var_types.update(outer_scope)
                    for stmt in method.body:
                        if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                            t = _mojo_type(stmt.type_ann)
                            outer_scope[stmt.name] = t
                            self.var_types[stmt.name] = t
                        elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                            if stmt.target.name not in outer_scope:
                                t = self._quick_type(stmt.value)
                                outer_scope[stmt.target.name] = t
                                self.var_types[stmt.target.name] = t
                    self.var_types = _saved_vt
                    _scan_for_closures(outer_name, outer_scope, method.body)

        # ── Phase 1.6: propagate transitive captures ─────────────────────
        # If sub-closure S captures variable X from scope that intermediate
        # closure C doesn't directly use, C must also capture X so it can
        # pass it to S's env struct. Repeat until fixpoint.
        _changed = True
        while _changed:
            _changed = False
            for _outer_name, _inner_map in list(self._all_closures.items()):
                for _inner_name, _ci in list(_inner_map.items()):
                    _sub_closures = self._all_closures.get(_ci.lifted_name, {})
                    if not _sub_closures:
                        continue
                    _ci_param_names = {pn for pn, _ in _ci.inner_def.params}
                    _ci_local_assigns = set()
                    for _bstmt in _ci.inner_def.body:
                        if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                            _ci_local_assigns.add(_bstmt.target.name)
                    _ci_own_vars = (_ci_param_names
                                    | _declared_vars_body(_ci.inner_def.body)
                                    | _ci_local_assigns)
                    _ci_captures_dict = dict(_ci.captures)
                    for _sub_ci in _sub_closures.values():
                        for _sv, _st in _sub_ci.captures:
                            if _sv not in _ci_own_vars and _sv not in _ci_captures_dict:
                                _ci.captures.append((_sv, _st))
                                _ci_captures_dict[_sv] = _st
                                if not _ci.env_struct:
                                    _ci.env_struct = f"{_ci.lifted_name}_env"
                                _changed = True

        # ── Pass 3b: re-infer return types now that closures are registered ──
        # `_scan_for_closures` (Pass 3) populated `_all_closures`, which is
        # what lets `_quick_type` type a nested-function VALUE reference
        # (`return add`) as MojoBoundMethod*/void* instead of the int64_t
        # default every earlier return-type-inference pass (Pass 2 / Pass
        # 1.3e) saw. Re-run the same inference here (mirroring Pass 1.3e's
        # identical "refresh now that inputs are final" pattern, with
        # current_func_name seeded per function so the closure lookup
        # resolves) so an unannotated function whose body returns a closure
        # — `def make_adder(n): ...; return add` — gets the real value type
        # in func_return_types BEFORE Phase 2a, regardless of which
        # function's body happens to be compiled first (a call site in any
        # other function types its local from this entry).
        for _p3b_s in all_functions:
            if isinstance(_p3b_s, FunctionDef) and _p3b_s.return_type is None:
                _saved_vt_3b = self.var_types
                _saved_fcn_3b = self.current_func_name
                self.current_func_name = _p3b_s.name
                self.var_types = dict(_saved_vt_3b)
                for pname, ptype in _p3b_s.params:
                    bare = pname.lstrip('*')
                    if pname.startswith('*'):
                        self.var_types[bare] = 'MojoList *'
                    elif ptype is None:
                        self.var_types[bare] = (self._inferred_param_types.get(_p3b_s.name, {}).get(bare)
                                                or self._resolve_type(ptype))
                    else:
                        self.var_types[bare] = self._resolve_type(ptype)
                for _cln, _clt in self._closure_value_locals(_p3b_s.body).items():
                    if _cln not in self.var_types:
                        self.var_types[_cln] = _clt
                inferred = self._infer_return_type(_p3b_s.body)
                if _p3b_s.name == 'main' and inferred == 'void':
                    inferred = 'int64_t'
                self.var_types = _saved_vt_3b
                self.current_func_name = _saved_fcn_3b
                self.func_return_types[_p3b_s.name] = inferred

        # ── Phase 1.7: pre-scan global variable declarations ──────────────
        # Must run before Phase 2a so _lower_IdentExpr can find globals.
        #
        # `if <platform-check>: X = [...] else: X = [...]` (the plain-
        # assignment sibling of gen_module's own conditional-toplevel-def
        # promotion a few hundred lines up -- e.g. Lib/importlib/
        # _bootstrap_external.py's `if _MS_WINDOWS: path_separators =
        # [...] else: path_separators = [...]`) was INVISIBLE to this
        # pre-scan: the loop below only recognizes a plain top-level
        # AssignStmt, never descending into an IfStmt's branches, so such
        # a global never got a `_global_var_types`/`_elem_types` entry at
        # all here. Flatten any top-level conditional whose condition
        # resolves to a known platform-constant bool (mirroring the
        # def-promotion pass's identical resolution logic) down to just
        # its platform-correct branch's statements before scanning, the
        # same way real CPython only ever executes ONE of the branches.
        # Iterative explicit-stack traversal, NOT a self-recursive nested
        # helper -- see the def-promotion pass's own identical comment on
        # why (a nested function calling itself doesn't survive this
        # file's own self-host closure-lifting).
        def _flatten_resolved_conditionals(_root_list):
            _out = []
            _stack = [(_root_list, 0)]
            while _stack:
                _frame_body, _frame_idx = _stack[-1]
                if _frame_idx >= len(_frame_body):
                    _stack.pop()
                    continue
                _frame_stmt = _frame_body[_frame_idx]
                _stack[-1] = (_frame_body, _frame_idx + 1)
                if isinstance(_frame_stmt, IfStmt):
                    _resolved = False
                    _resolved_body = []
                    _cond_val = self._eval_const_bool(_frame_stmt.condition)
                    if _cond_val is True:
                        _resolved = True
                        _resolved_body = _frame_stmt.then_body or []
                    elif _cond_val is False:
                        _resolved = True
                        for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                            _elif_val = self._eval_const_bool(_cond2)
                            if _elif_val is True:
                                _resolved_body = _elif_body2 or []
                                break
                            if _elif_val is None:
                                _resolved = False
                                break
                        else:
                            _resolved_body = _frame_stmt.else_body or []
                    if _resolved:
                        _stack.append((_resolved_body, 0))
                    else:
                        _out.append(_frame_stmt)
                else:
                    _out.append(_frame_stmt)
            return _out

        _pre_declared_globals = set()
        _phase17_mod = self.module_name or "root"  # module name for _global_to_module mapping
        _phase17_own_stmts = _flatten_resolved_conditionals(stmts)
        _phase17_stmts = (_phase17_own_stmts
                           + (_flatten_resolved_conditionals(imported_stmts)
                              if (self.do_imports or self.link_imports) else []))
        # OWNERSHIP (which module's globals struct a name lives in,
        # `_global_to_module`) must only ever be claimed from a module's
        # OWN top-level statements, never from `imported_stmts` (the
        # whole-transitive-tree-visibility superset — see `imported_stmts`'
        # own declaration/PERF doc). `_global_to_module` is a SHARED,
        # first-writer-wins dict: if ownership could be claimed from
        # `imported_stmts` too, then whichever module's OWN Phase 1.7 scan
        # happens to run FIRST (compile order, not true ownership) would
        # permanently claim any name it discovers anywhere in the closure
        # — a real, confirmed bug (found via `mojo.py`'s own self-host
        # build): `mojo_compiler.py`'s top-level `filename = ...` (inside
        # its `if __name__ == "__main__":` block) got attributed to
        # `gimple_codegen` (an unrelated module, merely compiled earlier
        # in this particular closure) purely because gimple_codegen.py's
        # OWN Phase 1.7 scan reached mojo_compiler.py's `filename` via
        # `imported_stmts` before mojo_compiler.py's own temp_gen got a
        # chance to register it correctly. `_global_var_types` (the type-
        # only registry, still populated from the full `_phase17_stmts`
        # below) is unaffected — this only narrows OWNERSHIP attribution,
        # not type-visibility, so cross-module type inference for e.g. an
        # inherited method spliced from a different origin module (see
        # `_merge_struct_inheritance`) keeps working exactly as before.
        # See bugs/CODEGEN_generator_function_Lib_weakref.md.
        _phase17_own_ids = set(id(s) for s in _phase17_own_stmts)

        def _phase17_value_type(_value):
            """Pure mapping from an RHS AST value to the C type
            _phase17_infer_global_type would assign it — no dict writes,
            no side effects. Factored out of _phase17_infer_global_type
            (below) so the TryStmt-branch join logic (_phase17_scan_try_
            branches, further below) can compute each branch's candidate
            type using the IDENTICAL rules without duplicating this table
            under a second name that would inevitably drift out of sync.
            (List/tuple element-type tracking (_elem_types) is NOT done
            here — that's a side effect specific to the direct-assignment
            caller, not part of "what C type does this value have.")"""
            if isinstance(_value, DictExpr):
                return 'MojoDict *'
            elif isinstance(_value, (ListExpr, TupleExpr)):
                return 'MojoList *'
            elif isinstance(_value, SetExpr):
                return 'MojoSet *'
            elif isinstance(_value, (IntLiteral, BoolLiteral)):
                return 'int'
            elif isinstance(_value, StringLiteral):
                return 'char *'
            elif isinstance(_value, CallExpr):
                # `g_mod = dict()` / `g_list = list()` / `g_set = set()` — a
                # constructor CALL, not a `{...}`/`[...]`/`{elem, ...}`
                # literal AST node, so none of the DictExpr/ListExpr/SetExpr
                # branches above ever match it. Without this, it fell
                # through to the generic IdentExpr-call branch just below,
                # which only knows about USER functions (self.struct_field_types
                # / self.func_return_types) — 'dict'/'list'/'set' are neither,
                # so it silently defaulted to 'int64_t'. That wrong type,
                # recorded here in Phase 1.7 (which runs BEFORE Phase 2a
                # generates any function body), is what every function
                # reading the global sees via _global_var_types at the time
                # its OWN body is compiled — even though a separate, later
                # "Module-level globals" pass (_gscan_declare_global's own
                # sibling VarDecl branch) already special-cases this exact
                # shape correctly, that pass runs AFTER Phase 2a and so never
                # gets a chance to correct what function bodies already
                # baked in. Symptom: a global dict/list/set populated via
                # one function and read via `in`/subscript-get from another
                # silently treated the read as a bare int64_t (the `_lower_
                # in_dispatch`/subscript-get dispatch has no 'int64_t'
                # branch, so `x in g_mod` always evaluated False and
                # `g_mod[x]` always misread) even though a `for k in g_mod:`
                # in the SAME function (a separate lowering path that
                # defaults ambiguous globals to dict/falls back through
                # _get_actual_type differently) still worked — see
                # box.3d/game/bugs/DICT_global_rebound_lookup_miss_and_
                # dylib_for_segv.md. Mirrors _quick_type's own _BUILTIN_CTORS
                # map (kept as the single other place this exact mapping is
                # spelled out; not merged into one shared table because
                # _quick_type takes no `self` scan-context and is called in
                # a different pass/signature — same reasoning as the
                # existing three-way Phase-1.7/_gscan_declare_global/Module-
                # level-globals split documented on those functions).
                if (isinstance(_value.func, IdentExpr)
                        and _value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set')):
                    return {'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                            'list': 'MojoList *', 'List': 'MojoList *',
                            'set': 'MojoSet *', 'Set': 'MojoSet *'}[_value.func.name]
                if isinstance(_value.func, IdentExpr) and _value.func.name in self.struct_field_types:
                    return f"{_value.func.name} *"
                elif isinstance(_value.func, IdentExpr):
                    ret = self.func_return_types.get(_value.func.name, '')
                    if ret.endswith(' *'):
                        return ret
                    elif ret == 'char *':
                        return 'char *'
                    else:
                        return 'int64_t'
                elif (isinstance(_value.func, MemberExpr)
                        and _value.func.member in ('read', 'readline')
                        and not _value.args):
                    return 'char *'
                elif (isinstance(_value.func, MemberExpr)
                        and _value.func.member == 'readlines'):
                    return 'MojoList *'
                else:
                    return 'int64_t'
            elif (isinstance(_value, MemberExpr) and isinstance(_value.obj, IdentExpr)
                    and _value.obj.name in self.imported_symbols):
                # `X = submod.GLOBAL` — a module-level global initialized
                # from a cross-module attribute read off a real submodule
                # marker (see `_gen_stmt_FromImportStmt`'s and the top-
                # level "Process imports" pre-pass's submodule-marker
                # registration, and `_lower_MemberExpr`'s matching
                # cross-module-global-read branch). The generic `_quick_
                # type` fallback below has no notion of this shape at all
                # and always defaults it to `int64_t` — harmless for a
                # genuinely-int64_t submodule global, but WRONG for e.g. a
                # `char *` one (real case: `Lib/test/test_support.py`'s
                # `TESTFN = os_helper.TESTFN`): the outer global then gets
                # declared `int64_t` while `_lower_MemberExpr` correctly
                # reads back the real `char *` value and boxes it into that
                # `int64_t` slot — a later bare read of the outer global
                # (e.g. `print(TESTFN)`) has no way to know it's actually a
                # boxed pointer and prints the raw address as a number
                # instead of dereferencing it as a string. Resolve the
                # submodule's OWN already-known global type directly (Phase
                # 0 has already fully compiled that submodule via
                # `_compile_imported_module` and populated `_global_var_
                # types`/`_global_to_module` for it, by the time THIS
                # module's own Phase 1.7 scan runs) instead of guessing.
                _mx_mod = self.imported_symbols[_value.obj.name].get('module')
                if (_mx_mod and _value.member in self._global_var_types
                        and getattr(self, '_global_to_module', {}).get(_value.member) == _mx_mod):
                    _mx_t = self._global_var_types[_value.member]
                    if _mx_t.endswith(' *'):
                        return _mx_t
                    elif _mx_t == '_Bool':
                        return 'int'
                    else:
                        return 'int64_t'
                return 'int64_t'
            else:
                qt = self._quick_type(_value) or 'int64_t'
                if qt.endswith(' *'):
                    return qt
                elif qt == '_Bool':
                    return 'int'
                else:
                    return 'int64_t'

        def _phase17_infer_global_type(_gname, _value):
            """Infer & record a global's C type (self._global_var_types,
            plus element type for list/tuple literals) from its assigned
            RHS value. Factored out of the AssignStmt branch below so
            MultiAssignStmt (`a = b = expr`) can share the identical
            inference logic for every one of its targets — real Python
            chained-assignment semantics: all targets receive the SAME
            value, so they must all receive the SAME inferred type. Before
            this, MultiAssignStmt was entirely invisible to this pre-scan,
            so every chained-assignment global target fell through to
            whatever default 'not seen at all' implies (int64_t, via the
            unconditional "Globals are stored at C level as int64_t"
            fallback), even for an obviously-pointer-typed RHS. See
            bugs/hard/CODEGEN_multi_assign_local_var_type_not_inferred.md
            (that doc covers the LOCAL-variable analogue of this same
            gap; this is the GLOBAL/module-scope sibling)."""
            self._global_var_types[_gname] = _phase17_value_type(_value)
            if isinstance(_value, (ListExpr, TupleExpr)) and _value.elements:
                _elt = self._quick_type(_value.elements[0])
                for _e in _value.elements[1:]:
                    _elt = TypeLattice.join(_elt, self._quick_type(_e))
                self._elem_types[_gname] = _elt
                self._global_elem_types[_gname] = _elt
            elif isinstance(_value, DictExpr) and _value.pairs:
                # Dict-VALUE-type sibling of the list/tuple element-type
                # inference just above -- was never implemented at all
                # before (a global dict literal's value type had no
                # Phase 1.7 tracking whatsoever, list/tuple-only). Only
                # _global_dict_val_types (persistent) is written here, not
                # the per-function _dict_val_types directly, since that
                # one is now seeded FROM _global_dict_val_types in
                # _reset_func -- see that seed's own comment.
                _vt = self._quick_type(_value.pairs[0][1])
                for _k, _v in _value.pairs[1:]:
                    _vt = TypeLattice.join(_vt, self._quick_type(_v))
                self._global_dict_val_types[_gname] = _vt

        def _phase17_scan_try_branches(_try_stmt):
            """Collect {name: C type} for every AssignStmt/MultiAssignStmt
            target living inside a top-level TryStmt's try/except/else/
            finally bodies, TypeLattice.join-ing the type across every
            branch that assigns the same name.

            Unlike an IfStmt (where _flatten_resolved_conditionals already
            picks the ONE platform-correct branch, mirroring how real
            CPython only ever executes one side of an `if sys.platform ==
            ...`), every branch of a try/except genuinely CAN execute at
            runtime -- the `try` body if nothing raises, one `except`
            handler if a matching exception is raised, or the `else` body
            if the try body succeeds -- so a correct global type must be
            the LUB across every branch that assigns the name, not just
            the first one found textually the way the flat top-level scan
            (which only ever sees a linear sequence of unconditionally-
            executed statements) is content to do.

            Deliberately NOT self-recursive (does not call itself for a
            nested TryStmt) -- mirrors _flatten_resolved_conditionals's
            own documented reason: a nested function calling itself here
            doesn't survive this file's own self-host build. A TryStmt
            nested inside another TryStmt's branch is left unscanned by
            this pass (out of scope for this fix -- no observed real-world
            instance needs it; see bugs/hard/CODEGEN_global_prescan_
            blind_to_trystmt_and_bare_annotation.md)."""
            _branch_lists = [_try_stmt.body or []]
            for _h in (_try_stmt.handlers or []):
                _branch_lists.append(getattr(_h, 'body', None) or [])
            if isinstance(_try_stmt.else_body, list):
                _branch_lists.append(_try_stmt.else_body)
            if isinstance(getattr(_try_stmt, 'finally_body', None), list):
                _branch_lists.append(_try_stmt.finally_body)
            _joined = {}
            for _blist in _branch_lists:
                for _bstmt in _flatten_resolved_conditionals(_blist):
                    _pairs = []
                    if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                        _pairs.append((_bstmt.target.name, _bstmt.value))
                    elif isinstance(_bstmt, MultiAssignStmt):
                        for _tgt in _bstmt.targets:
                            if isinstance(_tgt, IdentExpr):
                                _pairs.append((_tgt.name, _bstmt.value))
                    for _gname, _gvalue in _pairs:
                        _t = _phase17_value_type(_gvalue)
                        _joined[_gname] = (TypeLattice.join(_joined[_gname], _t)
                                           if _gname in _joined else _t)
            return _joined

        def _phase17_scan_if_branches(_if_stmt):
            """The IfStmt sibling of `_phase17_scan_try_branches`, for a
            top-level `if`/`elif`/`else` whose condition
            `_flatten_resolved_conditionals` could NOT fold to a
            compile-time constant (e.g. `if os.name == "nt": ENCODING =
            "utf-8" else: ENCODING = sys.getfilesystemencoding()` —
            `os.name` isn't one of the handful of comptime-foldable
            expressions `_eval_const_bool` recognizes, unlike
            `sys.platform`). An unresolved IfStmt is left as a single
            nested node in `_phase17_stmts` (never flattened into its
            branches the way a resolved one is), so the flat top-level
            scan loop never saw any of its branches' assignments at all —
            a global ONLY ever assigned inside such an if/else fell
            through to the unconditional 'globals are int64_t' default,
            same failure shape as the already-fixed TryStmt gap this
            mirrors. Concretely: `ENCODING`'s struct field was correctly
            inferred `char *` from OTHER evidence (the `"utf-8"` literal
            branch happened to be visible via a different path), but
            because THIS assignment-statement-type join never ran, this
            branch's own `sys.getfilesystemencoding()` RHS kept
            defaulting through the generic int64_t/`int` fallback,
            producing an invalid `char *`-field-assigned-from-`int`
            mismatch at both branches. See
            bugs/CODEGEN_generator_function_Lib_tarfile.md.

            Deliberately NOT self-recursive for the same reason
            `_phase17_scan_try_branches` isn't (a nested function calling
            itself here doesn't survive this file's own self-host build)
            — a nested if/elif/else inside one of THIS if's own branches
            is left unscanned (out of scope; no observed real-world
            instance needs it)."""
            _branch_lists = [_if_stmt.then_body or []]
            for _cond2, _elif_body2 in (getattr(_if_stmt, 'elifs', None) or []):
                _branch_lists.append(_elif_body2 or [])
            if isinstance(_if_stmt.else_body, list):
                _branch_lists.append(_if_stmt.else_body)
            _joined = {}
            for _blist in _branch_lists:
                for _bstmt in _flatten_resolved_conditionals(_blist):
                    _pairs = []
                    if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                        _pairs.append((_bstmt.target.name, _bstmt.value))
                    elif isinstance(_bstmt, MultiAssignStmt):
                        for _tgt in _bstmt.targets:
                            if isinstance(_tgt, IdentExpr):
                                _pairs.append((_tgt.name, _bstmt.value))
                    for _gname, _gvalue in _pairs:
                        _t = _phase17_value_type(_gvalue)
                        _joined[_gname] = (TypeLattice.join(_joined[_gname], _t)
                                           if _gname in _joined else _t)
            return _joined

        for _scan_stmt in _phase17_stmts:
            if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
                _gname = _scan_stmt.target.name
                # Track `X = re.compile("literal pattern")` so a later
                # `X.finditer(...)` call (in some function compiled after this
                # module-level scan — see _gen_for_iter) can look the pattern
                # up and get a REAL regex lowering instead of falling to the
                # "unsupported iterable" fallback. See regex_compile.py and
                # BACKLOG-CODEGEN.md §4f for why this exists: re.Pattern.finditer()
                # previously had no codegen lowering at all.
                if (isinstance(_scan_stmt.value, CallExpr)
                        and isinstance(_scan_stmt.value.func, MemberExpr)
                        and isinstance(_scan_stmt.value.func.obj, IdentExpr)
                        and _scan_stmt.value.func.obj.name == 're'
                        and _scan_stmt.value.func.member == 'compile'
                        and _scan_stmt.value.args
                        and isinstance(_scan_stmt.value.args[0], StringLiteral)):
                    self._regex_patterns[_gname] = _scan_stmt.value.args[0].value
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_infer_global_type(_gname, _scan_stmt.value)
            elif isinstance(_scan_stmt, MultiAssignStmt):
                # `a = b = ... = expr` at module scope (e.g. `Modules/
                # getpath.py`'s `executable_dir = real_executable_dir =
                # value.strip()` and `prefix = exec_prefix = ''`) was
                # entirely invisible to this pre-scan — only plain
                # single-target AssignStmt was ever matched above — so
                # every target of a module-level chained assignment fell
                # through to the int64_t default regardless of the RHS's
                # real type. Mirrors the AssignStmt branch: every target
                # gets the SAME inferred type, since real Python chained
                # assignment binds every target to the identical value.
                for _tgt in _scan_stmt.targets:
                    if not isinstance(_tgt, IdentExpr):
                        continue
                    _gname = _tgt.name
                    if _gname in _pre_declared_globals:
                        continue
                    _pre_declared_globals.add(_gname)
                    if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                        self._global_to_module[_gname] = _phase17_mod
                    _phase17_infer_global_type(_gname, _scan_stmt.value)
            elif isinstance(_scan_stmt, VarDecl) and _scan_stmt.name not in _pre_declared_globals:
                _pre_declared_globals.add(_scan_stmt.name)
                if _scan_stmt.name not in self._global_to_module:
                    self._global_to_module[_scan_stmt.name] = _phase17_mod
                if _scan_stmt.type_ann:
                    _resolved = self._resolve_type(_scan_stmt.type_ann)
                    self._global_var_types[_scan_stmt.name] = _resolved
                    # MojoDict*/MojoList*/MojoSet* globals are boxed as
                    # int64_t at the C storage level (see _lower_IdentExpr's
                    # `if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    # ctype = 'int64_t'` — the actual, load-bearing read-side
                    # convention) — without this, an annotated global (`X:
                    # dict = {...}`, now a VarDecl since the parser fix that
                    # also fixed StructDef's dataclass-field visibility — see
                    # mojo_compiler.py's annotated-assignment parsing) got
                    # its struct field declared as the real pointer type
                    # directly, mismatching every read site's int64_t
                    # assumption: "assignment to 'int64_t' from 'MojoDict *'
                    # without a cast".
                    #
                    # Deliberately NARROWER than "any pointer type" (an
                    # earlier version of this comment/condition claimed
                    # _lower_IdentExpr boxes EVERY pointer-typed global
                    # unconditionally — that's not what the code there
                    # actually does: char*/struct-pointer globals are read
                    # AND declared directly, unboxed, everywhere else in
                    # this file — see _gscan_declare_global's identical
                    # MojoDict*/MojoList*/MojoSet*-only boxing a few hundred
                    # lines down in gen_module). Boxing char* here too made
                    # a bare `X: str` annotation's struct field 'int64_t'
                    # while every WRITE to X during Phase 2a (which reads
                    # THIS dict, populated here, before the struct-
                    # declaration pass further down even runs) correctly
                    # boxed a char* value into it — consistent with itself,
                    # but not with the eventual UNBOXED 'char *' struct
                    # field the struct-declaration pass declares to match
                    # _lower_IdentExpr's read side. See bugs/hard/CODEGEN_
                    # global_prescan_blind_to_trystmt_and_bare_annotation.md,
                    # "Part 2".
                    if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                else:
                    # Infer type from value if present
                    if hasattr(_scan_stmt, 'value') and _scan_stmt.value:
                        if isinstance(_scan_stmt.value, DictExpr):
                            self._global_var_types[_scan_stmt.name] = 'MojoDict *'
                            self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                        elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                            self._global_var_types[_scan_stmt.name] = 'MojoList *'
                            self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                        elif isinstance(_scan_stmt.value, SetExpr):
                            self._global_var_types[_scan_stmt.name] = 'MojoSet *'
                            self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                        elif isinstance(_scan_stmt.value, StringLiteral):
                            self._global_var_types[_scan_stmt.name] = 'char *'
                        elif (isinstance(_scan_stmt.value, CallExpr)
                                and isinstance(_scan_stmt.value.func, IdentExpr)
                                and _scan_stmt.value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set')):
                            # `var g_mod = dict()` / `= list()` / `= set()` —
                            # a constructor CALL, not a `{...}`/`[...]`
                            # literal AST node, so none of the DictExpr/
                            # ListExpr/SetExpr branches just above ever
                            # matched it; it fell through to the generic
                            # CallExpr branch below, which only recognizes
                            # USER functions via self.func_return_types —
                            # 'dict'/'list'/'set' aren't registered there, so
                            # it silently defaulted to 'int64_t'. THIS branch
                            # (Phase 1.7, which runs before Phase 2a generates
                            # any function body) is what every function
                            # reading the global actually sees — a separate,
                            # correctly-special-cased "Module-level globals"
                            # pass exists further down (_gscan_declare_global's
                            # sibling VarDecl branch) but runs AFTER Phase 2a,
                            # too late to fix what function bodies already
                            # compiled against. See _phase17_value_type's
                            # identical fix (this mirrors it exactly — kept
                            # as a separate inline branch rather than calling
                            # that helper here since this VarDecl scan also
                            # needs to set _global_c_decl_types, which the
                            # AssignStmt-oriented helper doesn't) and
                            # box.3d/game/bugs/DICT_global_rebound_lookup_
                            # miss_and_dylib_for_segv.md.
                            self._global_var_types[_scan_stmt.name] = {
                                'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                                'list': 'MojoList *', 'List': 'MojoList *',
                                'set': 'MojoSet *', 'Set': 'MojoSet *',
                            }[_scan_stmt.value.func.name]
                            self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                        elif isinstance(_scan_stmt.value, CallExpr):
                            if isinstance(_scan_stmt.value.func, IdentExpr):
                                ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                                if ret and ret.endswith(' *'):
                                    self._global_var_types[_scan_stmt.name] = ret
                                elif ret == 'char *':
                                    self._global_var_types[_scan_stmt.name] = 'char *'
                                else:
                                    self._global_var_types[_scan_stmt.name] = 'int64_t'
                            elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                    and _scan_stmt.value.func.member in ('read', 'readline')
                                    and not _scan_stmt.value.args):
                                self._global_var_types[_scan_stmt.name] = 'char *'
                            elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                    and _scan_stmt.value.func.member == 'readlines'):
                                self._global_var_types[_scan_stmt.name] = 'MojoList *'
                            else:
                                self._global_var_types[_scan_stmt.name] = 'int64_t'
                        else:
                            qt = self._quick_type(_scan_stmt.value) or 'int64_t'
                            self._global_var_types[_scan_stmt.name] = qt if (qt.endswith(' *') or qt == '_Bool') else 'int64_t'
                    else:
                        self._global_var_types[_scan_stmt.name] = 'int64_t'
            elif isinstance(_scan_stmt, TryStmt):
                # A top-level `X: T` / feature-detection global that is
                # ONLY ever assigned inside a try/except/else (e.g. Lib/
                # _pyrepl/main.py's CAN_USE_PYREPL/FAIL_REASON pattern) was
                # completely invisible to this pre-scan before: the loop
                # only ever matched AssignStmt/MultiAssignStmt/VarDecl at
                # this SAME nesting level, so every AssignStmt living
                # inside a TryStmt's branches fell straight through,
                # leaving the global's type unresolved and (per
                # _lower_IdentExpr's unconditional "globals are int64_t at
                # the C storage level" fallback used whenever this pass
                # never recorded anything) eventually causing a type-
                # incoherent placeholder initializer downstream. See
                # bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_
                # bare_annotation.md.
                for _gname, _gtype in _phase17_scan_try_branches(_scan_stmt).items():
                    if _gname in _pre_declared_globals:
                        # A preceding bare `X: T` VarDecl (handled above,
                        # in source order before this TryStmt in the real-
                        # world idiom) or an earlier plain assignment
                        # already resolved this name -- an explicit
                        # annotation/assignment always takes priority over
                        # a type merely inferred from try/except branches.
                        continue
                    _pre_declared_globals.add(_gname)
                    if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                        self._global_to_module[_gname] = _phase17_mod
                    self._global_var_types[_gname] = _gtype
            elif isinstance(_scan_stmt, IfStmt):
                # See _phase17_scan_if_branches' own docstring: an IfStmt
                # whose condition couldn't be comptime-folded away by
                # _flatten_resolved_conditionals (so it still appears here
                # as a single nested node, not inlined into its winning
                # branch) was previously invisible to this pre-scan.
                for _gname, _gtype in _phase17_scan_if_branches(_scan_stmt).items():
                    if _gname in _pre_declared_globals:
                        continue
                    _pre_declared_globals.add(_gname)
                    if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                        self._global_to_module[_gname] = _phase17_mod
                    self._global_var_types[_gname] = _gtype
            elif (isinstance(_scan_stmt, ComptimeVarStmt)
                    and isinstance(_scan_stmt.value, (ListExpr, TupleExpr))
                    and _scan_stmt.target not in _pre_declared_globals):
                # A top-level `comptime NAME = [literal, literal, ...]` (e.g.
                # box.3d/game's `comptime DIR_OFFSETS: [Int; 18] = [0, 0,
                # -1, ...]`) is real Mojo — compile-time-KNOWN VALUE, not a
                # compile-time-ONLY construct: ordinary Mojo code is free to
                # read it at runtime with a DYNAMIC (non-constant) index,
                # e.g. `DIR_OFFSETS[direction * 3]`. Before this branch, a
                # top-level ComptimeVarStmt was invisible to this whole
                # Phase 1.7 pre-scan (it only matches AssignStmt/
                # MultiAssignStmt/VarDecl/TryStmt/IfStmt) — the parser also
                # discards the `[Int; 18]` type annotation entirely for
                # `comptime` statements (see mojo_compiler.py's
                # `_parse_comptime`, "parse and discard type annotation"),
                # so nothing downstream ever learned this name denotes a
                # real array. `_lower_IdentExpr` then fell through to its
                # final "unknown identifier" placeholder (int64_t 0) for
                # every ordinary (non-materialize[]) read of the name, and
                # subscripting that placeholder degraded to indexing a NULL
                # MojoList* (returns 0, doesn't crash) — every element of
                # the array silently read as 0 forever. Registering the
                # SAME type-inference here as an equivalent AssignStmt
                # would (`_phase17_infer_global_type`) makes this a real
                # 'MojoList *' global exactly like `var NAME = [...]` at
                # module scope; the matching toplevel-codegen branch (see
                # this file's other `ComptimeVarStmt` case in the top-level
                # statement dispatch loop) builds the actual backing list
                # at startup so subscripting it now indexes real memory.
                # This does not disturb the EXISTING compile-time-only
                # consumers of a comptime list (`materialize[NAME]()`
                # unrolling, `_comptime_list_asts`) — those are checked at
                # their own call sites before any of this runtime machinery
                # is ever reached. Found via box.3d/game's BUG-2026-011:
                # `_get_adjacent_block`'s `DIR_OFFSETS[direction * 3]`
                # always read (0, 0, 0), so every "neighbor" lookup silently
                # resolved to the block asking the question, and a redstone
                # counter's clock input never saw its lever's real signal.
                _pre_declared_globals.add(_scan_stmt.target)
                if _scan_stmt.target not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_scan_stmt.target] = _phase17_mod
                _phase17_infer_global_type(_scan_stmt.target, _scan_stmt.value)

        # A module-level `var g: list()` / `var g = list()` (no literal
        # elements ever — the empty-at-declaration idiom, e.g. box.3d/
        # game/lib/recipes.mojo's `g_item_names`/`g_item_ids`) has NO
        # element type any of the branches above can see: they only ever
        # look at the declaration's own literal elements (`_elt =
        # self._quick_type(_value.elements[0])` above), and an empty/
        # constructor-call declaration has none. Such a global is
        # populated exclusively via `.append(...)` calls in some OTHER
        # function (e.g. `register_item_name`), read via subscript/`in`/
        # iteration in yet another (e.g. `_name_to_id`) — cross-function,
        # usage-only element-type inference that nothing above attempts.
        # Left unresolved, `_elem_types`/`_global_elem_types` stays empty
        # for these globals and every later list-element codegen path
        # (_lower_subscript's list-get, `.append` itself, `for x in g:`)
        # falls back to its int64_t default: every STRING actually
        # `.append()`-ed gets correctly stored via `mojo_list_append_str`
        # (append lowering resolves the element type from the ARGUMENT's
        # own type, not the global's), but every READ instead did
        # `(char)mojo_list_get_int(...)` — truncating the stored string
        # POINTER to its low byte and reinterpreting that single byte as
        # a 1-char string. `len()` and the append itself are unaffected
        # (the list is genuinely shared/populated correctly — only
        # element READS silently misread), which is exactly why this
        # shape is easy to miss: nothing crashes, nothing is empty, only
        # every stored value reads back wrong. See box.3d/game/bugs/
        # DYLIB_dict_int_key_strdup_null.md's final section.
        #
        # Fix: for every global already known to be a MojoList* (boxed
        # int64_t at the C storage level) that STILL has no element type
        # after the scan above, walk the ENTIRE module (own + imported,
        # matching _phase17_stmts' own scope — an appending function need
        # not be textually before its global's declaration) looking for
        # `<name>.append(<expr>)` call sites anywhere, including nested
        # inside other functions/if/while/for/try/with bodies, and
        # TypeLattice.join the argument's _quick_type across every site
        # found. Mirrors _infer_local_var_types' own param-seeding
        # pattern: since this runs before Phase 2a populates var_types
        # per-function, a function's own annotated parameters (e.g.
        # `name: String`) must be seeded temporarily so `_quick_type` of
        # a bare identifier argument (`g_item_names.append(name)`)
        # resolves to 'char *' instead of falling through to the int64_t
        # "unknown identifier" default.
        def _phase17_collect_appends(_node_list, _append_hits):
            for _n in _node_list:
                if (isinstance(_n, ExprStmt)
                        and isinstance(_n.value, CallExpr)
                        and isinstance(_n.value.func, MemberExpr)
                        and _n.value.func.member == 'append'
                        and isinstance(_n.value.func.obj, IdentExpr)
                        and len(_n.value.args) == 1):
                    # Resolve the argument's type NOW, while self.var_types
                    # still carries whatever function-parameter seeding is
                    # active for this call site (see the FunctionDef branch
                    # below) -- deferring to a later pass (after that seeding
                    # has been restored) would silently lose it and infer
                    # every string-typed parameter argument as int64_t again.
                    _append_hits.setdefault(_n.value.func.obj.name, []).append(
                        self._quick_type(_n.value.args[0]))
                if isinstance(_n, FunctionDef):
                    _saved = self.var_types
                    self.var_types = dict(_saved)
                    for _pname, _ptype in (_n.params or []):
                        if _ptype:
                            self.var_types[_pname] = _mojo_type(_ptype)
                    # Also seed LOCAL (walrus/assign) variable types, not just
                    # annotated params -- e.g. `r := ShapedRecipe(); g_list.
                    # append(r)`. Without this, `_quick_type(IdentExpr('r'))`
                    # below finds no var_types entry and falls through to its
                    # int64_t default, so a global struct list populated only
                    # via a local-var append (never a literal or a bare-param
                    # append) gets no element type at all. Every subsequent
                    # `g_list[i]` read then emits `mojo_list_get_int`, which
                    # reads only the boxed pointer's first 8 bytes worth of
                    # dispatch instead of the real struct pointer -- see
                    # box.3d/game/bugs/DYLIB_struct_list_index_reads_first_
                    # field_only_wrong_craft_results.md (game/lib/recipes.mojo's
                    # `register_shaped_recipe` etc.).
                    for _lname, _ltype in self._infer_local_var_types(_n).items():
                        if _lname not in self.var_types:
                            self.var_types[_lname] = _ltype
                    _phase17_collect_appends(_n.body or [], _append_hits)
                    self.var_types = _saved
                elif isinstance(_n, IfStmt):
                    _phase17_collect_appends(_n.then_body or [], _append_hits)
                    if _n.else_body:
                        _phase17_collect_appends(_n.else_body, _append_hits)
                    for _cond2, _ebody2 in (_n.elifs or []):
                        _phase17_collect_appends(_ebody2 or [], _append_hits)
                elif isinstance(_n, (WhileStmt, ForStmt)):
                    _phase17_collect_appends(_n.body or [], _append_hits)
                    if getattr(_n, 'else_body', None):
                        _phase17_collect_appends(_n.else_body, _append_hits)
                elif isinstance(_n, TryStmt):
                    _phase17_collect_appends(_n.body or [], _append_hits)
                    for _h in (_n.handlers or []):
                        _phase17_collect_appends(getattr(_h, 'body', None) or [], _append_hits)
                    if isinstance(_n.else_body, list):
                        _phase17_collect_appends(_n.else_body, _append_hits)
                    if isinstance(getattr(_n, 'finally_body', None), list):
                        _phase17_collect_appends(_n.finally_body, _append_hits)
                elif isinstance(_n, WithStmt):
                    _phase17_collect_appends(_n.body or [], _append_hits)

        _phase17_append_hits: dict = {}
        _phase17_collect_appends(_phase17_stmts, _phase17_append_hits)
        for _gname, _gargs in _phase17_append_hits.items():
            if self._global_var_types.get(_gname) != 'MojoList *':
                continue
            if _gname in self._global_elem_types:
                continue
            _elt = None
            for _at in _gargs:
                _elt = _at if _elt is None else TypeLattice.join(_elt, _at)
            if _elt:
                self._elem_types[_gname] = _elt
                self._global_elem_types[_gname] = _elt

        # Also scan ImportStmts inside TryStmt/IfStmt blocks (e.g., try: import mojo_compiler)
        # These are missed by the flat scan above.
        def _scan_try_imports(stmt_list):
            for _s in stmt_list:
                if isinstance(_s, ImportStmt):
                    for _tm, _ta in _import_targets(_s):
                        _local = _ta if _ta else _tm
                        if _local not in self._global_var_types:
                            self._global_var_types[_local] = 'int64_t'
                            self._global_c_decl_types[_local] = 'int64_t'
                            if _local not in self._global_to_module:
                                self._global_to_module[_local] = _phase17_mod
                elif isinstance(_s, TryStmt):
                    _scan_try_imports(_s.body or [])
                    for _h in (_s.handlers or []):
                        _scan_try_imports(getattr(_h, 'body', []) or [])
                elif isinstance(_s, IfStmt):
                    _scan_try_imports(_s.then_body or [])
                    if isinstance(_s.else_body, list):
                        _scan_try_imports(_s.else_body)
        _scan_try_imports(stmts + (imported_stmts if (self.do_imports or self.link_imports) else []))

        # Pre-populate _global_c_decl_types from _global_var_types so Phase 2a
        # generates correct loads for globals whose C type is a pointer (not boxed int64_t).
        _EARLY_DISPATCH_DICTS = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                                 '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
        _EARLY_DISPATCH_SETS = {'_CMP_OPS'}
        for _gn, _gt in list(self._global_var_types.items()):
            if _gn in self._global_c_decl_types:
                continue
            if _gn in _EARLY_DISPATCH_DICTS:
                self._global_c_decl_types[_gn] = 'MojoDict *'
            elif _gn in _EARLY_DISPATCH_SETS:
                self._global_c_decl_types[_gn] = 'MojoSet *'
            elif _gt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                self._global_c_decl_types[_gn] = 'int64_t'  # boxed by default
            else:
                self._global_c_decl_types[_gn] = _gt

        # ── Phase 2a: generate all function bodies ────────────────────────
        # This pass populates _ptr_helpers_needed and _struct_allocs_needed
        # so the preamble helpers can be emitted before the __GIMPLE bodies.

        func_parts: list[str] = []

        _emitted_closures: set[str] = set()

        def _emit_closure_recursive(ci, outer_name: str = None) -> None:
            """Emit sub-closures first (depth-first), then this closure's allocator + body."""
            # Deduplicate: overloaded methods share the same closure outer_name, so
            # the same lifted closure may be emitted multiple times (once per overload).
            if ci.lifted_name in _emitted_closures:
                return
            _emitted_closures.add(ci.lifted_name)
            for sub_ci in self._all_closures.get(ci.lifted_name, {}).values():
                _emit_closure_recursive(sub_ci, ci.lifted_name)
            if ci.env_struct:
                alloc_fn = f"_alloc_{ci.env_struct}"
                func_parts.append(
                    f"{ci.env_struct} * __GIMPLE {alloc_fn} (void)\n"
                    f"{{\n"
                    f"  {ci.env_struct} * _e;\n"
                    f"  void * _vp;\n"
                    f"\nbb_2:\n"
                    f"  _vp = malloc (sizeof({ci.env_struct}));\n"
                    f"  _e = ({ci.env_struct} *) _vp;\n"
                    f"  return _e;\n"
                    f"}}"
                )
                func_parts.append('')
            func_parts.append(self._gen_lifted_closure(ci, outer_name))
            func_parts.append('')

        # Collect top-level statements for _toplevel() function
        toplevel_stmts = []

        # Pre-scan so the main() wrapper (emitted by _gen_function below, before
        # has_toplevel_code is known) can decide whether to call _toplevel().
        # If there is no top-level code we trim the call entirely; otherwise the
        # _toplevel() function is emitted and the call links.
        _toplevel_types = (AssignStmt, AugAssignStmt, ExprStmt,
                           IfStmt, WhileStmt, ForStmt,
                           TryStmt, WithStmt, PassStmt,
                           BreakStmt, ContinueStmt, ReturnStmt,
                           RaiseStmt, AssertStmt, VarDecl)
        self._has_toplevel_code = False
        for _ts in stmts:
            if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
                self._has_toplevel_code = True
                break
            # A top-level `comptime NAME = [literal, ...]` is synthesized
            # into a real runtime-init AssignStmt further down (see this
            # file's other ComptimeVarStmt/ListExpr branches) and DOES need
            # `_toplevel()` called — this pre-scan runs first (the `main()`
            # wrapper it feeds is emitted before the real toplevel_stmts
            # collection below), so it needs the identical condition or the
            # call to `_toplevel()` gets trimmed as dead even though the
            # function now has real initialization code in it.
            if isinstance(_ts, ComptimeVarStmt) and isinstance(_ts.value, (ListExpr, TupleExpr)):
                self._has_toplevel_code = True
                break
        # Step I (create_task/Task/TaskGroup/RaisingTask project): a REAL,
        # pre-existing bug found while getting a real behavioral (compile+
        # link+RUN) verification of test_raising_asyncrt.mojo working —
        # NOT something new this project introduced, but exposed by it
        # (compile_stdlib.py's own gate never actually RUNS anything, only
        # `gcc -fsyntax-only`, so this was invisible to every existing
        # quality gate). `gen_func`'s wrapper for a module's own `def
        # main():` (see its own comment there) assumed ANY top-level code
        # at all means "the top-level code itself already calls main() —
        # e.g. `if __name__ == '__main__': main()`" and therefore skips
        # calling the compiled main function directly, relying entirely on
        # `_toplevel()` to do it. That assumption is FALSE for a real Mojo
        # program's top-level MODULE DOCSTRING (`"""...""""` as the file's
        # first statement — an ordinary, harmless top-level `ExprStmt`,
        # extremely common in real Mojo/stdlib source, ubiquitous in every
        # test file) with NO `__name__` guard at all (real Mojo has no
        # `__name__`/`__main__` convention — `main()` is just the direct,
        # unconditional program entry point) — the compiled binary would
        # silently do NOTHING and exit 0, "looking" like a clean, silent
        # success while actually never running a single line of the
        # program. Confirmed via a minimal repro
        # (`"""doc"""\ndef main(): print(42)`) — `int main` called only
        # `_toplevel()`, whose own body was just the inert docstring
        # assignment, and `42` was never printed.
        #
        # Distinguishes the two cases correctly instead of guessing: does
        # ANY top-level statement actually contain a call to `main(...)`
        # anywhere in its own subtree (the real `if __name__ ==
        # '__main__': main()` shape, and anything structurally
        # equivalent)? If so, unchanged behavior (`_toplevel()` alone,
        # avoiding the ORIGINAL double-invocation bug this code was built
        # to prevent). If not, `gen_func`'s wrapper now calls BOTH
        # `_toplevel()` (for whatever real top-level side effects exist)
        # AND the compiled main function directly — the correct behavior
        # for the common, unconditional-`main()` case this always should
        # have handled.
        self._toplevel_calls_main = False
        for _ts in stmts:
            if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
                for _n in _walk_ast(_ts):
                    if isinstance(_n, CallExpr) and isinstance(_n.func, IdentExpr) and _n.func.name == 'main':
                        self._toplevel_calls_main = True
                        break
                if self._toplevel_calls_main:
                    break

        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                if (stmt.name in self._supported_generators or stmt.name in self._supported_async
                        or stmt.name in self._supported_async_gen):
                    # Milestone B / Step B: this function's body was already
                    # fully translated to C++20 coroutine text by the pre-
                    # pass above (self._generator_cpp_units, which holds both
                    # generator AND async fragments — see gen_module's two
                    # pre-pass loops) — it gets NO ordinary -fgimple C body
                    # here at all; only its extern "C" API forward
                    # declarations appear in this .c/.ci output (see the
                    # preamble emission and the free-function forward-decl
                    # loop below, both gated the same way).
                    continue
                if stmt.name in self._unsupported_generator_names:
                    # See _unsupported_generator_names's docstring: this
                    # generator/async function failed C++ translation and was
                    # stub-declared instead (relaxed_imports). It must NOT
                    # also get an ordinary body here — gen_func has no idea
                    # how to lower `yield`, and a second, differently-shaped
                    # definition of the same C symbol is a hard conflicting-
                    # types compile error, not just wasted work.
                    continue
                # Step I: scoped push — temporarily expose this function's
                # own nested async helpers (compiled earlier by
                # gen_module's own _compile_nested_async_functions pass,
                # under a QUALIFIED key — see self._nested_async_api's
                # docstring) into self._async_api under their bare names,
                # for the duration of THIS ONE function's body compile
                # only, so create_task(wrapper())/await composition inside
                # it resolve exactly like a top-level async function would.
                # Popped again right after (whether or not gen_func raises
                # — see `finally`), so a later, unrelated top-level
                # function never sees a stale entry belonging to a
                # DIFFERENT enclosing function's same-named nested helper.
                #
                # Pushed BEFORE the closure-lifting loop just below too
                # (not only around `gen_func`, its original, narrower
                # scope) — test_locks.mojo's own real shape: `inc()` is
                # nested directly in `test_basic_lock`, but CALLED (via
                # `tg.create_task(inc())`) from `test_atomic()`, a
                # DIFFERENT ordinary nested function ALSO declared inside
                # `test_basic_lock` and compiled via the GENERAL (non-
                # async) closure-LIFTING mechanism (`_emit_closure_
                # recursive`/`_gen_lifted_closure`), a separate code path
                # from `gen_func` that this push never used to cover — a
                # real, hand-verified gap: `tg.create_task(inc())` inside a
                # sibling lifted closure found no entry for `inc` in self.
                # _async_api at all (the push hadn't happened yet), and hit
                # `TaskGroup.create_task(...)`'s own "not a call to a
                # known compiled async unit" refusal.
                _nested_pushed = []
                _prefix = f"{stmt.name}::"
                for _qn, _info in self._nested_async_api.items():
                    if _qn.startswith(_prefix):
                        _nm = _info['nested_name']
                        self._async_api[_nm] = _info
                        _nested_pushed.append(_nm)
                # A `comptime NAME = <value>` declared directly in `stmt`'s
                # own top-level body is normally only folded into `self.
                # _comptime_vals` when `_gen_stmt_ComptimeVarStmt` actually
                # RUNS, during `gen_func(stmt)` below -- too late for any
                # NESTED closure of `stmt` that references it (`range(0,
                # maxI)`-shaped, test_locks.mojo's own `test_atomic()`
                # idiom), since `_emit_closure_recursive` just below
                # compiles every nested closure BEFORE `gen_func(stmt)`
                # ever runs. Pre-fold them here first -- pure compile-time
                # constant folding, no runtime state involved, so doing it
                # early is always safe. A hand-verified real bug: without
                # this, `range(0, maxI)` inside a nested closure silently
                # read `maxI` as `0` (the same "ct param or undeclared"
                # placeholder `_lower_IdentExpr`'s comptime fallback uses
                # for a genuinely unresolvable name), not a compile error —
                # exactly the kind of silent miscompile CLAUDE.md forbids.
                for _cvs in stmt.body:
                    if isinstance(_cvs, ComptimeVarStmt):
                        _cv = self._eval_const(_cvs.value)
                        if _cv is not None:
                            self._comptime_vals.setdefault(_cvs.target, _cv)
                # Per-lexical-scope import tracking: the enclosing function's
                # own body is a scope, and it must stay active while this
                # function's nested CLOSURES are emitted too — closures are
                # emitted BEFORE gen_func(stmt) below, so without this frame a
                # nested def's body could not resolve a name the enclosing
                # function imported locally (a legitimate Mojo pattern). The
                # frame is kept through closure emission AND gen_func (which
                # pushes/pops its own narrower frame on top), then popped.
                _func_outer_scope = self._push_import_scope()
                self._collect_body_import_bindings(stmt.body, _func_outer_scope)
                try:
                    for ci in self._all_closures.get(stmt.name, {}).values():
                        _emit_closure_recursive(ci, stmt.name)
                    self._lambda_parts = []
                    func_parts.append(self.gen_func(stmt))
                finally:
                    self._pop_import_scope()
                    for _nm in _nested_pushed:
                        self._async_api.pop(_nm, None)
                # Flush any lambdas lifted during gen_func, emitting them
                # immediately before the enclosing function body so forward
                # declarations in the preamble resolve correctly.
                if self._lambda_parts:
                    func_parts.extend(self._lambda_parts)
                    self._lambda_parts = []
                func_parts.append('')
            elif isinstance(stmt, StructDef):
                # Overload IDs aligned with stmt.methods; the closure-emit, the
                # method symbol, and the pre-pass closure registration all key by
                # the same overload-suffixed name (so overloaded methods with
                # nested closures don't share capture state).
                _moids = self._struct_method_overload_ids(stmt)
                for m, overload_id in zip(stmt.methods, _moids):
                    if (stmt.name, m.name) in self._supported_generator_methods:
                        # Milestone C step 3: this method's body was already
                        # fully translated to C++20 coroutine text by the
                        # pre-pass above (self._generator_cpp_units) — same
                        # as a supported free-function generator (see the
                        # analogous FunctionDef skip just above), it gets NO
                        # ordinary -fgimple C body here at all.
                        continue
                    method_outer_name = f"{stmt.name}_{m.name}{overload_id}"
                    # Emit lifted closures for this method (if any), recursively
                    # — with the method's own body as an enclosing lexical
                    # scope so a nested closure can resolve a name the method
                    # imported locally (see the same wrapping for free
                    # functions in the FunctionDef branch above).
                    _method_outer_scope = self._push_import_scope()
                    self._collect_body_import_bindings(m.body, _method_outer_scope)
                    for ci in self._all_closures.get(method_outer_name, {}).values():
                        _emit_closure_recursive(ci, method_outer_name)
                    self._lambda_parts = []
                    func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                    func_parts.append('')
                    self._pop_import_scope()
                    # Flush any lambdas lifted during this method's body (see
                    # the identical flush for top-level FunctionDefs above,
                    # whose comment explains why body ORDER doesn't matter —
                    # the forward decl already lives in the preamble). Without
                    # this, a lambda inside a struct method (e.g. a
                    # `@classmethod`'s `return lambda *a, **k: ...`) got its
                    # forward declaration AND static function-pointer
                    # initializer emitted (both registered unconditionally by
                    # `_lower_LambdaExpr`), but the actual lifted C function
                    # DEFINITION accumulated in `self._lambda_parts` was never
                    # flushed anywhere for the struct-method code path — a
                    # silent "declared but never defined" link failure.
                    # Confirmed via importlib/util.py's `LazyLoader.factory`
                    # classmethod: `return lambda *args, **kwargs: cls(loader(
                    # *args, **kwargs))` linked as an undefined symbol
                    # (`_LazyLoader_factory_lambda_1`) despite compiling clean.
                    if self._lambda_parts:
                        func_parts.extend(self._lambda_parts)
                        self._lambda_parts = []
            elif isinstance(stmt, TraitDef):
                lines = [f"typedef struct {stmt.name}_vtable {{"]
                _seen_vtable_members: set = set()
                for m in stmt.methods:
                    safe_mname = _safe_name(m.name)
                    if safe_mname in _seen_vtable_members:
                        continue
                    _seen_vtable_members.add(safe_mname)
                    ret    = self._resolve_type(m.return_type)
                    if m.params and any(pn.startswith('*') for pn, _ in m.params):
                        ptypes = 'MojoList *'
                    else:
                        ptypes = (', '.join(self._resolve_type(pt) for _, pt in m.params)
                                  if m.params else 'void')
                    lines.append(f"  {ret} (*{safe_mname}) ({ptypes});")
                lines.append(f"}} {stmt.name}_vtable;")
                func_parts.extend(lines)
                func_parts.append('')
            elif isinstance(stmt, (ImportStmt, FromImportStmt)):
                pass  # Imports processed in pre-pass; extern declarations generated in preamble
            elif (isinstance(stmt, ComptimeVarStmt)
                    and isinstance(stmt.value, (ListExpr, TupleExpr))):
                # A top-level `comptime NAME = [literal, ...]` needs REAL
                # runtime backing storage, not just compile-time folding —
                # see this file's matching Phase 1.7 branch (same
                # ComptimeVarStmt/ListExpr condition, a few thousand lines
                # up) for the full why. Synthesize the equivalent
                # `NAME = [literal, ...]` AssignStmt and feed it through the
                # SAME toplevel-init codegen every ordinary module-level
                # list global already uses (builds the real MojoList* via
                # runtime append calls at startup) — this reuses that
                # machinery exactly rather than duplicating a second list-
                # construction path. A plain `comptime NAME = 4096` (or any
                # non-list value) is unaffected: it isn't a ListExpr, so
                # this branch never matches, and it keeps its existing
                # pure-compile-time-fold-only handling.
                toplevel_stmts.append(AssignStmt(
                    target=IdentExpr(stmt.target, line=stmt.line, col=stmt.col),
                    value=stmt.value, line=stmt.line, col=stmt.col))
            elif isinstance(stmt, (AssignStmt, AugAssignStmt, MultiAssignStmt,
                                   ExprStmt, IfStmt, WhileStmt, ForStmt,
                                   TryStmt, WithStmt, PassStmt,
                                   BreakStmt, ContinueStmt, ReturnStmt,
                                   RaiseStmt, AssertStmt, VarDecl)):
                # Collect all executable statements for _toplevel()
                toplevel_stmts.append(stmt)
            else:
                _debug_note('top-level statement dropped', type(stmt).__name__)
                func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

        # Populate func_param_types BEFORE _gen_toplevel so call-site coercion works
        # This must happen before _gen_toplevel since it needs param types for _emit_call
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        for fn in func_defs:
            if fn.name == 'main':
                continue
            if fn.params and any(pn.startswith('*') for pn, _ in fn.params):
                self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
                self._note_vararg_trailing_param_types(fn)
            else:
                inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
                param_ctypes = []
                for pn, pt in (fn.params or []):
                    if pn in inferred_params:
                        param_ctypes.append(inferred_params[pn])
                    else:
                        param_ctypes.append(self._param_ctype(pn, pt, fn))
                self.func_param_types[fn.name] = param_ctypes

        # Only generate _toplevel() if there are actual top-level statements
        has_toplevel_code = len(toplevel_stmts) > 0
        if has_toplevel_code:
            toplevel_func = self._gen_toplevel(toplevel_stmts)
            func_parts.append(toplevel_func)
            func_parts.append('')
            # In library mode, register the sub-module toplevel for the root to call
            if not self.emit_entry_points:
                sub_fn = _module_toplevel_name(self.module_name)
                if sub_fn not in self._sub_toplevels:
                    self._sub_toplevels.append(sub_fn)
                # bugs/DYLIB_module_scope_never_executes.md (box.3d/game repo):
                # a standalone `mojo dylib` compile of THIS module (do_imports
                # is False here — an imported sibling pulled into an
                # EXECUTABLE's own translation unit sets do_imports=True and
                # is deliberately excluded below; its toplevel already runs
                # correctly via the executable's own `main()` wrapper calling
                # `_sub_toplevels` explicitly, and giving it an automatic
                # ctor too would fire before that `main()`'s Py_Initialize(),
                # which is unsafe for USE_PYTHON code even though it's
                # otherwise harmless thanks to the one-shot guard in
                # `_gen_toplevel`) has no `main()`/`_gimple_main` at all in
                # its own ABI — nothing EVER calls `sub_fn`. Fix: emit an
                # automatic `__attribute__((constructor))` (fires at dlopen
                # time with no C host cooperation needed) AND export a
                # documented `<module>_init()` alias a C host may call
                # explicitly instead/as well — both simply call `sub_fn`,
                # which is itself one-shot-guarded, so any combination of
                # "ctor already ran it" / "host also called `<module>_init`"
                # is safe, never a double-init.
                if not self.do_imports:
                    init_fn = _module_init_name(self.module_name)
                    func_parts.append(f"__attribute__((constructor)) static void {sub_fn}_ctor (void)")
                    func_parts.append("{")
                    func_parts.append(f"  {sub_fn} ();")
                    func_parts.append("}")
                    func_parts.append('')
                    func_parts.append(f"void {init_fn} (void)")
                    func_parts.append("{")
                    func_parts.append(f"  {sub_fn} ();")
                    func_parts.append("}")
                    func_parts.append('')

        # Only generate entry points (main/_gimple_main) for the root module
        if self.emit_entry_points:
            has_main = False
            for _hs in stmts:
                if isinstance(_hs, FunctionDef) and _hs.name == 'main':
                    has_main = True
                    break
            if not has_main:
                func_parts.append("int _gimple_main (void)")
                func_parts.append("{")
                func_parts.append("  return 0;")
                func_parts.append("}")
                func_parts.append("")
                func_parts.append("int main (int argc, const char **argv) {")
                func_parts.append("  mojo_set_argv(argc, argv);")
                func_parts.append("#if USE_PYTHON")
                func_parts.append("  Py_Initialize ();")
                func_parts.append("#endif")
                # Call sub-module toplevels first
                for sub_fn in self._sub_toplevels:
                    func_parts.append(f"  {sub_fn} ();")
                # Then call root's own _toplevel if it has top-level code
                if has_toplevel_code:
                    func_parts.append("  _toplevel ();")
                func_parts.append("#if USE_PYTHON")
                func_parts.append("  Py_Finalize ();")
                func_parts.append("#endif")
                func_parts.append("  return 0;")
                func_parts.append("}")

        # ── Phase 2b: assemble final C output ────────────────────────────

        parts = [
            '/* Generated by gimple_codegen.py */',
            '/* Compile with: gcc -fgimple -fsyntax-only file.c (uses gcc-15 if available) */',
            '#define USE_PYTHON 1' if self._python_api_needed else '#define USE_PYTHON 0',
            '#include <stdint.h>',
            '#include <stdlib.h>',
            '#include <string.h>',
            '#include <math.h>',
            '#include <stdio.h>',
            '#include <setjmp.h>',
            '#include <dlfcn.h>',
            '#if USE_PYTHON',
            '#include <Python.h>',
            '#endif',
            '#include <mojo_runtime.h>',
            '#include <mojo_sqlite3.h>',
            '#include <mojo_zlib.h>',
            '#include <mojo_ssl.h>',
            '#include <mojo_ncurses.h>',
            '/* Disable security wrappers: sprintf/snprintf/memcpy/memmove/memset/',
            '   strcpy/strncpy/strcat/strncat macros expand to nested',
            '   __builtin___*_chk calls which GIMPLE rejects (confirmed for memcpy:',
            '   a bare memcpy(dst, src, n) call expanded to',
            '   __builtin___memcpy_chk(dst, src, n, __builtin_object_size(dst, 0))',
            '   and broke every cold-CAS-cache stdlib build via List[T].extend,',
            '   investigated 2026-07-15 — the other _FORTIFY_SOURCE-wrapped libc',
            '   functions below are the same class of bug, pre-empted before they',
            '   bite the same way). */',
            '#ifdef sprintf',
            '#undef sprintf',
            '#endif',
            '#ifdef snprintf',
            '#undef snprintf',
            '#endif',
            '#ifdef memcpy',
            '#undef memcpy',
            '#endif',
            '#ifdef memmove',
            '#undef memmove',
            '#endif',
            '#ifdef memset',
            '#undef memset',
            '#endif',
            '#ifdef strcpy',
            '#undef strcpy',
            '#endif',
            '#ifdef strncpy',
            '#undef strncpy',
            '#endif',
            '#ifdef strcat',
            '#undef strcat',
            '#endif',
            '#ifdef strncat',
            '#undef strncat',
            '#endif',
            '/* Undefine exception-name macros from mojo_runtime.h that clash with',
            '   Mojo struct/class names in generated code. */',
            '#ifdef StopIteration',
            '#undef StopIteration',
            '#endif',
            '#ifdef ValueError',
            '#undef ValueError',
            '#endif',
            '#ifdef TypeError',
            '#undef TypeError',
            '#endif',
            '#ifdef IndexError',
            '#undef IndexError',
            '#endif',
            '#ifdef KeyError',
            '#undef KeyError',
            '#endif',
            '#ifdef NotImplementedError',
            '#undef NotImplementedError',
            '#endif',
            'void mojo_print(char *str);',
        ]
        # Forward declarations for sub-module toplevels and root toplevel
        if self.emit_entry_points:
            # Root module: forward-declare all sub-module toplevels
            for sub_fn in self._sub_toplevels:
                parts.append(f'void {sub_fn}(void);')
            # Forward-declare root's own _toplevel if it has top-level code
            if has_toplevel_code:
                parts.append('void _toplevel(void);')
        else:
            # Library module: forward-declare this module's own toplevel if it has one
            if has_toplevel_code:
                fn_name = _module_toplevel_name(self.module_name)
                parts.append(f'void {fn_name}(void);')
        # Built-in type constructor stubs: only emit for names not defined as
        # structs in this module AND not imported (both would conflict with the
        # function declaration).
        _local_structs = set(self.struct_field_types.keys())
        _imported_names = set(self.imported_symbols.keys())
        _skip_ctors = _local_structs | _imported_names
        _builtin_ctors = [
            # Use (...) so any argument type is accepted — these are stubs for
            # Mojo type constructors whose call signatures vary widely at use sites.
            ('String',   'int64_t String(...);'),             # FIXME: should be char *String(void *value) [takes any Python object, returns char *]
            ('Int',      'int64_t Int(...);'),                # FIXME: should be int64_t Int(void *value) [takes any Python object, returns int64_t]
            ('UInt',     'int64_t UInt(...);'),               # FIXME: should be uint64_t UInt(void *value)
            ('Bool',     'int64_t Bool(...);'),               # FIXME: should be _Bool Bool(void *value)
            ('Int8',     'int64_t Int8(...);'),
            ('Int16',    'int64_t Int16(...);'),
            ('Int32',    'int64_t Int32(...);'),
            ('Int64',    'int64_t Int64(...);'),
            ('UInt8',    'int64_t UInt8(...);'),
            ('UInt16',   'int64_t UInt16(...);'),
            ('UInt32',   'int64_t UInt32(...);'),
            ('UInt64',   'int64_t UInt64(...);'),
            ('Float16',  'int64_t Float16(...);'),            # FIXME: should be float16_t Float16(void *value)
            ('BFloat16', 'int64_t BFloat16(...);'),           # FIXME: should be bfloat16_t BFloat16(void *value)
            ('Float32',  'int64_t Float32(...);'),            # FIXME: should be float Float32(void *value)
            ('Float64',  'int64_t Float64(...);'),            # FIXME: should be double Float64(void *value)
            ('Error',    'int64_t Error(...);'),              # FIXME: should be Error *Error(void *value)
        ]
        def _guarded_ctor(name, decl):
            guard = f'_MOJO_CTOR_{name.upper()}'
            # Also suppress this ctor-function stub if the same name was emitted
            # as a struct typedef: `typedef … Error;` (a type) and `int64_t
            # Error(...)` (a function) collide as "Error redeclared as a
            # different kind of symbol". The struct-typedef paths #define
            # _MOJO_STUB_<NAME> right after the typedef and are emitted earlier
            # in the file, so this #ifndef sees it. Hit by `Error` (Mojo's
            # builtin error type) when a module in the closure registers it as
            # an opaque struct — e.g. any enum-importing file (types.py).
            stub_guard = _stub_guard_name(name)
            return (f'#ifndef {stub_guard}\n#ifndef {guard}\n#define {guard}\n'
                    + (decl + '\n#endif\n#endif'))
        _ctor_lines = [_guarded_ctor(name, decl) for name, decl in _builtin_ctors if name not in _skip_ctors]
        if _ctor_lines:
            parts.append('/* Mojo built-in type constructors */')
            parts.extend(_ctor_lines)
            parts.append('')
        # Also skip utility stubs for locally-defined functions (they'd conflict).
        # Exclude _C_RESERVED_FUNCS names: those Mojo functions get renamed to mojo_X,
        # so the C function (e.g. getuid) still needs its stub declaration.
        _local_funcs = {s.name for s in stmts
                        if isinstance(s, FunctionDef) and s.name not in _C_RESERVED_FUNCS}
        # Also include struct method names (e.g. Span_unsafe_ptr from fn Span.unsafe_ptr)
        for _s in stmts:
            if isinstance(_s, StructDef):
                for _m in (_s.methods or []):
                    if isinstance(_m, FunctionDef):
                        _local_funcs.add(f'{_s.name}_{_m.name}')
        # Renamed forms of local/imported functions — Phase 2b emits proper forward
        # declarations with real signatures; the variadic preamble stub would conflict.
        _local_funcs_renamed = {_safe_name(s.name) for s in stmts if isinstance(s, FunctionDef)}
        _imported_names_renamed = {_safe_name(n) for n in _imported_names}
        # Also skip stubs for functions defined in any sub-module (do_imports=True monolithic build).
        # Exclude _C_RESERVED_FUNCS: their Mojo wrappers get renamed (e.g. getuid → mojo_getuid)
        # so the underlying C function still needs its util stub.
        _all_defined_funcs = (set(self.func_return_types.keys()) | self._global_inline_defs) - _C_RESERVED_FUNCS
        _skip_util = (_local_structs | _imported_names | _local_funcs | _all_defined_funcs
                      | _local_funcs_renamed | _imported_names_renamed)
        _util_pairs = [
            ('iter',    'int64_t iter(...);'),         # FIXME: should be MojoList *iter(MojoList *obj) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
            ('next',    'int64_t next(...);'),           # FIXME: should be MojoList *next(MojoList *it) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
            ('swap',    'void swap(...);'),    # FIXME: should be void swap(int64_t *a, int64_t *b) [takes pointer arguments boxed as int64_t]; variadic so both int and pointer call sites typecheck
            ('op',      'int64_t op(...);'),
            ('U128',    'int64_t U128(...);'),
            # Pointer: guarded so it's suppressed if the struct typedef was already emitted
            ('Pointer', '#ifndef _MOJO_POINTER_STRUCT_DEF\nint64_t Pointer(...);\n#endif'),
            # Commonly used Mojo stdlib types/constructors — forward-declared as variadic
            # so they compile without full type resolution (do_imports=False mode).
            ('UnsafePointer',    'int64_t UnsafePointer(...);'),
            ('StringSlice',      'int64_t StringSlice(...);'),
            ('StaticString',     'int64_t StaticString(...);'),
            ('debug_assert',     'void debug_assert(...);'),
            ('__get_mvalue_as_litref', 'int64_t __get_mvalue_as_litref(...);'),
            ('__get_litref_as_mvalue', 'int64_t __get_litref_as_mvalue(...);'),
            ('MojoList_unsafe_ptr',    'int64_t MojoList_unsafe_ptr(...);'),
            ('MojoList_unsafe_get',    'int64_t MojoList_unsafe_get(...);'),
            ('Span_unsafe_ptr',        'int64_t Span_unsafe_ptr(...);'),
            ('Optional',               'int64_t Optional(...);'),
            ('int64_t_init_pointee_move', 'void int64_t_init_pointee_move(...);'),
            ('conforms_to',            '_Bool conforms_to(int64_t a, int64_t b);'),
            ('Codepoint',              'int64_t Codepoint(...);'),
            ('stat_result',            'int64_t stat_result(...);'),
            ('UInt128',                'int64_t UInt128(...);'),
            ('SIMDSize',               'int64_t SIMDSize(...);'),
            ('List',                   'int64_t List(...);'),
            ('MojoDict__reserved',     'int64_t MojoDict__reserved(...);'),
            ('ord',                    'int64_t ord(...);'),         # FIXME: should be int64_t ord(char *c) [takes char * boxed as int64_t]; variadic so both int and pointer call sites typecheck
            ('chr',                    'int64_t chr(...);'),        # FIXME: should be char *chr(int64_t i) [returns char * boxed as int64_t]; variadic so both int and pointer call sites typecheck
            ('sort',                   'void sort(...);'),       # FIXME: should be void sort(MojoList *list) [takes MojoList * boxed as int64_t]; variadic so both int and pointer call sites typecheck
            ('Span_byte_length',       'int64_t Span_byte_length(...);'),
            ('_stat_macos',            'int64_t _stat_macos(...);'),
            ('_getpw_macos',           'int64_t _getpw_macos(...);'),
            ('Passwd',                 'int64_t Passwd(...);'),
            ('create_test_device_context', 'int64_t create_test_device_context(...);'),
            ('check_write_to',         'void check_write_to(...);'),
            ('_unsupported_mma_op',    'void _unsupported_mma_op(...);'),
            ('IntType',                'int64_t IntType(...);'),
            ('Byte',                   'int64_t Byte(...);'),
            ('hash',                   'int64_t hash(...);'),
            ('MojoList___contains__',  'int64_t MojoList___contains__(...);'),
            ('MojoList_get_loaded_kgen_pack', 'int64_t MojoList_get_loaded_kgen_pack(...);'),
            ('_stat_linux_x86',        'int64_t _stat_linux_x86(...);'),
            ('func',                   'int64_t func(...);'),
            ('mojo_getenv',            'int64_t mojo_getenv(...);'),
            ('mojo_atol',              'int64_t mojo_atol(...);'),
            ('mojo_frexp',             'int64_t mojo_frexp(...);'),
            # Mojo's abort() is overloaded (0-arg trap, or message + optional
            # SourceLocation) — incompatible with libc's `void abort(void)`;
            # variadic so every call shape typechecks (see _FORCE_RENAME_RESERVED).
            ('mojo_abort',             'void mojo_abort(...);'),
            ('Span_as_bytes',          'int64_t Span_as_bytes(...);'),
            ('Span_get_immutable',     'int64_t Span_get_immutable(...);'),
            ('_Bool___mlir_i1__',      'int64_t _Bool___mlir_i1__(...);'),
            ('sync_parallelize',       'void sync_parallelize(...);'),
            ('main_func',              'void main_func(void);'),
            # Mojo SIMD/Scalar type constructors and utilities
            ('scalar',                 'int64_t scalar(...);'),
            ('Scalar',                 'int64_t Scalar(...);'),
            ('type_of',                'int64_t type_of(...);'),
            ('align_up',               'int64_t align_up(...);'),
            ('align_down',             'int64_t align_down(...);'),
            ('clamp',                  'int64_t clamp(...);'),
            # NOTE: `isdir` intentionally has NO entry here (removed — see
            # bugs/COMPILE_FAIL_Modules_getpath.md and the paired removal of
            # `'isdir'` from `_KNOWN_SIGS` below, in `_lower_named_call`'s
            # docstring-adjacent comment, for the full root-cause writeup).
            # Short version: unlike every other name in this table (real C
            # stdlib/POSIX functions, or genuine Mojo runtime helpers that
            # always have a backing definition somewhere in the link), a bare
            # `isdir` reference with no local def/import (e.g. CPython's own
            # Modules/getpath.py, where the C embedder injects `isdir` into
            # the exec() namespace at runtime — a mechanism this compiler
            # doesn't have) has NO possible backing definition at all, ever.
            # This table is emitted UNCONDITIONALLY into every compiled
            # file's preamble regardless of whether the name is even
            # referenced (see `_skip_util`/`_util_stubs` above) — fine for a
            # one-line prototype, but wrong for anything needing a real weak
            # body (bloats every single compiled unit, confirmed via
            # test_module_cache.py's "reflect: client object is tiny" size
            # assertion regressing from a first attempt that put a weak
            # `{ mojo_print(...); return 0; }` body directly in this table).
            # The right mechanism for "only synthesize a stub in files that
            # actually call this unresolved name" already exists and is
            # exercised by every sibling CPython-injected name (`abspath`/
            # `isfile`/`joinpath`/`hassuffix`/`warn`/...): `_lower_named_
            # call`'s `_is_unknown`/`self._elaborated_externs` fallback,
            # which lazily emits a `__attribute__((weak))` stub with that
            # same safe body, ONE PER FILE THAT ACTUALLY CALLS IT. `isdir`
            # just needs to be routed through that path instead of this one.
            ('serialize',              'void serialize(...);'),
            ('slice',                  'int64_t slice(...);'),
            ('_getpw_linux',           'int64_t _getpw_linux(...);'),
            ('_lstat_macos',           'int64_t _lstat_macos(...);'),
            # POSIX functions not declared by our minimal header set (<unistd.h> stubs)
            ('getuid',   'unsigned int getuid (void);'),
            ('getgid',   'unsigned int getgid (void);'),
            ('getpid',   'int getpid (void);'),
            ('getppid',  'int getppid (void);'),
            ('isatty',   'int isatty (int fd);'),
            ('sysconf',  'long sysconf (int name);'),
            ('_log2_ceil',             'int64_t _log2_ceil(...);'),
            ('int64_t_unsafe_value',   'int64_t int64_t_unsafe_value(...);'),
            ('MojoDict_unsafe_ptr',    'int64_t MojoDict_unsafe_ptr(...);'),
            ('_Empty_copy',            'void _Empty_copy(...);'),
            ('_get_global_or_null',    'int64_t _get_global_or_null(...);'),
        ]
        def _guarded_stub(name, decl):
            guard = _stub_guard_name(name)
            return f'#ifndef {guard}\n#define {guard}\n' + (decl + '\n#endif')
        _util_stubs = [_guarded_stub(name, decl) for name, decl in _util_pairs if name not in _skip_util]
        parts.extend([
            '/* Mojo iterator and utility functions */',
            *_util_stubs,
            '',
            '/* Struct ___new stubs (for Self(...) call sites) */',
            *[f'int64_t {s}___new(...);' for s in sorted(self._self_ctor_stubs)],
            '',
            '/* Renamed C-reserved builtins called without import (e.g. abs→mojo_abs) */',
            *[f'{rt} {fn}(...);'
              for fn, rt in sorted(self._renamed_builtin_calls.items())
              if fn not in _skip_util and fn not in _imported_names
              and fn not in _local_funcs and fn not in _local_funcs_renamed
              and fn not in _imported_names_renamed],
            '',
            '',
            'char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename);',
            'char *compile_to_gimple(char *mojo_src, int do_imports, char *filename);',
            'int64_t mojo_open_file(char *path);',
            # Suppress mojo_open decl when this module defines or imports 'open'
            # (renamed to mojo_open via _C_RESERVED_FUNCS, causing a conflict)
            *([] if ('open' in self.func_return_types or 'open' in self.imported_symbols) else ['void *mojo_open(char *filename, char *mode);']),
            'int64_t int_write (int64_t, char *);',
            'int64_t int_parse_module (int);',
            # Genuinely-unimplemented dispatch helpers (ctypes Structure.in_dll
            # interop; a mis-dispatched .items()). Define as abort() stubs so the
            # program links, but any real call detonates loudly rather than
            # silently returning garbage. Include-guarded: the preamble is emitted
            # once per module, but these must be defined exactly once.
            # `static` so separately-compiled units (module cache: c1.o + l1.o)
            # don't collide at link; the include guard prevents same-file dup
            # (the preamble repeats per module).
            '#ifndef _MOJO_UNIMPL_STUBS',
            '#define _MOJO_UNIMPL_STUBS',
            'static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }',
            'static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }',
            'static int64_t id (int64_t x) { return x; }',
            '#endif',
        ])

        # NOTE: extern prototypes for external_call[...] targets (e.g. write/read/
        # isatty) are emitted AFTER the struct typedef section below — an
        # external_call's argument can be a real user struct pointer (e.g.
        # `external_call["...", Ret](a_device_stream_var, ...)` lowers its arg to
        # `DeviceStream *`, not a boxed int64_t), so the prototype must not precede
        # that struct's typedef.

        # Link mode: extern decls for imported symbols (bodies live in the linked
        # artifact / stdlib dylib, per ABI.md). Collected by the Phase-0 pre-pass.
        for _decl in self._link_import_decl_list:
            parts.append(_decl)
        # NOTE: extern decls for elaborated instantiations (incl. struct methods,
        # which reference monomorphized struct types) are emitted AFTER the struct
        # typedef section below, so the types they reference are already defined.

        # For all modules, declare extern references to known module globals structs
        # Each module can reference globals from other modules via these externs
        # Determine which module is being compiled from either module_name or filename
        our_mod = self.module_name or "root"
        if not self.module_name and self._current_filename:
            # Infer module name from filename (e.g., "myinterpreter.py" → "myinterpreter")
            # (`os` is already imported at module level — a redundant local
            # `import os` here used to shadow it for gen_module's ENTIRE body,
            # since Python scopes a name as local to the whole function the
            # moment it's assigned anywhere in that function, not just from
            # the assignment point onward — any earlier `os.*` use in this
            # same function raised UnboundLocalError.)
            our_mod = os.path.splitext(os.path.basename(self._current_filename))[0]

        all_modules_to_declare = set()

        # If this is not the root module, always declare root's globals (it's special)
        if our_mod != "root":
            all_modules_to_declare.add("root")

        # Add all modules we know about (including successfully compiled ones)
        all_modules_to_declare.update(self._module_globals.keys())

        # Also add all directly imported modules from stmts — even modules that
        # fail to compile need an extern incomplete-struct forward declaration
        # so references like `_build_stdlib_dylib_globals.x` don't get "undeclared".
        # Use the module name (not alias) since generated C accesses _module_globals not _alias_globals.
        all_scan_for_mods = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        for _ms in all_scan_for_mods:
            if isinstance(_ms, ImportStmt):
                # module name, not alias (globals struct uses module name) — every
                # comma-separated target (`import a, b, c`), not just the first.
                for _mn, _ in _import_targets(_ms):
                    if _mn and not _mn.startswith('_'):
                        all_modules_to_declare.add(_mn)
            elif isinstance(_ms, FromImportStmt):
                _mn = _ms.module
                if _mn and not _mn.startswith('_') and '.' not in _mn:
                    all_modules_to_declare.add(_mn)

        # Emit initial #line directive at the start if we have a filename
        # This sets the context for all subsequent code
        if self._current_filename:
            parts.append(f'#line 1 "{self._current_filename}"')

        # Emit struct typedefs early, before any functions that use them
        # This includes structs from struct_field_types (like Interpreter, Scope, etc.)
        # Emit in dependency order: structs with no struct dependencies first
        # Self-referential dependencies (e.g. Scope->Scope*) are allowed in C
        if self.emit_struct_defs and hasattr(self, 'struct_field_types') and self.struct_field_types:
            parts.append('')
            emitted = set()
            max_iterations = len(self.struct_field_types) + 1
            iteration = 0
            while emitted != set(self.struct_field_types.keys()) and iteration < max_iterations:
                iteration += 1
                for struct_name in sorted(self.struct_field_types.keys()):
                    if struct_name in emitted:
                        continue
                    fields = self.struct_field_types[struct_name]
                    # Check if all dependencies are emitted (excluding self-references)
                    dependencies_met = True
                    for field_type in fields.values():
                        # Extract struct name from type (e.g., "Scope *" → "Scope")
                        # `'' + field_type` recovers the char* (dict value boxed
                        # as int64_t) so `.rstrip(' *')`/comparison see real
                        # text — without it the self-hosted dependency check saw
                        # garbage and emitted structs out of dependency order.
                        # Also strip a fixed-size-array marker suffix ("Block[4096]"
                        # -> "Block", see _FIXED_ARRAY_ANN_RE) so a struct embedding
                        # a fixed-size array of another local struct still gets
                        # correctly ordered AFTER that element struct's own typedef.
                        base_type = re.sub(r'\[\d+\]$', '', ('' + field_type).rstrip(' *'))
                        # Allow self-references: Scope can have a field of type Scope*
                        if base_type == struct_name:
                            continue  # Self-reference is OK
                        if base_type in self.struct_field_types and base_type not in emitted:
                            dependencies_met = False
                            break
                    if not dependencies_met:
                        continue
                    # All dependencies met (or are self-references), emit this struct
                    _td_start = len(parts)
                    if struct_name == 'Pointer':
                        parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                        _td_start = len(parts)
                    parts.append(f"typedef struct {struct_name} {{")
                    # Runtime type tag, always first — see the other struct-typedef
                    # emission below (Section 2 for AST-sourced StructDefs) and
                    # mojo_read_type_tag in runtime/mojo_runtime.c. This is a
                    # SEPARATE typedef-emission path (topologically sorted from
                    # struct_field_types rather than walking StructDef nodes
                    # directly) that needs the same leading field, or a struct
                    # emitted via THIS path never gets tagged and isinstance()
                    # against it always reads a stale/garbage first field.
                    parts.append(f"  int64_t __mojo_type_id;")
                    if fields:
                        # Iterate in DICT INSERTION order, not sorted() —
                        # every population site for struct_field_types[name]
                        # (the main s.fields walk after _merge_struct_
                        # inheritance around gen_module's Phase 1, the
                        # reflected-dylib layout-descriptor parse in
                        # _register_reflected_struct, elaborate_generic_
                        # struct's field list, and _materialize_imported_
                        # struct's own sdef.fields walk) inserts fields in
                        # real declaration/merge order — base fields first,
                        # own fields after — specifically so a subclass
                        # pointer cast to its base type (`(Base *)self`, the
                        # unbound-instance-method call shape) sees identical
                        # field offsets to a real Base struct, C-struct-
                        # inheritance style (no vtable in this codegen).
                        # sorted() here silently alphabetized every such
                        # struct's fields instead, corrupting that layout
                        # compatibility for any subclass that adds its own
                        # field(s) on top of an inherited base (confirmed via
                        # bugs/hard/CODEGEN_struct_typedef_alphabetical_field
                        # _order_breaks_inheritance_layout.md's repro — a
                        # base method invoked through the cast wrote into the
                        # wrong field entirely, a silent data corruption, not
                        # a crash). Section 2 below (the AST-`StructDef.
                        # fields`-driven typedef path) already walks fields
                        # in this same real order; this makes Section 1
                        # agree instead of maintaining a second, independently
                        # -wrong ordering rule.
                        for field_name, field_type in fields.items():
                            # field_type arrives boxed as int64_t (tuple-unpacked
                            # from dict.items()); an f-string interpolation of it
                            # would lower to mojo_str_from_int (its pointer value
                            # as decimal text) in the self-hosted binary. `'' +
                            # field_type` (a fresh local, so its type is the
                            # concat's char* — reassigning the int64_t-typed loop
                            # var itself would keep the old declared type and
                            # still str_from_int it) recovers the char*, and
                            # `ft` is what every f-string below interpolates.
                            ft = '' + field_type
                            # For self-references in typedef, use 'struct Name *' syntax
                            if ft == f"{struct_name} *":
                                # Change Scope * to struct Scope * for self-references
                                ft = f"struct {struct_name} *"
                            safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                            # Fixed-size-array field marker ("ElemCtype[N]",
                            # see _FIXED_ARRAY_ANN_RE): C array-declarator
                            # syntax puts the size after the FIELD NAME, not
                            # after the type ("ElemCtype name[N];"), unlike
                            # every other field shape here.
                            _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
                            if _arr_dm:
                                parts.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
                            else:
                                parts.append(f"  {ft} {safe_fn};")
                    else:
                        # Empty struct - add a dummy field for valid C
                        parts.append(f"  int _dummy;")
                    parts.append(f"}} {struct_name};")
                    # Milestone C step 3: verbatim copy of this exact typedef
                    # text (nothing else, so an identical view compiles under
                    # BOTH gcc -fgimple and g++) — reused, not re-derived, by
                    # the .cpp preamble for any struct a compiled generator
                    # METHOD needs to see (self.<field> access / the `self`
                    # parameter's own pointer type). See the generated_cpp
                    # assembly further below in gen_module.
                    self._struct_typedef_texts[struct_name] = '\n'.join(parts[_td_start:])
                    parts.append(f"#define {_stub_guard_name(struct_name)}")  # suppress any later variadic stub
                    emitted.add(struct_name)
                    self._emitted_structs.add(struct_name)  # track for dedup in Section 2
            parts.append('')

        # `type(node).__name__` runtime resolver: maps a struct's leading
        # __mojo_type_id tag (the _struct_type_id hash) back to its name. Used
        # by every compiled AST walker's `type(x).__name__` dispatch — the
        # self-hosted gimple_codegen's gen_stmt/_EXPR_DISPATCH and the
        # interpreter's execute_{TypeName}. See the __name__ member-expr
        # handling in _lower_MemberExpr (the "<type>" stub made every compiled
        # statement emit `/* TODO: <type> */`).
        global _emitted_type_name_emitted
        if self._needs_type_name_table and not _emitted_type_name_emitted:
            _emitted_type_name_emitted = True
            parts.append("static char * _mojo_type_name (int64_t tag)")
            parts.append("{")
            # struct_field_types alone is NOT enough: the compiled binary's
            # gen_stmt/_EXPR_DISPATCH dispatch on `type(node).__name__` for
            # EVERY AST node, and most node types (ExprStmt, AssignStmt,
            # FunctionDef, IntLiteral, ...) are NOT in struct_field_types for
            # an ordinary compile — without them _mojo_type_name fell back to
            # "<type>" and every compiled statement/expression silently emitted
            # `/* TODO: <type> */`. Include the dispatch-table keys so every
            # node type resolves to its real name.
            _type_name_set = set(self.struct_field_types)
            for _dspk in _STMT_DISPATCH.keys():
                _type_name_set.add('' + _dspk)
            for _dspk in _EXPR_DISPATCH.keys():
                _type_name_set.add('' + _dspk)
            for _tn in sorted(_type_name_set):
                # `'' + _tn` recovers the char* (dict key boxed as int64_t); a
                # bare interpolation of `_tn`/`_struct_type_id(_tn)` would
                # str_from_int the pointer instead of the name text.
                _tn_s = '' + _tn
                parts.append(f"  if (tag == {_struct_type_id(_tn_s)}) return \"{_tn_s}\";")
            parts.append("  return \"<type>\";")
            parts.append("}")
            parts.append('')

        for mod_name in sorted(all_modules_to_declare):
            # Skip declaring our own module as extern (sorted: deterministic .ci
            # output, required for the bootstrap stage1==stage2==stage3 check)
            # `mod_s = '' + mod_name` recovers the char*: the loop var arrives
            # boxed as int64_t (a MojoSet element), and an f-string/str() on it
            # would stringify its pointer VALUE instead of the name text
            # (`str()` on an int64_t lowers to mojo_str_from_int — a numeric
            # string that _c_field_name then strips to empty, producing the
            # bogus `struct __toplev`).
            mod_s = '' + mod_name
            if mod_s == our_mod:
                continue
            # Ensure module names are valid C identifiers (replace dots → underscores)
            mod_str = mod_s if mod_s else "root"
            safe_mod = _c_field_name(mod_str) if mod_str else "root"
            struct_name = f"_{safe_mod}_toplev"
            global_var = f"_{safe_mod}_globals"
            # If this OTHER module's real globals field list is already known
            # (see bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
            # defined.md) reconstruct a REAL, field-matching struct typedef
            # here instead of an incomplete stub, mirroring the identical
            # reconstruction the C++ generator side already does from the
            # same shared dict (see the `_cpp_module_global_refs` typedef-
            # copy block further down in this method). A plain incomplete
            # forward declaration only supports pointer-only uses of the
            # extern instance; any real member access (`genericpath.
            # something`) requires the type to be COMPLETE at the point of
            # access, which C disallows for an incomplete type ("invalid
            # use of undefined type"). Field order is deterministic (the
            # populating scan always inserts in sorted name order — see the
            # `for gname in sorted(_declared_globals)` loop below) so this
            # reconstruction exactly matches the layout that module's own
            # compile would emit for itself.
            #
            # This whole `for mod_name in ...` loop is deliberately
            # positioned AFTER the struct_field_types typedef block above
            # (moved there 2026-08-07, "mechanism 2" fix — originally sat
            # right after `all_modules_to_declare` is computed, well BEFORE
            # struct_field_types): a known field's C type can itself be a
            # pointer to a Mojo struct/class type (`_Unknown *`, `_TupleType
            # *`, ...) that struct_field_types defines — reconstructing a
            # full struct HERE, this early, before that typedef exists,
            # produced a real, confirmed regression (`gcc -fsyntax-only`
            # error count on Lib/subprocess.py went 788 -> 1123, "unknown
            # type name '_Unknown'" etc., even though the TARGETED "invalid
            # use of undefined type" error count did drop 26 -> 0) the first
            # time this loop was widened to run unconditionally. Moving the
            # whole loop to after struct_field_types (same place `external_
            # call[...]` prototypes and elaborated-instantiation externs
            # already live, for the identical reason — see their own NOTE
            # comments near the top of this preamble) fixed it — see the doc
            # (bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
            # defined.md) for the exact before/after error-count breakdown.
            #
            # 2026-08-07 update (see the doc's "mechanism 2" section): the
            # `mod_str not in self._module_stmts` restriction above (i.e.
            # "only reconstruct when the module will NOT also get a real
            # definition inlined later") turned out to be based on a false
            # assumption — a module can be fully, successfully compiled
            # (`self._module_stmts` populated) and STILL never have its own
            # text actually embedded anywhere in THIS file's final output,
            # because the TEXT propagation path is per-PARENT: a nested
            # module's compiled C text only reaches the root's output by
            # being threaded, unmodified, through every ancestor's own
            # `imported_code` list — and if any ONE ancestor in that chain
            # itself ultimately fails (e.g. `os.py` failing on an unrelated
            # bug well after successfully, recursively compiling `posixpath`
            # -> `genericpath` as part of its own Phase 0), that ancestor's
            # ENTIRE returned code (including the successfully-compiled
            # descendants nested within it) is discarded by the `if code:`
            # guard around `imported_code.append(code)` — while the
            # descendants' own entries in the SHARED `self._module_globals`/
            # `self._module_stmts` dicts remain, since those commit
            # independently of whatever their parent does afterward.
            # Confirmed via direct .ci inspection on `Lib/subprocess.py`:
            # `_genericpath_toplev`'s real definition (`struct
            # _genericpath_toplev {`) appears NOWHERE in the ~14MB output
            # (0 matches) despite `self._module_globals['genericpath']`
            # being fully populated — because `os` (the only path by which
            # subprocess reaches genericpath) fails outright on an unrelated
            # "'relpath' is ambiguous" bug, so `Imported module: os` never
            # appears in the output at all.
            #
            # There is no way to know, AT THIS POINT, whether the eventual
            # real definition will actually make it into the final text —
            # so this now ALWAYS reconstructs a full, field-matching struct
            # whenever the field list is known, regardless of
            # `self._module_stmts`, guarded by an `#ifndef`/`#define`
            # preprocessor pair (using a name derived purely from the
            # module's own C-safe name, so every emission site for the same
            # module agrees on it) rather than by Python-side "has this
            # already been emitted" bookkeeping — cheap, and correct by
            # construction regardless of how many places (this loop, at
            # however many ancestor levels reference this module; the
            # module's own official per-module emission below) attempt to
            # define the SAME struct, and regardless of which one ends up
            # textually first. The module's own official emission (below,
            # `if self._module_globals.get(current_mod_name):`) wraps its
            # typedef in the identical guard for the same reason. Whichever
            # occurrence is textually first in the final file wins; every
            # later one is a preprocessor no-op — never a GCC "redefinition
            # of struct or union" error, unlike the old Python-side
            # `mod_str not in self._module_stmts` gate this replaces.
            #
            # Falls back to the old incomplete stub only when the field
            # list isn't known at all (e.g. do_imports=False's isolated
            # per-file compiles, where no other module is ever recursively
            # compiled, or a module this level references that was never
            # reached by ANY globals scan anywhere in the tree) — same
            # behavior as before this fix, not a regression for that mode.
            _known_fields = self._module_globals.get(mod_str)
            if _known_fields:
                _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_mod}'
                parts.append(f'#ifndef {_toplev_guard}')
                parts.append(f'#define {_toplev_guard}')
                parts.append(f'typedef struct {struct_name} {{')
                for _kf_name, _kf_ctype, _ in _known_fields:
                    parts.append(f'  {_kf_ctype} {_c_field_name(_kf_name)};')
                parts.append(f'}} {struct_name};')
                parts.append('#endif')
                parts.append(f'extern struct {struct_name} {global_var};')
            else:
                # Forward-declare the struct type with gcc attribute to allow incomplete use
                # AND the extern global instance
                parts.append(f'struct {struct_name} __attribute__((incomplete));  /* extern module globals struct */')
                parts.append(f'extern struct {struct_name} {global_var};')

        # extern decls for elaborated instantiations (generic functions + struct
        # methods). Emitted here, after the struct typedefs above, so struct-method
        # declarations like `Box_Int64_unbox (Box_Int64 *)` see the type.
        for _decl in self._elaborated_externs:
            parts.append(_decl)

        # extern prototypes for external_call[...] targets (e.g. write/read/isatty).
        # Skip libc names already declared by our standard includes to avoid clashes.
        for _ecname in sorted(self._external_protos):
            if _ecname in self._LIBC_DECLARED and _ecname not in self._NEEDS_SELF_EXTERN:
                continue
            _eret, _eargs = self._external_protos[_ecname]
            _argstr = ', '.join(_eargs) if _eargs else 'void'
            parts.append(f'extern {_eret} {_ecname} ({_argstr});')


        # Include compiled imported modules.
        # Record where imported code begins: imported modules may reference THIS
        # module's globals struct (e.g. myinterpreter reading _root_globals.mojo_compiler),
        # so the complete struct typedef must be inserted *before* this point rather than
        # after, otherwise those functions see an incomplete type. See the globals struct
        # emission below, which inserts at this index.
        _module_globals_insert_idx = len(parts)
        if imported_code:
            parts.append('')
            parts.extend(imported_code)

        # Pointer-at helper functions (plain C — pointer arithmetic forbidden in __GIMPLE)
        new_helpers = self._ptr_helpers_needed - self._emitted_ptr_helpers
        for et in sorted(new_helpers):
            cn = _c_id(et)
            parts.append(
                f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
            )
            self._emitted_ptr_helpers.add(et)
        if new_helpers:
            parts.append('')

        # Module-level globals (imported modules, dicts, lists, sets, values at module scope)
        global_decls = []  # kept for compatibility, but won't be emitted
        # Initialize module globals tracking for this module
        current_mod_name = self.module_name or "root"
        if current_mod_name not in self._module_globals:
            self._module_globals[current_mod_name] = []
            self._module_global_inits[current_mod_name] = {}
        # Dispatch table globals already forward-declared near top of file
        # Also declare imported dispatch tables as MojoDict/MojoSet globals
        _dispatch_dict_names = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                                '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
        _dispatch_set_names = {'_CMP_OPS'}
        _dispatch_names = _dispatch_dict_names | _dispatch_set_names
        _declared_globals = set()
        # Scan ONLY this module's own top-level `stmts` here — NOT
        # `imported_stmts`. `imported_stmts` is the whole-transitive-tree
        # visibility list (see bugs/hard/PERF_nested_module_compile_walk_
        # ast_quadratic_rescan.md's "Why the reconciliation loop exists"),
        # deliberately a superset of every module compiled anywhere in the
        # program so far — appropriate for struct/function *visibility*
        # scans (all_struct_defs, all_functions, ...) but WRONG here: this
        # scan's job is registering the CURRENT module's (`current_mod_name`)
        # own globals-struct fields (`self._module_globals[current_mod_name]`
        # below). Every module already independently registers its OWN
        # globals under its OWN name via its own recursive `gen_module` call
        # (each transitively-imported module gets its own `temp_gen` with
        # `module_name=<that module>`, which runs this exact code with
        # `current_mod_name` set correctly) — so re-scanning `imported_stmts`
        # here was pure double-registration under the WRONG module name.
        # Confirmed real bug (found via Lib/weakref.py's transitive-closure
        # build, which pulls in a much larger module graph than earlier
        # per-file tests): `_functools_toplev` ended up with fields like
        # `BINBYTES`/`BOM32_BE` (pickle.py/codecs.py module-level globals)
        # and `AsyncGenerator`/`Attribute` (ast.py/typing.py names) merged
        # into functools.py's OWN globals struct, because `all_scan`/
        # `all_global_scan` included every foreign top-level statement
        # reachable via `imported_stmts` and attributed ANY matching
        # AssignStmt/ImportStmt/VarDecl to `current_mod_name` regardless of
        # which module it actually came from — a massive, real field-name
        # cross-contamination across unrelated modules that (at weakref.py's
        # transitive-closure scale) produced genuine GCC "redefinition"/
        # type-mismatch errors cascading through the rest of the compile.
        # See bugs/CODEGEN_generator_function_Lib_weakref.md.
        all_scan = stmts
        for stmt in all_scan:
            if isinstance(stmt, FromImportStmt):
                for alias in stmt.names:
                    orig_name = alias[0]
                    local_name = alias[1] if len(alias) > 1 and alias[1] else orig_name
                    for check_name in (orig_name, local_name):
                        if check_name in _dispatch_dict_names and check_name not in _declared_globals:
                            global_decls.append(f"MojoDict * {check_name};")
                            _declared_globals.add(check_name)
                            self._global_c_decl_types[check_name] = 'MojoDict *'
                            self._global_var_types[check_name] = 'MojoDict *'
                        elif check_name in _dispatch_set_names and check_name not in _declared_globals:
                            global_decls.append(f"MojoSet * {check_name};")
                            _declared_globals.add(check_name)
                            self._global_c_decl_types[check_name] = 'MojoSet *'
                            self._global_var_types[check_name] = 'MojoSet *'
            elif isinstance(stmt, ImportStmt):
                for _tm, _ta in _import_targets(stmt):
                    local_name = _ta if _ta else _tm
                    if local_name not in _declared_globals:
                        global_decls.append(f"int64_t {local_name};")
                        _declared_globals.add(local_name)
                        self._global_var_types[local_name] = 'int64_t'
                        if local_name not in self._global_to_module:
                            self._global_to_module[local_name] = current_mod_name
        # Scan current module + imported stmts for module-level variable declarations.
        # Also recurse into TryStmt/IfStmt/ForStmt bodies at module level since Python
        # allows module-level assignments inside try/except (e.g. mojo_compiler = None).
        def _collect_global_stmts(stmt_list):
            result = []
            for _gs in stmt_list:
                result.append(_gs)
                if isinstance(_gs, TryStmt):
                    result.extend(_collect_global_stmts(_gs.body or []))
                    for _h in (_gs.handlers or []):
                        result.extend(_collect_global_stmts(getattr(_h, 'body', []) or []))
                    result.extend(_collect_global_stmts(_gs.else_body or [] if isinstance(_gs.else_body, list) else []))
                    result.extend(_collect_global_stmts(_gs.finally_body or [] if isinstance(_gs.finally_body, list) else []))
                elif isinstance(_gs, IfStmt):
                    result.extend(_collect_global_stmts(_gs.then_body or []))
                    result.extend(_collect_global_stmts(_gs.else_body or []))
            return result

        # Same reasoning as `all_scan` just above: only this module's own
        # top-level `stmts`, not the whole-tree `imported_stmts` superset.
        all_global_scan = stmts

        def _gscan_declare_global(gname, value):
            """Infer a global's C type from its assigned RHS `value` and
            append the literal struct-field declaration text to
            `global_decls` (this is the pass that actually determines
            which fields exist on the module's `_<mod>_toplev` struct —
            see `_module_globals` below, built from `_declared_globals`).
            Factored out of the AssignStmt branch so MultiAssignStmt
            (`a = b = expr`) can share the identical logic for every one
            of its targets — mirrors the identical refactor done for the
            separate Phase 1.7 pre-scan above (`_phase17_infer_global_type`)
            for the exact same reason: a chained assignment was invisible
            to THIS scan too, so a global only ever assigned via `a = b =
            expr` (e.g. `Lib/codecs.py`'s `BOM_LE = BOM_UTF16_LE = ...`)
            never got a struct field here at all, even after Phase 1.7
            (elsewhere) learned about it — the two scans must agree on
            which names are real struct fields, or code that resolves a
            name via Phase 1.7's `_global_var_types`/`_global_to_module`
            emits `_<mod>_toplev.NAME` for a field this scan never
            declared, i.e. 'struct _X_toplev has no member named NAME'."""
            if isinstance(value, DictExpr):
                if gname in _dispatch_names:
                    global_decls.append(f"MojoDict * {gname};")
                    self._global_c_decl_types[gname] = 'MojoDict *'
                else:
                    global_decls.append(f"int64_t {gname};  /* MojoDict * */")
                    self._global_c_decl_types[gname] = 'int64_t'
                self._global_var_types[gname] = 'MojoDict *'
            elif isinstance(value, (ListExpr, TupleExpr)):
                if gname in _dispatch_names:
                    global_decls.append(f"MojoList * {gname};")
                    self._global_c_decl_types[gname] = 'MojoList *'
                else:
                    global_decls.append(f"int64_t {gname};  /* MojoList * */")
                    self._global_c_decl_types[gname] = 'int64_t'
                self._global_var_types[gname] = 'MojoList *'
            elif isinstance(value, SetExpr):
                if gname in _dispatch_names:
                    global_decls.append(f"MojoSet * {gname};")
                    self._global_c_decl_types[gname] = 'MojoSet *'
                else:
                    global_decls.append(f"int64_t {gname};  /* MojoSet * */")
                    self._global_c_decl_types[gname] = 'int64_t'
                self._global_var_types[gname] = 'MojoSet *'
            elif isinstance(value, (IntLiteral, BoolLiteral)):
                global_decls.append(f"int {gname};")
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            elif isinstance(value, StringLiteral):
                global_decls.append(f"char * {gname};")
                self._global_var_types[gname] = 'char *'
                self._global_c_decl_types[gname] = 'char *'
            elif isinstance(value, CallExpr):
                if isinstance(value.func, IdentExpr) and value.func.name in self.struct_field_types:
                    struct_name = value.func.name
                    global_decls.append(f"{struct_name} * {gname};")
                    self._global_var_types[gname] = f"{struct_name} *"
                    self._global_c_decl_types[gname] = f"{struct_name} *"
                elif isinstance(value.func, IdentExpr):
                    ret = self.func_return_types.get(value.func.name, '')
                    if ret.endswith(' *'):
                        global_decls.append(f"{ret} {gname};")
                        self._global_var_types[gname] = ret
                        self._global_c_decl_types[gname] = ret
                    elif ret == 'char *':
                        global_decls.append(f"char * {gname};")
                        self._global_var_types[gname] = 'char *'
                        self._global_c_decl_types[gname] = 'char *'
                    else:
                        global_decls.append(f"int64_t {gname};")
                        self._global_var_types[gname] = 'int64_t'
                        self._global_c_decl_types[gname] = 'int64_t'
                elif (isinstance(value.func, MemberExpr)
                        and value.func.member in ('read', 'readline')
                        and not value.args):
                    global_decls.append(f"char * {gname};")
                    self._global_var_types[gname] = 'char *'
                    self._global_c_decl_types[gname] = 'char *'
                elif (isinstance(value.func, MemberExpr)
                        and value.func.member == 'readlines'):
                    global_decls.append(f"int64_t {gname};  /* MojoList * */")
                    self._global_var_types[gname] = 'MojoList *'
                    self._global_c_decl_types[gname] = 'int64_t'
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
            elif (isinstance(value, MemberExpr) and isinstance(value.obj, IdentExpr)
                    and value.obj.name in self.imported_symbols
                    and self.imported_symbols[value.obj.name].get('module')
                    and value.member in self._global_var_types
                    and getattr(self, '_global_to_module', {}).get(value.member)
                        == self.imported_symbols[value.obj.name].get('module')):
                # `X = submod.GLOBAL` — mirrors the identical MemberExpr
                # case added to `_phase17_value_type` above (see that
                # branch's docstring for the full why: without this, THIS
                # later pass — which actually determines the struct field
                # text and unconditionally overwrites whatever Phase 1.7
                # already inferred, since it runs AFTER Phase 1.7 — would
                # silently downgrade a correctly-inferred `char *` back to
                # `int64_t`, reintroducing the exact same "print(TESTFN)
                # shows a raw pointer address" bug Phase 1.7's fix alone
                # doesn't prevent).
                _mx_t = self._global_var_types[value.member]
                if _mx_t.endswith(' *'):
                    global_decls.append(f"{_mx_t} {gname};")
                    self._global_var_types[gname] = _mx_t
                    self._global_c_decl_types[gname] = _mx_t
                elif _mx_t == '_Bool':
                    global_decls.append(f"int {gname};")
                    self._global_var_types[gname] = 'int'
                    self._global_c_decl_types[gname] = 'int'
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
            else:
                qt = self._quick_type(value) or 'int64_t'
                if qt.endswith(' *') or qt == 'char *':
                    global_decls.append(f"{qt} {gname};")
                    self._global_var_types[gname] = qt
                    self._global_c_decl_types[gname] = (
                        'int64_t' if qt in ('MojoDict *', 'MojoList *', 'MojoSet *')
                        else qt)
                elif qt == '_Bool':
                    global_decls.append(f"int {gname};")
                    self._global_var_types[gname] = 'int'
                    self._global_c_decl_types[gname] = 'int'
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'

        for stmt in _collect_global_stmts(all_global_scan):
            if isinstance(stmt, VarDecl):
                # Module-level `var NAME: T = value` — a real global, not just
                # an AssignStmt. Without this, a top-level `var counter: Int = 0`
                # was never registered in _global_var_types, so a function doing
                # `global counter; counter += 1` emitted "counter undeclared"
                # (gcc error) at compile time. Reuse the AssignStmt path by
                # treating the VarDecl's name+value as the global definition.
                gname = stmt.name
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                if stmt.type_ann and stmt.value is None:
                    # A BARE (unassigned) annotation — `FAIL_REASON: str`,
                    # no `= ...` — e.g. a feature-detection global only
                    # ever assigned inside try/except/else (real instance:
                    # Lib/_pyrepl/main.py's CAN_USE_PYREPL/FAIL_REASON).
                    # `stmt.value` is None for this shape, so every
                    # isinstance(_gv, ...) check below used to fail and
                    # fall through to the final catch-all ("int gname;"),
                    # silently OVERWRITING whatever real pointer type the
                    # separate, EARLIER-running Phase 1.7 pre-scan (which
                    # has always consulted type_ann for exactly this case
                    # — see gen_module's "Phase 1.7" VarDecl branch) had
                    # already correctly recorded in these same
                    # self._global_var_types/_global_c_decl_types dicts —
                    # this loop runs LATER and unconditionally clobbers
                    # them.
                    #
                    # Resolve the annotation and declare the struct field
                    # using the SAME boxing convention this pass's own
                    # sibling branches already use (NOT Phase 1.7's: that
                    # pass's comment claims "every pointer-typed global is
                    # boxed as int64_t", but the actual, load-bearing
                    # convention -- both in _gscan_declare_global just
                    # above, for AssignStmt-declared globals, AND in the
                    # READ side, _lower_IdentExpr's `if gtype in
                    # ('MojoDict *', 'MojoList *', 'MojoSet *'): ctype =
                    # 'int64_t' else: ctype = gtype` -- only boxes
                    # MojoDict*/MojoList*/MojoSet*; a char*/struct-pointer
                    # global is declared and read as its real pointer type
                    # directly, unboxed. Boxing char* here too (an earlier
                    # version of this fix did, copying Phase 1.7's
                    # convention literally) declared the struct field
                    # int64_t while _lower_IdentExpr's read path still
                    # assigned it straight into a char* temp with no cast
                    # -- "assignment to 'char *' from 'int64_t'" at every
                    # read site. See bugs/hard/CODEGEN_global_prescan_
                    # blind_to_trystmt_and_bare_annotation.md, "Part 3".
                    _resolved = self._resolve_type(stmt.type_ann)
                    self._global_var_types[gname] = _resolved
                    if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                        global_decls.append(f"int64_t {gname};  /* {_resolved} */")
                        self._global_c_decl_types[gname] = 'int64_t'
                    else:
                        global_decls.append(f"{_resolved} {gname};")
                        self._global_c_decl_types[gname] = _resolved
                    continue
                _gv = stmt.value
                if (isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr)
                        and _gv.func.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                    # `var g_cooking_recipes = list()` / `= dict()` — a
                    # constructor CALL, not a `[...]`/`{...}` literal AST
                    # node, so none of the ListExpr/DictExpr/SetExpr branches
                    # below ever matched it; it fell all the way through to
                    # the final "else: int gname;" catch-all, which is wrong
                    # in the SAME way the literal-value branches were before
                    # this fix (and just as unboxed on top of being the wrong
                    # base type) — "assignment to 'int' from 'MojoList *'" at
                    # every read/write of such a global. Found alongside the
                    # `_fuel_burn_times` dict-literal bug in the same file
                    # (box.3d/game/lib/recipes.mojo's `g_cooking_recipes`/
                    # `g_stonecut_recipes`/`g_shapeless_recipes`/
                    # `g_shaped_recipes`/`g_name_to_id`).
                    _ctype = 'MojoDict *' if _gv.func.name in ('dict', 'Dict') else (
                        'MojoSet *' if _gv.func.name in ('set', 'Set') else 'MojoList *')
                    global_decls.append(f"int64_t {gname};  /* {_ctype} */")
                    self._global_var_types[gname] = _ctype
                    self._global_c_decl_types[gname] = 'int64_t'
                elif isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr):
                    # `var g_world = engine_create_world()` — a general
                    # user-function call (not a list()/dict()/set() literal
                    # constructor, handled above), whose return type may be
                    # a real struct pointer. This VarDecl-with-value inline
                    # scan (distinct from, and previously missing the
                    # CallExpr branch that, its sibling `_gscan_declare_
                    # global` function above already has — that function is
                    # only reached from the separate AssignStmt-based global
                    # scan, never from this VarDecl one) fell all the way
                    # through to the final "else: int gname;" catch-all for
                    # ANY function-call initializer, unconditionally
                    # declaring the struct field `int` regardless of the
                    # function's real return type. Harmless while every
                    # cross-module struct-typed consumer ALSO defaulted to a
                    # generic int64_t/int placeholder (a self-consistent,
                    # if imprecise, world) — but once a sibling function's
                    # OWN parameter type is correctly resolved to a real
                    # struct pointer (see _resolve_sibling_param_ctype /
                    # the "Process imports" loop's return-type correction
                    # above), a global initialized this way and then passed
                    # to such a function mismatches: "assignment to 'World
                    # *' from 'int' makes pointer from integer without a
                    # cast" (confirmed via box.3d/game/lib/game_ffi.mojo's
                    # real `var g_world = engine_create_world()` +
                    # `engine_place_block(g_world, ...)`). Mirrors
                    # `_gscan_declare_global`'s own CallExpr branch exactly
                    # (same struct_field_types / func_return_types / char*
                    # / generic-int64_t rules) rather than inventing a new
                    # rule, so both scans agree on any name they might both
                    # eventually see.
                    if _gv.func.name in self.struct_field_types:
                        _struct_name = _gv.func.name
                        global_decls.append(f"{_struct_name} * {gname};")
                        self._global_var_types[gname] = f"{_struct_name} *"
                        self._global_c_decl_types[gname] = f"{_struct_name} *"
                    else:
                        _ret = self.func_return_types.get(_gv.func.name, '')
                        if _ret.endswith(' *'):
                            global_decls.append(f"{_ret} {gname};")
                            self._global_var_types[gname] = _ret
                            self._global_c_decl_types[gname] = _ret
                        elif _ret == 'char *':
                            global_decls.append(f"char * {gname};")
                            self._global_var_types[gname] = 'char *'
                            self._global_c_decl_types[gname] = 'char *'
                        else:
                            global_decls.append(f"int64_t {gname};")
                            self._global_var_types[gname] = 'int64_t'
                            self._global_c_decl_types[gname] = 'int64_t'
                elif isinstance(_gv, (IntLiteral, BoolLiteral)):
                    global_decls.append(f"int {gname};")
                    self._global_var_types[gname] = 'int'
                    self._global_c_decl_types[gname] = 'int'
                elif isinstance(_gv, StringLiteral):
                    global_decls.append(f"char * {gname};")
                    self._global_var_types[gname] = 'char *'
                    self._global_c_decl_types[gname] = 'char *'
                elif isinstance(_gv, (ListExpr, TupleExpr)):
                    # Boxed as int64_t at the struct-field level — the SAME
                    # convention this loop's own bare-annotation branch just
                    # above (and _gscan_declare_global's identical AssignStmt-
                    # without-annotation case) already use for a
                    # MojoDict*/MojoList*/MojoSet* global. This branch handles
                    # `var name: T = [...]/{...}/{elem, ...}` — a VarDecl with
                    # BOTH a type_ann and a value — and previously declared
                    # the struct field as the real pointer type directly,
                    # unboxed, while every *read* site of a module-level
                    # dict/list/set global (_lower_IdentExpr et al) assumes
                    # the boxed convention: "assignment to 'int64_t' from
                    # 'MojoList *'/'MojoDict *'/'MojoSet *' makes integer from
                    # pointer without a cast" at every read. Found via
                    # box.3d/game/lib/recipes.mojo's
                    # `var _fuel_burn_times: Dict[Int, Int] = {}`, which
                    # failed to compile standalone (a WRITE —
                    # `_fuel_burn_times[k] = v` — happened to declare its own
                    # temp straight from the correct semantic type and so
                    # never tripped over this).
                    global_decls.append(f"int64_t {gname};  /* MojoList * */")
                    self._global_var_types[gname] = 'MojoList *'
                    self._global_c_decl_types[gname] = 'int64_t'
                elif isinstance(_gv, DictExpr):
                    global_decls.append(f"int64_t {gname};  /* MojoDict * */")
                    self._global_var_types[gname] = 'MojoDict *'
                    self._global_c_decl_types[gname] = 'int64_t'
                elif isinstance(_gv, SetExpr):
                    global_decls.append(f"int64_t {gname};  /* MojoSet * */")
                    self._global_var_types[gname] = 'MojoSet *'
                    self._global_c_decl_types[gname] = 'int64_t'
                elif isinstance(_gv, IdentExpr) and _gv.name in self._global_var_types:
                    global_decls.append(f"{self._global_var_types[_gv.name]} {gname};")
                    self._global_c_decl_types[gname] = self._global_c_decl_types.get(
                        _gv.name, self._global_var_types[_gv.name])
                else:
                    global_decls.append(f"int {gname};")
                    self._global_var_types[gname] = 'int'
                    self._global_c_decl_types[gname] = 'int'
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                gname = stmt.target.name
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                _gscan_declare_global(gname, stmt.value)
            elif (isinstance(stmt, ComptimeVarStmt)
                    and isinstance(stmt.value, (ListExpr, TupleExpr))):
                # Struct-field-declaration sibling of this file's other two
                # ComptimeVarStmt/ListExpr branches (Phase 1.7's type-only
                # pre-scan, and the toplevel-statement dispatch loop that
                # synthesizes the matching runtime-init AssignStmt) — see
                # either of those for the full why. Without this branch, the
                # C struct backing this module's globals never gained a
                # field for the comptime array at all, so a synthesized
                # init AssignStmt (this file's earlier fix) that reads
                # `<module>_globals.<name>` at startup referenced an
                # undeclared struct member ("invalid use of undefined type"
                # / "undeclared" GCC errors). Reuses `_gscan_declare_global`
                # exactly like a plain `NAME = [...]` global would.
                gname = stmt.target
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                _gscan_declare_global(gname, stmt.value)
            elif isinstance(stmt, MultiAssignStmt):
                # `a = b = ... = expr` at module scope (e.g. `Lib/codecs.py`'s
                # `BOM_LE = BOM_UTF16_LE = b'\xff\xfe'`) was invisible to
                # this scan — only plain single-target AssignStmt was ever
                # matched above — so a global ONLY ever assigned via a
                # chained assignment never got a struct field declared for
                # it at all. See `_gscan_declare_global`'s own docstring
                # for why this must stay in sync with the separate Phase
                # 1.7 pre-scan's identical fix. Every target gets the same
                # inferred type (real Python chained-assignment semantics).
                for _tgt in stmt.targets:
                    if not isinstance(_tgt, IdentExpr):
                        continue
                    gname = _tgt.name
                    if gname in _declared_globals:
                        continue
                    _declared_globals.add(gname)
                    _gscan_declare_global(gname, stmt.value)
            elif isinstance(stmt, VarDecl) and stmt.name not in _declared_globals:
                _declared_globals.add(stmt.name)
                ctype = self._resolve_type(stmt.type_ann) if stmt.type_ann else 'int64_t'
                global_decls.append(f"{ctype} {stmt.name};")
                self._global_var_types[stmt.name] = ctype
                self._global_c_decl_types[stmt.name] = ctype
            elif isinstance(stmt, ImportStmt):
                # `import X as Y` (esp. platform-conditional: `import posixpath
                # as path` / `import ntpath as path` inside os.py's if/else)
                # must register the bound name `Y` as a module-globals struct
                # field. The non-recursive top-level scan above only sees imports
                # at the very top level; _collect_global_stmts recurses into
                # IfStmt/TryStmt/ForStmt bodies, so an import nested there was
                # silently dropped — leaving `globals.path` referencing a field
                # that was never emitted (bug: "struct _X_toplev has no member
                # named 'path'"). Mirror the top-level ImportStmt handler here.
                for _tm, _ta in _import_targets(stmt):
                    local_name = _ta if _ta else _tm
                    if local_name not in _declared_globals:
                        _declared_globals.add(local_name)
                        global_decls.append(f"int64_t {local_name};")
                        self._global_var_types[local_name] = 'int64_t'
                        self._global_c_decl_types[local_name] = 'int64_t'
                        if local_name not in self._global_to_module:
                            self._global_to_module[local_name] = current_mod_name
        # Skip emitting standalone global declarations — they'll be in module globals structs instead
        # if global_decls:
        #     parts.extend(global_decls)
        #     parts.append('')

        # Populate _module_globals tracking from collected globals
        # Build a map of global name -> module name for later lookup.
        #
        # Do NOT reassign `self._global_to_module` to a fresh `{}` here —
        # it's a SHARED, by-reference dict across every GimpleGen instance
        # in the whole transitive-closure build (see its own declaration
        # in __init__: "global_name -> module_name (shared)", and
        # `_compile_imported_module`'s `temp_gen._global_to_module = self.
        # _global_to_module` sharing). Reassigning the attribute here
        # silently detaches THIS instance from that shared object going
        # forward — every entry any OTHER module's Phase 1.7/this-same
        # section wrote into the ORIGINAL dict stays correct there, but
        # THIS instance's own later reads (in particular `_lower_
        # IdentExpr`'s bare-identifier "does this name belong to some
        # OTHER module" check, which runs during this SAME gen_module
        # call's later statement-lowering phase) only ever see a narrow,
        # freshly-rebuilt view containing just `current_mod_name`'s own
        # globals — losing all ownership information about every other
        # module's globals discovered via Phase 1.7 just above. Confirmed
        # real bug (found via `mojo.py`'s own self-host build): removing
        # this reassignment (this fix) plus scoping Phase 1.7's ownership
        # writes to a module's own statements (that section's own fix,
        # same commit) together resolve a same-symptom regression where a
        # closure inside `gimple_codegen.py` capturing its own enclosing
        # function's `filename` PARAMETER got misresolved as
        # `_gimple_codegen_globals.filename` (a field gimple_codegen.py
        # never declares — the real one lives in `mojo_compiler.py`). See
        # bugs/CODEGEN_generator_function_Lib_weakref.md.
        for gname in sorted(_declared_globals):   # sorted: deterministic field order for bootstrap
            if gname in self._global_var_types:
                g_mtype = self._global_var_types[gname]
                # Use g_mtype as C type; if it ends with *, it's a pointer type
                # Otherwise default to int64_t for numeric types
                if gname in self._global_c_decl_types:
                    c_type = self._global_c_decl_types[gname]
                elif g_mtype and g_mtype.endswith(' *') \
                        and self._cpp_known_ptr_struct(g_mtype):
                    c_type = g_mtype
                else:
                    c_type = 'void *' if (g_mtype and g_mtype.endswith(' *')) else (
                        g_mtype if g_mtype and g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *', 'char *') else 'int64_t')
                # Find the initialization expression from stmts
                init_code = '0'
                for stmt in _collect_global_stmts(all_global_scan):
                    if isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr) and stmt.target.name == gname:
                        init_code = _extract_init_expr(stmt.value)
                        break
                    elif (isinstance(stmt, MultiAssignStmt)
                            and any(isinstance(_t, IdentExpr) and _t.name == gname for _t in stmt.targets)):
                        # Same chained-assignment blind spot as the two
                        # scans above (`_gscan_declare_global`/Phase 1.7) —
                        # without this, a global ONLY ever assigned via
                        # `a = b = expr` always got a '0' initializer
                        # (harmless for most types since _gen_toplevel's
                        # own runtime assignment sets the real value right
                        # after, but inconsistent with the plain-AssignStmt
                        # case just above, which extracts the real literal).
                        init_code = _extract_init_expr(stmt.value)
                        break
                    elif isinstance(stmt, ImportStmt) and gname in (
                            (_ta if _ta else _tm) for _tm, _ta in _import_targets(stmt)):
                        init_code = '0'
                        break
                if (gname, c_type, g_mtype) not in self._module_globals[current_mod_name]:
                    self._module_globals[current_mod_name].append((gname, c_type, g_mtype))
                    self._module_global_inits[current_mod_name][gname] = init_code
                    self._global_to_module[gname] = current_mod_name

        # Generate per-module struct typedefs and instances for globals.
        # Build into a local list and insert *before* the imported module code so that
        # imported functions referencing this module's globals (e.g. _root_globals.x) see
        # the complete struct type rather than the incomplete forward declaration.
        if self._module_globals.get(current_mod_name):
            globals_list = self._module_globals[current_mod_name]
            # Ensure module names are valid C identifiers (replace dots → underscores)
            current_mod_str = str(current_mod_name) if current_mod_name else "root"
            safe_name = _c_field_name(current_mod_str) if current_mod_str else "root"
            typedef_name = f"_{safe_name}_toplev"

            globals_struct_lines = []
            # Emit struct typedef, guarded the identical way (same macro
            # name, derived purely from `safe_name`) as the "other
            # referenced modules" reconstruction above — see that block's
            # comment (bugs/hard/COMPILE_FAIL_module_toplev_struct_never_
            # fully_defined.md, "mechanism 2"). An ancestor level may have
            # already emitted (or may later emit) a field-matching
            # reconstruction of this exact struct before this module's own
            # "official" text ends up positioned in the final file — the
            # guard makes whichever occurrence is textually first the one
            # real definition, with every other one a harmless no-op,
            # regardless of emission order or how many places attempt it.
            _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_name}'
            globals_struct_lines.append(f'#ifndef {_toplev_guard}')
            globals_struct_lines.append(f'#define {_toplev_guard}')
            globals_struct_lines.append(f"typedef struct {typedef_name} {{")
            for gname, c_type, _ in globals_list:
                globals_struct_lines.append(f"  {c_type} {_c_field_name(gname)};")
            globals_struct_lines.append(f"}} {typedef_name};")
            globals_struct_lines.append('#endif')
            globals_struct_lines.append("")

            # Emit struct instance with initializers
            instance_name = f"_{safe_name}_globals"
            globals_struct_lines.append(f"struct {typedef_name} {instance_name} = {{")
            inits = self._module_global_inits.get(current_mod_name, {})

            for gname, c_type, _ in globals_list:
                init_val = inits.get(gname)
                # C struct initializers must be compile-time constants
                # Only use simple values; function calls must be deferred to runtime
                if not init_val or init_val == '0' or 'mojo_' in str(init_val) or 'new' in str(init_val):
                    # Use compile-time constant: NULL for pointers, 0 for integers
                    if c_type.endswith(' *'):
                        init_val = f'({c_type})0'
                    else:
                        init_val = '0'
                elif init_val.startswith('"') or init_val.startswith("'"):
                    # String literals are OK
                    pass
                elif init_val.lstrip('-').isdigit():
                    # Numeric literals are OK
                    pass
                else:
                    # Non-constant expression - use default null
                    if c_type.endswith(' *'):
                        init_val = f'({c_type})0'
                    else:
                        init_val = '0'
                globals_struct_lines.append(f"  .{_c_field_name(gname)} = {init_val},")
            globals_struct_lines.append("};")
            globals_struct_lines.append("")

            # Synthesized cross-module accessor for every one of THIS
            # module's own plain `var` globals (BUG-2026-009) — a real,
            # externally-linked, module-qualified C function that a
            # DIFFERENT translation unit (a bare `from thismodule import
            # <this_global>` in another `mojo dylib`-compiled module — see
            # `_emit_imported_global_accessors`, the consuming half) can
            # `extern`-declare and call to read this global's REAL, live
            # value/pointer, instead of trying to replicate this module's
            # own internal globals-struct FIELD LAYOUT in a foreign TU
            # (fragile: two independently-compiled translation units
            # agreeing byte-for-byte on a whole struct's field order/
            # offsets is not something this per-module-independent compile
            # path can guarantee — a partial/foreign reconstruction of
            # this struct with only ONE field, e.g., would read the WRONG
            # offset whenever this real struct has other fields ahead of
            # it). Emitted unconditionally for every global — mirroring
            # how every free function is already unconditionally exported
            # (module A's own compile has no visibility into which OTHER
            # modules, if any, actually import a given name) — so this is
            # pure additional exported surface, never a behavior change
            # for this module's own code (nothing here is called from
            # THIS module's own body). Symbol naming
            # (`<safe_name>__mojo_global_get_<field>`) must exactly match
            # what `_emit_imported_global_accessors` independently derives
            # on the importing side — both computed via the same
            # `_c_field_name`/`module_name_for_path` convention, so a
            # sibling module's compile agrees on the symbol without either
            # side needing to see the other's actual compile.
            for gname, c_type, _ in globals_list:
                _acc_sym = f'{safe_name}__mojo_global_get_{_c_field_name(gname)}'
                globals_struct_lines.append(
                    f'{c_type} {_acc_sym} (void) {{ return {instance_name}.{_c_field_name(gname)}; }}')
            globals_struct_lines.append("")

            insert_idx = _module_globals_insert_idx
            if insert_idx is not None and insert_idx <= len(parts):
                parts[insert_idx:insert_idx] = globals_struct_lines
            else:
                parts.extend(globals_struct_lines)

        # Class-level attribute globals (class body AssignStmt not in __init__)
        class_attr_decls = []
        class_attr_inits = []
        for s in all_struct_defs:
            if isinstance(s, StructDef):
                class_attrs = self._class_attrs
                for aname, mangled in class_attrs.get(s.name, {}).items():
                    # Find the assignment in the class body to determine value type
                    for field in s.fields:
                        if isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr) and field.target.name == aname:
                            v = field.value
                            ctype = _class_attr_ctype(v)
                            if ctype == 'MojoSet *':
                                # Build init code: create set and add elements
                                inits = [f"  {mangled} = mojo_set_new();"]
                                _set_elts = v.elements if isinstance(v, SetExpr) else []
                                for elt in _set_elts:
                                    if isinstance(elt, StringLiteral):
                                        inits.append(f'  mojo_set_add_str ({mangled}, "{_c_escape(elt.value)}");')
                                    elif isinstance(elt, IntLiteral):
                                        inits.append(f'  mojo_set_add_int ({mangled}, {elt.value});')
                                class_attr_inits.extend(inits)
                            elif ctype == 'MojoDict *':
                                class_attr_inits.append(f"  {mangled} = mojo_dict_new();")
                            elif ctype == 'MojoList *':
                                class_attr_inits.append(f"  {mangled} = mojo_list_new();")
                            elif isinstance(v, StringLiteral):
                                ctype = 'char *'
                                class_attr_inits.append(f'  {mangled} = "{_c_escape(v.value)}";')
                            elif isinstance(v, IntLiteral):
                                ctype = 'int64_t'
                                class_attr_inits.append(f'  {mangled} = {v.value};')
                            else:
                                ctype = 'int64_t'
                            class_attr_decls.append(f"{ctype} {mangled};")
                            self._global_var_types[mangled] = ctype
                            break
        if class_attr_decls:
            parts.extend(class_attr_decls)
            parts.append('')
        # Save for use in module init
        self._class_attr_inits = class_attr_inits

        # Free-function "memoize on the function object" attribute globals
        # (`_func_attrs` — see its pre-scan docstring, gen_module Phase 1,
        # and `_lower_MemberExpr`/`_gen_stmt_AssignStmt`'s matching read/
        # write branches). Emitted once per (function, attr) pair across the
        # WHOLE transitive closure — `_emitted_funcattr_decls` (shared the
        # same way `_emitted_ptr_helpers`/`_emitted_funcptr_builtins` are;
        # see those fields' own sharing comments in `_compile_imported_
        # module`) guards against a duplicate `int64_t` definition if two
        # nested temp_gens both see the same already-inlined function.
        # `static`, matching `class_attr_decls` immediately above: this is a
        # single-C-file/whole-program compile (do_imports=True), so there's
        # no cross-translation-unit sharing need, and `static` avoids ANY
        # theoretical clash with an unrelated same-named global elsewhere.
        _funcattr_decls = []
        for _fn_name in sorted(self._func_attrs):
            for _attr in sorted(self._func_attrs[_fn_name]):
                _mangled = self._func_attrs[_fn_name][_attr]
                if _mangled in self._emitted_funcattr_decls:
                    continue
                self._emitted_funcattr_decls.add(_mangled)
                _gtype = self._global_var_types.get(_mangled, 'int64_t')
                _funcattr_decls.append(f"static {_gtype} {_mangled};")
        if _funcattr_decls:
            parts.extend(_funcattr_decls)
            parts.append('')

        # Struct typedefs (dedup across modules, keep most complete definition)
        if self.emit_struct_defs:
            track_best = {}
            for s in (stmts + self._imported_typedef_structs
                      + (imported_stmts if (self.do_imports or self.link_imports) else [])):
                if isinstance(s, StructDef):
                    field_count = len([f for f in s.fields if isinstance(f, VarDecl)])
                    if s.name not in track_best or field_count > track_best[s.name][1]:
                        track_best[s.name] = (s, field_count)

            for sd, _ in track_best.values():
                if sd.name not in self._emitted_structs:
                    _td_start = len(parts)
                    if sd.name == 'Pointer':
                        parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                        _td_start = len(parts)
                    parts.append(f"typedef struct {sd.name} {{")
                    # Runtime type tag, always first — see mojo_read_type_tag
                    # in runtime/mojo_runtime.c and _struct_type_id above. Must
                    # be the leading field: reading it back needs no per-struct
                    # layout knowledge, just a plain int64_t* dereference of the
                    # struct's own address (no padding precedes a first member).
                    parts.append(f"  int64_t __mojo_type_id;")
                    emitted_fields = set()
                    for field in sd.fields:
                        if isinstance(field, VarDecl):
                            # Use inferred type from struct_field_types, or resolve from annotation
                            if sd.name in self.struct_field_types and field.name in self.struct_field_types[sd.name]:
                                ft = self.struct_field_types[sd.name][field.name]
                            else:
                                ft = self._resolve_type(field.type_ann) if field.type_ann else 'int'
                            safe_fn = f'_kw_{field.name}' if (field.name in _C_KEYWORDS or field.name in _C_PARAM_EXTRA_KEYWORDS) else field.name
                            # Fixed-size-array field marker ("ElemCtype[N]",
                            # see _FIXED_ARRAY_ANN_RE / Section 1's identical
                            # handling above): the size goes after the field
                            # name in C array-declarator syntax.
                            _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
                            if _arr_dm:
                                parts.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
                            else:
                                parts.append(f"  {ft} {safe_fn};")
                            emitted_fields.add(field.name)
                    # Also emit any fields that are in struct_field_types but not in AST fields
                    if sd.name in self.struct_field_types:
                        for field_name, field_type in self.struct_field_types[sd.name].items():
                            if field_name not in emitted_fields:
                                safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                                _arr_dm2 = re.match(r'^(.+)\[(\d+)\]$', field_type)
                                if _arr_dm2:
                                    parts.append(f"  {_arr_dm2.group(1)} {safe_fn}[{_arr_dm2.group(2)}];")
                                else:
                                    parts.append(f"  {field_type} {safe_fn};")
                    parts.append(f"}} {sd.name};")
                    # Milestone C step 3: see the identical capture in the
                    # struct_field_types-based typedef path above (Section 1)
                    # — this is Section 2's own analogous copy, for a struct
                    # only ever emitted via THIS path (not already in
                    # struct_field_types when Section 1 ran).
                    self._struct_typedef_texts[sd.name] = '\n'.join(parts[_td_start:])
                    # Suppress any builtin-ctor function stub of the same name in
                    # this or another module (a `typedef … Name;` type collides
                    # with an `int64_t Name(...)` function) — see _guarded_ctor.
                    parts.append(f"#define {_stub_guard_name(sd.name)}")
                    parts.append('')
                    self._emitted_structs.add(sd.name)

            # Closure env struct typedefs (main module: inside emit_struct_defs block)
            for inner_map in self._all_closures.values():
                for ci in inner_map.values():
                    if ci.env_struct and ci.env_struct not in self._emitted_structs:
                        parts.append(f"typedef struct {ci.env_struct} {{")
                        for vname, vtype in ci.captures:
                            # A mutably-captured (`{mut}`-spec) name gets a
                            # pointer field instead of a value copy -- see
                            # ClosureInfo.mut_names.
                            field_ctype = f"{vtype} *" if vname in ci.mut_names else vtype
                            parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                        parts.append(f"}} {ci.env_struct};")
                        parts.append('')
                        self._emitted_structs.add(ci.env_struct)

            # ── Phase C: Dispatch table typedefs (from solver) ──────────────
            # Emit vtable struct typedefs for all planned dispatch tables
            if self._dispatch_solver and self._dispatch_tables:
                for callee_set, dispatch_table in self._dispatch_tables.items():
                    if dispatch_table.name not in self._emitted_dispatch_typedefs:
                        typedef = dispatch_table.emit_typedef()
                        if typedef:
                            parts.append(typedef)
                            parts.append('')
                            self._emitted_dispatch_typedefs.add(dispatch_table.name)

        # Struct alloc helpers — __GIMPLE OK because StructName * is the return type
        # Emitted before user-function forward decls so no forward decl needed.
        for sn in sorted(self._struct_allocs_needed):
            if sn in self._emitted_allocs:
                continue  # already emitted by an imported module
            self._emitted_allocs.add(sn)
            alloc_name = f'_alloc_{sn}'
            if alloc_name not in self.func_return_types:
                self.func_return_types[alloc_name] = f'{sn} *'
            # Class-level attributes that are ALSO modeled as instance struct
            # fields (see struct_field_types['Parser']['_CONV_KWS'] etc. and
            # the "self-host hardcoded struct tables" memory note) need their
            # instance slot seeded from the class-level global right here.
            # Member-READ lowering (_lower_MemberExpr) checks struct_field_types
            # BEFORE _class_attrs, so once a name is in both tables (needed so
            # the field gets the right C type / doesn't corrupt self-host
            # GIMPLE type inference), `self.X` reads the INSTANCE field, not
            # the class global - and _alloc_{sn} used to leave every field but
            # __mojo_type_id as raw malloc garbage. A class attribute like
            # `_CONV_KWS = {...}` is never assigned inside __init__ (Python's
            # own attribute-lookup fallback to the class dict is exactly why
            # the source never needs to), so nothing else ever initializes
            # that instance slot - `self._peek().value in self._CONV_KWS`
            # dereferenced garbage as a MojoSet*, segfaulting the first time
            # a self-hosted Parser actually exercised the ref/out/mut
            # soft-keyword path (found debugging make bootstrap's stage2
            # SIGSEGV on mojo_compiler.py). Seeding from the class global here
            # mirrors real Python semantics (a fresh instance's attribute
            # starts as the class value until something assigns over it) and
            # composes correctly with any later `self.X = ...` in __init__/
            # methods, which still just overwrites this same instance field.
            class_attrs = self._class_attrs.get(sn, {})
            field_map = self.struct_field_types.get(sn, {})
            # Only seed when the instance field's declared type actually
            # matches the global's: some class attributes (e.g.
            # LayoutSolver.STACK/HEAP, plain string constants with no `var`
            # annotation) have an unrelated, pre-existing type-inference gap
            # in struct_field_types (defaulting to the wrong C type) that was
            # previously harmless because nothing ever wrote into that
            # instance slot - introducing a write here would turn that latent
            # gap into a new compile error. Skip those; they're no worse off
            # than before this fix (still uninitialized instance-field
            # garbage if ever read that way, same as pre-existing behavior).
            attr_inits = ''.join(
                f"  _p->{_safe_field(aname)} = {gname};\n"
                for aname, gname in sorted(class_attrs.items())
                if aname in field_map
                and field_map[aname] == self._global_var_types.get(gname, field_map[aname])
            )
            parts.append(
                # static: each module that needs it emits its own copy; the
                # monolithic stdlib dylib compiles modules independently, so an
                # externally-linked _alloc_<sn> would collide at link time.
                # Stamps __mojo_type_id (the struct's first field, see the
                # typedef emission above) so isinstance(x, sn) can recognize
                # this instance later — the sole struct-construction choke
                # point, so this is the only place that needs to set it.
                f"static {sn} * __GIMPLE _alloc_{sn} (void)\n"
                f"{{\n"
                f"  {sn} * _p;\n"
                f"  void * _vp;\n"
                f"  int64_t _tag;\n"
                f"\nbb_2:\n"
                # calloc, not malloc: a field with no initializer must read
                # back as 0/NULL (this runtime's None), not as whatever the
                # heap happened to hold. `struct Point: x: Int; y: Int` with
                # no __init__ (test_struct.mojo) left BOTH fields garbage, and
                # any pointer-typed field then fed a wild address to the
                # generic repr/getattr dispatch — a NONDETERMINISTIC segfault
                # (~25% of runs) that made `make bootstrap`'s stage 3 flaky.
                # Zeroing is also what every reader here already assumes: the
                # reflection helpers, _mojo_repr_*, and the `?:` None-guards
                # all test a field against 0/NULL.
                f"  _vp = calloc (1, sizeof({sn}));\n"
                f"  _p = ({sn} *) _vp;\n"
                f"  _tag = (int64_t){_struct_type_id(sn)};\n"
                f"  _p->__mojo_type_id = _tag;\n"
                f"{attr_inits}"
                f"  return _p;\n"
                f"}}"
            )
            parts.append('')

        # Generic reflection dispatch: getattr(x, name)/setattr(x, name, v)/
        # dataclasses.fields(x)/dataclasses.is_dataclass(x) on a value whose
        # static type is unknown (boxed as int64_t/void*) previously always
        # routed to the runtime's mojo_obj_getattr/mojo_setattr stubs, which
        # either abort() (a hard crash: e.g. ast_rewriter.py's generic
        # AST-node walk doing `getattr(node, f.name)`) or silently no-op.
        # Every codegen-emitted struct already carries a runtime type tag
        # (__mojo_type_id, see mojo_read_type_tag in runtime/mojo_runtime.c)
        # and this file already knows every struct's field names/types
        # (struct_field_types) — so a real dispatch table can be built here,
        # once per linked program, instead of leaving this permanently a stub.
        # Plain (non-__GIMPLE) C: GIMPLE's SSA-only restrictions don't apply
        # to functions without that marker (see _HELPERS above), so ordinary
        # if/strcmp control flow is fine here.
        if self.emit_struct_defs:
            # Scoped to structs actually ALLOCATED in this specific program
            # (not the full struct_field_types, which also carries every
            # hardcoded self-hosting compiler class — Parser, Interpreter,
            # Token, etc. — unconditionally, regardless of whether this
            # program touches them). Emitting a getattr/setattr/fieldnames
            # accessor per entry there bloated even a trivial unrelated
            # client program's compiled size (module-cache's whole point is
            # a client stays tiny because bodies live in the shared dylib —
            # see test_module_cache.py's "client object is tiny" checks).
            # _struct_allocs_needed itself used to only track the ROOT
            # module's own allocations, missing structs (e.g. StructDef)
            # only ever constructed inside an IMPORTED module's functions —
            # now shared across temp_gen sub-compiles like _emitted_structs
            # already was (see the do_imports module-compile setup above).
            reflect_structs = sorted(set(self.struct_field_types.keys())
                                      & self._emitted_structs & self._struct_allocs_needed)
            refl_parts = []
            for sn in reflect_structs:
                fields = self.struct_field_types.get(sn, {})
                if not fields:
                    continue
                get_lines = []
                set_lines = []
                name_lits = []
                asdict_lines = []
                for fname, ftype in fields.items():
                    if fname == '__mojo_type_id':
                        continue
                    safe_f = _safe_field(fname)
                    # Fixed-size-array field ("ElemCtype[N]", see
                    # _FIXED_ARRAY_ANN_RE): `obj->field` names the whole
                    # embedded array, not a scalar/pointer value — casting
                    # a VALUE to an array type ("(Block[4096])val") is not
                    # legal C, so this generic reflection dispatch (only
                    # ever reached for dynamically-typed/unknown-receiver
                    # getattr/setattr, never ordinary compiled field access)
                    # just skips it, same as any other field shape this
                    # dispatch doesn't understand — no regression, since this
                    # shape had no reflection support before this fix either.
                    if re.match(r'^.+\[\d+\]$', ftype):
                        name_lits.append(f'"{fname}"')
                        continue
                    if ftype.endswith(' *'):
                        get_lines.append(
                            f'  if (strcmp(attr, "{fname}") == 0) return (int64_t)(intptr_t)obj->{safe_f};')
                        set_lines.append(
                            f'  if (strcmp(attr, "{fname}") == 0) {{ obj->{safe_f} = ({ftype})(intptr_t)val; return; }}')
                        asdict_lines.append(
                            f'  mojo_dict_set_int(_r, "{fname}", (int64_t)(intptr_t)obj->{safe_f});')
                    else:
                        get_lines.append(
                            f'  if (strcmp(attr, "{fname}") == 0) return (int64_t)obj->{safe_f};')
                        set_lines.append(
                            f'  if (strcmp(attr, "{fname}") == 0) {{ obj->{safe_f} = ({ftype})val; return; }}')
                        asdict_lines.append(
                            f'  mojo_dict_set_int(_r, "{fname}", (int64_t)obj->{safe_f});')
                    name_lits.append(f'"{fname}"')
                # `obj.__dict__`/`vars(obj)` on a struct with statically-known
                # fields (Step 0 of bugs/hard/
                # CODEGEN_dynamic_attribute_on_generic_object.md) — a real
                # MojoDict* view of the struct's OWN fields, matching
                # Python's `obj.__dict__` semantics, reusing this same
                # per-struct field enumeration rather than a second,
                # separately-maintained field list. Every value goes through
                # mojo_dict_set_int (the same generic int64_t boxed-value
                # convention every other MojoDict* this codegen builds
                # already uses), matching how _mojo_getattr_{sn}/repr's own
                # per-field access already treat pointer vs. scalar fields
                # identically at the storage-representation level. Gated on
                # `_asdict_dispatch_needed` (see its own declaration) —
                # UNLIKE its getattr/setattr/fieldnames siblings just above
                # (always emitted, however trivial), this one is genuinely
                # optional per-compile and a real client-object-size
                # regression (test_module_cache.py's "client object is
                # tiny" check) confirmed it must not be unconditional.
                asdict_part = (
                    f"static MojoDict * _mojo_asdict_{sn} ({sn} *obj) {{\n"
                    f"  MojoDict *_r = mojo_dict_new();\n"
                    + "".join(asdict_lines) +
                    f"\n  return _r;\n}}\n"
                ) if self._asdict_dispatch_needed else ""
                refl_parts.append(
                    f"static int64_t _mojo_getattr_{sn} ({sn} *obj, char *attr) {{\n"
                    + "\n".join(get_lines) +
                    f"\n  return mojo_obj_getattr((void *)obj, attr);\n}}\n"
                    f"static void _mojo_setattr_{sn} ({sn} *obj, char *attr, int64_t val) {{\n"
                    + "\n".join(set_lines) +
                    f"\n  mojo_setattr((void *)obj, attr, val);\n}}\n"
                    f"static MojoList * _mojo_fieldnames_{sn} (void) {{\n"
                    f"  MojoList *_r = mojo_list_new();\n"
                    + "".join(f'  mojo_list_append_str(_r, {nl});\n' for nl in name_lits) +
                    f"  return _r;\n}}\n"
                    + asdict_part
                )
            # Field-by-field repr() — mirrors Python's dataclass repr
            # ("ClassName(field1=..., field2=...)"). Before this, repr() on
            # any compiled struct pointer (e.g. `repr(ast)` on a parsed AST
            # list, mojo.py's own `--dump`) fell to mojo_repr_obj, which has
            # no field-metadata table and just prints an address — real bug
            # found via verify's .ast comparison, where every stage's dump
            # was a meaningless, non-comparable `<object at 0x...>` instead
            # of the node's actual content. Ambiguous case: a field statically
            # typed int64_t that's really an Optional[int]/Any box can't be
            # told apart from a genuine int here (both are the same C
            # representation and Python's None is also encoded as int64_t 0 —
            # see _lower_IdentExpr's `if name == 'None': return 'int', '0'`),
            # so it always prints as a plain number rather than guessing
            # "None" for 0 — the same reasoning as the col=0-not-None fix
            # above, just applied per-field instead of per-print-call.
            repr_fwd_decls = [f"static char * _mojo_repr_{sn} ({sn} *obj);" for sn in reflect_structs
                               if self.struct_field_types.get(sn)]
            for sn in reflect_structs:
                fields = self.struct_field_types.get(sn, {})
                if not fields:
                    continue
                boxed = self.struct_boxed_fields.get(sn, set())
                bool_fields = self.struct_bool_fields.get(sn, set())
                nullable_containers = self.struct_nullable_container_fields.get(sn, set())
                part_exprs = []
                for fname, ftype in fields.items():
                    if fname == '__mojo_type_id':
                        continue
                    safe_f = _safe_field(fname)
                    fref = f'obj->{safe_f}'
                    if sn == 'IntLiteral' and fname == 'value' and 'raw' in fields:
                        # IntLiteral.value wraps to a 64-bit machine word for
                        # real arithmetic, so a literal exceeding int64_t
                        # range (e.g. 0xFFFFFFFFFFFFFFFF) can't dump as the
                        # same decimal text Python's own arbitrary-precision
                        # int repr would show. `raw` (the original source
                        # token text) lets the dump reconstruct the exact
                        # decimal value instead — see
                        # mojo_int_literal_decimal's doc comment.
                        raw_fref = f"obj->{_safe_field('raw')}"
                        val_expr = (f'(({raw_fref} && {raw_fref}[0]) '
                                    f'? mojo_int_literal_decimal({raw_fref}) '
                                    f': mojo_repr_int((int64_t){fref}))')
                    elif fname in bool_fields:
                        val_expr = f'({fref} ? "True" : "False")'
                    elif fname in boxed and ftype in (
                            'int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                            'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                        val_expr = f'_mojo_generic_elem_repr((int64_t){fref})'
                    elif ftype == 'char *':
                        val_expr = f'({fref} ? mojo_repr_str({fref}) : "None")'
                    elif ftype == '_Bool':
                        val_expr = f'({fref} ? "True" : "False")'
                    elif ftype in ('double', 'float'):
                        val_expr = f'mojo_repr_float((double){fref})'
                    elif ftype == 'MojoList *':
                        # Double-aware repr when this field's element type is
                        # tracked (see _field_elem_types): the generic
                        # _mojo_repr_list mis-reprs (or crashes on) a list of
                        # doubles. Unknown element type keeps the generic repr.
                        if self._field_elem_types.get(sn, {}).get(fname) == 'double':
                            list_repr = f'mojo_repr_list_doubles({fref})'
                        else:
                            list_repr = f'_mojo_repr_list({fref})'
                        if fname in nullable_containers:
                            val_expr = f'({fref} ? {list_repr} : "None")'
                        else:
                            val_expr = list_repr
                    elif ftype == 'MojoDict *':
                        if fname in nullable_containers:
                            val_expr = f'({fref} ? _mojo_repr_dict({fref}) : "None")'
                        else:
                            val_expr = f'_mojo_repr_dict({fref})'
                    elif ftype in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                                   'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                        val_expr = f'mojo_repr_int((int64_t){fref})'
                    elif ftype.endswith(' *'):
                        val_expr = f'({fref} ? _mojo_dispatch_repr((void *){fref}) : "None")'
                    else:
                        val_expr = f'mojo_repr_int((int64_t){fref})'
                    part_exprs.append(f'"{fname}=", {val_expr}')
                cat_chain = f'strdup("{sn}(")'
                for i, pe in enumerate(part_exprs):
                    sep = ', ' if i > 0 else ''
                    if sep:
                        cat_chain = f'mojo_str_cat({cat_chain}, ", ")'
                    name_lit, val_e = pe.split(', ', 1)
                    cat_chain = f'mojo_str_cat({cat_chain}, {name_lit})'
                    cat_chain = f'mojo_str_cat({cat_chain}, {val_e})'
                cat_chain = f'mojo_str_cat({cat_chain}, ")")'
                refl_parts.append(
                    f"static char * _mojo_repr_{sn} ({sn} *obj) {{\n"
                    f"  if (!obj) return \"None\";\n"
                    f"  return {cat_chain};\n"
                    f"}}\n"
                )
            # Forward-declare _mojo_dispatch_repr/_mojo_repr_list/
            # _mojo_repr_dict/_mojo_generic_elem_repr UNCONDITIONALLY (not
            # just when repr_fwd_decls is non-empty): _mojo_generic_elem_repr's
            # own body (emitted below, unconditionally, as part of "Generic
            # reflection dispatch") calls _mojo_repr_list directly (to
            # recurse into a nested list/tuple element) regardless of whether
            # any struct actually needs reflection — with zero reflect_structs
            # (e.g. a trivial program with no structs at all), the old
            # `if repr_fwd_decls:` guard skipped this block entirely, leaving
            # _mojo_repr_list undeclared at its call site inside
            # _mojo_generic_elem_repr and triggering GCC's old-style
            # "implicit declaration" (defaults to int, "conflicting types"
            # once the real definition appears later). Same class of ordering
            # bug the repr_fwd_decls path itself was originally added to fix
            # (see below) — just not covering the empty case.
            parts.append("static char * _mojo_dispatch_repr (void *);")
            parts.append("static char * _mojo_repr_list (MojoList *);")
            parts.append("static char * _mojo_repr_dict (MojoDict *);")
            parts.append("static char * _mojo_generic_elem_repr (int64_t);")
            if repr_fwd_decls:
                # Must precede every _mojo_repr_<sn> body: AST-shaped structs
                # reference each other directly by field type (e.g. FunctionDef
                # has a StringLiteral-typed default, ExprStmt has a value: CallExpr
                # field), so alphabetically-later structs called by an earlier
                # one's body need to already be declared. Found via
                # compile_stdlib.py: _ListIter's generated repr called
                # _mojo_dispatch_repr with no declaration in scope yet,
                # "implicit declaration of function".
                parts.append("/* Forward decls for generic repr() (mutual struct references) */")
                parts.append("\n".join(repr_fwd_decls))
                parts.append('')
            if True:
                # Unconditional (even with refl_parts empty / reflect_structs
                # empty): a forward declaration for these 4 names is always
                # emitted (see "Always add forward decls for cross-module
                # struct methods" below) so an importer calling getattr()/
                # setattr()/dataclasses.fields()/is_dataclass() compiles —
                # the definition must always exist too, or that forward
                # declaration is a link-time dangling reference.
                parts.append("/* Generic reflection dispatch (getattr/setattr/dataclasses.fields/is_dataclass) */")
                parts.extend(refl_parts)
                tag_cases_get = "\n".join(
                    f'  if (_tag == {_struct_type_id(sn)}) return _mojo_getattr_{sn}(({sn} *)obj, attr);'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                tag_cases_set = "\n".join(
                    f'  if (_tag == {_struct_type_id(sn)}) {{ _mojo_setattr_{sn}(({sn} *)obj, attr, val); return; }}'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                tag_cases_fields = "\n".join(
                    f'  if (_tag == {_struct_type_id(sn)}) return _mojo_fieldnames_{sn}();'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                tag_cases_asdict = "\n".join(
                    f'  if (_tag == {_struct_type_id(sn)}) return _mojo_asdict_{sn}(({sn} *)obj);'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                tag_set_literal = ", ".join(
                    str(_struct_type_id(sn)) for sn in reflect_structs if self.struct_field_types.get(sn))
                if len(tag_set_literal) == 0:
                    tag_set_literal = "0"
                # `_mojo_dispatch_asdict` (Step 0 of bugs/hard/
                # CODEGEN_dynamic_attribute_on_generic_object.md) is, unlike
                # its 4 siblings just below, gated on `_asdict_dispatch_
                # needed` — see that flag's own declaration for why an
                # unconditional-like-its-siblings emission regressed
                # test_module_cache.py's tiny-client-object byte budget.
                asdict_dispatch_part = (
                    "static MojoDict * _mojo_dispatch_asdict (void *obj) {\n"
                    "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n"
                    + f"{tag_cases_asdict}\n"
                    + "  return mojo_dict_new();\n"
                    "}\n"
                ) if self._asdict_dispatch_needed else ""
                parts.append(
                    ("static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {\n"
                     "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                    + f"{tag_cases_get}\n"
                    + ("  return mojo_obj_getattr(obj, attr);\n"
                       "}\n"
                       "static void _mojo_dispatch_setattr (void *obj, char *attr, int64_t val) {\n"
                       "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                    + f"{tag_cases_set}\n"
                    + ("  mojo_setattr(obj, attr, val);\n"
                       "}\n"
                       "static MojoList * _mojo_dispatch_fields (void *obj) {\n"
                       "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                    + f"{tag_cases_fields}\n"
                    + ("  return mojo_list_new();\n"
                       "}\n")
                    + asdict_dispatch_part
                    + ("static int _mojo_dispatch_is_dataclass (void *obj) {\n"
                       "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                    + f"  static const int64_t _known[] = {{{tag_set_literal}}};\n"
                    + ("  if (_tag == 0) return 0;\n"
                       "  for (size_t _i = 0; _i < sizeof(_known)/sizeof(_known[0]); _i++)\n"
                       "    if (_known[_i] == _tag) return 1;\n"
                       "  return 0;\n"
                       "}\n")
                )
                tag_cases_repr = "\n".join(
                    f'  if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)obj);'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                tag_cases_repr_elem = "\n".join(
                    f'    if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)(intptr_t)val);'
                    for sn in reflect_structs if self.struct_field_types.get(sn))
                parts.append(
                    ("static char * _mojo_dispatch_repr (void *obj) {\n"
                     "  if (!obj) return \"None\";\n"
                     "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                    + f"{tag_cases_repr}\n"
                    + ("  return mojo_repr_obj((int64_t)(intptr_t)obj);\n"
                       "}\n"
                       "static char * _mojo_generic_elem_repr (int64_t val) {\n"
                       "  if (val == 0) return \"None\";\n"
                       "  if (val > 65536) {\n"
                       "    if (mojo_is_registered_list(val))\n"
                       "      return _mojo_repr_list((MojoList *)(intptr_t)val);\n"
                       "    if (mojo_is_registered_dict(val))\n"
                       "      return _mojo_repr_dict((MojoDict *)(intptr_t)val);\n"
                       "    int64_t _tag = mojo_read_type_tag_safe(val);\n")
                    + f"{tag_cases_repr_elem}\n"
                    + ("    return mojo_repr_str((char *)(intptr_t)val);\n"
                       "  }\n"
                       "  return mojo_repr_int(val);\n"
                       "}\n"
                       "static char * _mojo_repr_list (MojoList *lst) {\n"
                       "  int _is_tup = lst && mojo_is_tuple(lst);\n"
                       "  if (!lst) return _is_tup ? \"()\" : \"[]\";\n"
                       "  int64_t _n = mojo_list_len(lst);\n"
                       "  char *_buf = strdup(_is_tup ? \"(\" : \"[\");\n"
                       "  for (int64_t _i = 0; _i < _n; _i++) {\n"
                       "    if (_i > 0) _buf = mojo_str_cat(_buf, \", \");\n"
                       "    _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(mojo_list_get_int(lst, _i)));\n"
                       "  }\n"
                       "  if (_is_tup && _n == 1) _buf = mojo_str_cat(_buf, \",\");\n"
                       "  return mojo_str_cat(_buf, _is_tup ? \")\" : \"]\");\n"
                       "}\n"
                       "static char * _mojo_repr_dict (MojoDict *d) {\n"
                       "  if (!d) return \"{}\";\n"
                       "  int _is_booldict = mojo_is_bool_dict(d);\n"
                       "  char *_buf = strdup(\"{\");\n"
                       "  int64_t *_order = mojo_dict_order_indices(d);\n"
                       "  for (int64_t _oi = 0; _oi < d->used; _oi++) {\n"
                       "    int64_t _i = _order[_oi];\n"
                       "    if (_oi > 0) _buf = mojo_str_cat(_buf, \", \");\n"
                       "    _buf = mojo_str_cat(_buf, mojo_repr_str(d->slots[_i].key));\n"
                       "    _buf = mojo_str_cat(_buf, \": \");\n"
                       "    if (_is_booldict)\n"
                       "      _buf = mojo_str_cat(_buf, d->slots[_i].val ? \"True\" : \"False\");\n"
                       "    else\n"
                       "      _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(d->slots[_i].val));\n"
                       "  }\n"
                       "  free(_order);\n"
                       "  return mojo_str_cat(_buf, \"}\");\n"
                       "}\n"
                    )
                )
                parts.append('')

        # Forward declaration for class-attr initializer (main module only)
        if self.emit_struct_defs:
            parts.append("static void _mojo_classattr_init (void);")
            parts.append('')

        # Extern declarations: imported symbols with full parameter information
        # Skip symbols that are already hardcoded in the preamble
        hardcoded = {
            'mojo_print', 'gimple_codegen_compile_to_gimple', 'compile_to_gimple',
            'int_write', 'int_parse_module', 'py_tokenize', 'Parser', 'Interpreter'
        }
        # When do_imports=True, imported module code is inlined — functions will
        # have actual definitions, so extern stubs would conflict. Same for
        # link mode's own inlined-fallback modules (self._link_inline_modules,
        # compiled into imported_stmts above) — those have no dylib either.
        if self.do_imports or self.link_imports:
            inline_defined = set()
            for stmt in (imported_stmts or []):
                if isinstance(stmt, FunctionDef):
                    inline_defined.add(stmt.name)
                elif isinstance(stmt, StructDef):
                    for m in stmt.methods:
                        inline_defined.add(f"{stmt.name}_{m.name}")
                        inline_defined.add(m.name)
        else:
            inline_defined = set()

        # Modules that are pure-Python compiler/JIT infrastructure and are deliberately
        # NOT self-compiled (e.g. the ARM64 JIT engine). Symbols imported from them have
        # no native definition, so emit an abort stub instead of an unresolved extern,
        # letting the self-compiled binary link. These paths are never exercised in
        # compiled mode (the JIT engine only runs under the Python interpreter).
        # TODO: this is a hack. Hardcoding a stub-module allowlist and silently
        # replacing every imported symbol with a no-op stub is wrong — it papers over
        # the real gap (no native JIT engine) and will mask genuinely-missing symbols
        # from these modules. Fine for now to get self-compile to link; revisit with a
        # proper mechanism (e.g. explicit @python_only markers or compiling jit.arm64).
        _stub_only_modules = {'jit.arm64', 'jit'}
        for sym_name in sorted(self.imported_symbols.keys()):
            if sym_name in hardcoded:
                continue
            sym_info = self.imported_symbols[sym_name]
            # Skip module-level imports (import os / import re) — those become
            # int64_t global variables, not extern function declarations.
            if sym_info.get('return_type') == 'unknown':
                continue
            # Skip symbols that are defined inline (when do_imports=True)
            if sym_name in inline_defined or sym_name in self._global_inline_defs:
                continue
            # Skip struct names — they're declared as typedefs, not extern functions
            if sym_name in self.struct_field_types:
                continue
            # Skip C stdlib names declared by system headers — but only if the name is used
            # as-is (i.e., not renamed by _C_RESERVED_FUNCS). If the name IS reserved, the
            # call site uses 'mojo_<name>' (a different symbol) so we still need the extern.
            if sym_name in self._LIBC_DECLARED and sym_name not in _C_RESERVED_FUNCS:
                continue

            module = sym_info.get('module', '')
            if module in _stub_only_modules:
                # Provide a defined-but-unusable stub (plain C, like the _mojo_at_ helpers)
                # so the symbol resolves at link time.
                cname = _safe_name(sym_name)
                if cname in _emitted_unresolved_stub_syms:
                    continue
                _emitted_unresolved_stub_syms.add(cname)
                ret_type = sym_info.get('return_type', 'int64_t')
                ret_type = self._resolve_type(ret_type) if ret_type and ret_type != 'unknown' else 'int'
                if ret_type == 'void':
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
                else:
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
                # Guarded with the SAME canonical `_MOJO_STUB_{NAME}` macro
                # convention every other auto-stub generator in this file
                # uses (see the "no signature" branch below, and
                # `_lower_named_call`'s/`_gen_stmt_ExprStmt`'s `_is_unknown`
                # auto-stub paths) — this specific branch used to be emitted
                # completely UNGUARDED (no #ifndef at all), a latent
                # duplicate-definition risk for the same reason the "no
                # signature" branch below was fixed to use a matching guard
                # (see that fix's own comment / bugs/CODEGEN_generator_
                # function_Lib_weakref.md).
                _stub_only_guard = _stub_guard_name(cname)
                parts.append(f"#ifndef {_stub_only_guard}\n#define {_stub_only_guard}\n"
                              f"{ret_type} {cname} () {body}  /* stub from {module} */\n#endif")
                continue

            # _func_csym applies the overload suffix for imported Mojo functions so
            # this extern matches the defining module's mangled symbol and the call
            # sites in this module.
            safe = self._func_csym(sym_name)
            if 'signature' in sym_info:
                # For _C_RESERVED_FUNCS symbols (renamed to mojo_X), the Mojo wrapper may
                # have optional/default parameters that aren't passed at all call sites.
                # Use variadic (...) so any arity is accepted without "too few arguments".
                if sym_name in _C_RESERVED_FUNCS:
                    # Prefer c_return_type (already a C type) over return_type (Mojo type)
                    ret_type = sym_info.get('c_return_type') or sym_info.get('return_type', 'int64_t')
                    if ret_type and ret_type != 'unknown' and not any(
                            c in ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')):
                        ret_type = self._resolve_type(ret_type)
                    elif not ret_type or ret_type == 'unknown':
                        ret_type = 'int64_t'
                    parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")
                else:
                    # New format: use full signature with parameters, applying safe name
                    signature = sym_info['signature']
                    orig_name = sym_info.get('original_name', sym_name)
                    # `signature` text was built (module_loader/_local_sibling_
                    # module_exports) from the ORIGINAL definition's own
                    # source — it always literally contains `orig_name`, never
                    # the local alias `sym_name` (when the two differ). Always
                    # substitute `orig_name`, not `sym_name` — matches
                    # `_func_csym`'s own aliased-import handling just above
                    # (mangling base uses `original_name`, not the alias), so
                    # this extern's symbol and the call sites' emitted symbol
                    # always agree. Substituting `sym_name` here instead (the
                    # previous logic, keyed off `safe != sym_name` — true for
                    # nearly every mangled function) was a silent no-op for any
                    # ALIASED import: the regex searched for the alias, which
                    # never appears in a signature drawn from the real
                    # definition, so the extern kept the unmangled,
                    # unqualified original name — "implicit declaration of
                    # function 'qualifier_origname_hash'" at every call site.
                    if safe != orig_name:
                        signature = re.sub(r'\b' + re.escape(orig_name) + r'\b', safe, signature, count=1)
                    # Strip Mojo parameter modifiers (out, inout, mut, var, etc.) from signature
                    signature = re.sub(
                        r'\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\s+(?=\w)',
                        '', signature)
                    # Rename C control/storage keywords used as Mojo parameter names.
                    # Only rename non-type keywords: type keywords (void, int, char, etc.)
                    # legitimately appear as C types in extern signatures and must NOT be renamed.
                    for _ckw in ('default', 'register', 'auto', 'static', 'extern',
                                 'volatile', 'inline'):
                        signature = re.sub(r'\b' + _ckw + r'\b(?=\s*[,)])', f'_kw_{_ckw}', signature)
                    # Guard with #ifndef so C preprocessor macros (SEEK_END etc.) aren't
                    # accidentally redeclared (the macro would expand before gcc sees the decl).
                    parts.append(f"#ifndef {safe}\nextern {signature};  /* from {module} */\n#endif")
            else:
                # No 'signature' was ever attached (see module_loader.py — that
                # key is only set once a real definition is actually found,
                # whether an inlined Mojo function, a compiled dylib symbol,
                # or a reflected C signature). Reaching here means this name
                # (typically `from some_module import name`, e.g. `from
                # itertools import filterfalse`) was never resolved to any
                # real implementation.
                ret_type = sym_info.get('return_type', 'int64_t')
                ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
                if self.do_imports or self.link_imports:
                    # do_imports=True is `mojo.py build`'s standalone-binary
                    # mode: every resolvable Mojo definition is inlined into
                    # this same translation unit and would already have hit
                    # the `inline_defined`/`struct_field_types` skips above.
                    # So an unresolved name here is genuinely never defined
                    # anywhere this build will link against (e.g. a real
                    # Python stdlib module this project doesn't implement) —
                    # a bare `extern` forward declaration would leave an
                    # undefined symbol at link time (bugs/consolidated/
                    # COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md).
                    # Emit an actual (weak) definition instead, matching the
                    # existing "unavailable in compiled mode" convention
                    # _stub_only_modules above uses for the same situation.
                    #
                    # link_imports=True (driver.py's dylib-based link mode)
                    # is included here too, NOT just do_imports=True: reaching
                    # this branch under link_imports means _register_link_
                    # imports's own Phase 0 pre-pass (gen_module, which DOES
                    # resolve real dylib/reflection signatures when one
                    # exists) already looked at this exact name and could
                    # NOT find a 'signature' for it either — e.g. a function-
                    # scoped `from pkgutil import read_code` reaching a
                    # plain untyped Python function pulled in via module_
                    # loader's source-level fallback (no dylib, no type
                    # annotations to build a C signature from). Unlike the
                    # OLD `else` branch's "another sibling .o will define it
                    # later" assumption below (genuinely true for compile_
                    # stdlib.py's separately-compiled-.mojo-files workflow),
                    # link mode has no such other translation unit for a
                    # name Phase 0 already failed to resolve — the bare
                    # `extern` this used to fall through to left a real,
                    # unconditional undefined symbol at LINK time (confirmed
                    # via `Lib/runpy.py`'s `from pkgutil import read_code`/
                    # `get_importer` inside `_get_code_from_file`/`_run_path`
                    # — see bugs/hard/CODEGEN_function_scoped_import_call_
                    # unresolved_at_link.md). Routing link_imports through
                    # this same weak-stub path makes its behavior consistent
                    # with what a TOP-LEVEL import of the exact same
                    # unresolvable name already got for free (the separate,
                    # per-call-site `_is_unknown`/`_is_unknown_stmt` auto-
                    # stub mechanism in `_lower_named_call`/`_gen_stmt_
                    # ExprStmt` — never reached for the function-scoped case
                    # because `_gen_stmt_FromImportStmt` had already
                    # registered this name into `self.imported_symbols`,
                    # marking it "known" before the call site's own lowering
                    # ever ran its "is this genuinely unknown" check).
                    # Guard against re-emitting the SAME definition when
                    # another module elsewhere in this flattened program also
                    # imports the same never-resolved name (weak-symbol
                    # linkage doesn't help here - this is one definition
                    # showing up twice in one translation unit).
                    if safe in _emitted_unresolved_stub_syms:
                        continue
                    _emitted_unresolved_stub_syms.add(safe)
                    if ret_type == 'void':
                        body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
                    else:
                        body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
                    # Guard name MUST be the canonical `_MOJO_STUB_{NAME}`
                    # macro (not the bare `safe` symbol name) — this is the
                    # SAME real symbol a completely separate auto-stub
                    # mechanism (`_lower_named_call`'s/`_gen_stmt_ExprStmt`'s
                    # `_is_unknown`/`_is_unknown_stmt` call-site auto-stub,
                    # each per-`temp_gen`-instance, not deduped through the
                    # module-global `_emitted_unresolved_stub_syms` set this
                    # loop uses) can ALSO stub for the exact same unresolved
                    # name (e.g. `get_cache_token`, imported via `from abc
                    # import get_cache_token` in functools.py AND called at
                    # a use site) — that mechanism already guards its own
                    # emitted weak-definition text with `_MOJO_STUB_{NAME.
                    # upper()}` (see its own `_stub_guard`/`_stub_key`
                    # locals). Using a DIFFERENT guard string here (the bare
                    # symbol name) meant cpp's `#ifndef` never recognized
                    # the two occurrences as the same guard, so BOTH weak
                    # function definitions survived into the same
                    # translation unit — a real GCC "redefinition of X"
                    # error (found via Lib/weakref.py's transitive-closure
                    # build; confirmed via `get_cache_token`, doubly-stubbed
                    # once here and once at the call site inside functools.py
                    # — see bugs/CODEGEN_generator_function_Lib_weakref.md).
                    # Matching the guard convention makes whichever
                    # occurrence is textually first in the final .ci win,
                    # exactly like every other `_MOJO_STUB_*`-guarded stub
                    # in this file already relies on.
                    _unresolved_guard = _stub_guard_name(safe)
                    parts.append(f"#ifndef {_unresolved_guard}\n#define {_unresolved_guard}\n"
                                  f"__attribute__((weak)) {ret_type} {safe} (...) {body}  /* stub from {module} */\n#endif")
                else:
                    # do_imports=False AND link_imports=False (e.g.
                    # build_module.py / compile_stdlib.py's separately-
                    # compiled-.mojo-module workflow, NOT driver.py's dylib-
                    # based link mode — that's handled above now): sibling
                    # modules are compiled to their own .o and linked
                    # together afterward, so an unresolved-here name may
                    # legitimately be defined in one of those other
                    # translation units. Keep the historical bare-extern
                    # behavior — turning this into a stub would silently
                    # swallow real cross-module calls instead of linking to
                    # their real definition.
                    # Legacy format fallback: use pure variadic so callers can pass any args.
                    # GIMPLE mode treats () as "no params" (causing "too many args" errors),
                    # so we use (...) instead which accepts any number of arguments.
                    parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")

        if self.imported_symbols:
            parts.append('')

        # Note: user-defined functions (_hash, jit_compile_and_execute, etc.) must NOT
        # be pre-registered here with guessed signatures — they get forward declarations
        # generated from their actual definitions below, and pre-registering creates
        # conflicting type errors.

        # Forward declarations: free functions (skip main — handled specially)
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        if self._supported_generators or self._generator_method_api:
            # Milestone B (free functions) / Milestone C step 3 (struct
            # methods): the extern "C" API (opaque handle + start/resume/
            # value/destroy) for every supported generator in this module —
            # the ONLY forward declarations these functions get (they have
            # no ordinary -fgimple C body/prototype at all; see the Phase 2a
            # skip above, both the FunctionDef one and the StructDef-methods
            # one). One shared opaque MojoGenerator typedef covers every
            # generator regardless of its yielded-value type — see
            # _gen_cpp_generator_unit's docstring for why a bare
            # reinterpret_cast of the coroutine_handle's own address is
            # enough, no separate wrapper allocation needed. A generator
            # METHOD's `<base>_start` takes the enclosing struct's `{Name}
            # *` as its first parameter — the struct's own C typedef is
            # already emitted earlier in this same preamble (see the
            # struct-typedef emission above, well before this point), so the
            # type is already known here.
            parts.append('typedef struct MojoGenerator MojoGenerator;')
            for _api in list(self._generator_api.values()) + list(self._generator_method_api.values()):
                _base, _vct = _api['base'], _api['value_ctype']
                _gptypes = ', '.join(_api.get('params') or []) or 'void'
                parts.append(f"extern MojoGenerator *{_base}_start ({_gptypes});")
                parts.append(f"extern _Bool {_base}_resume (MojoGenerator *);")
                parts.append(f"extern {_vct} {_base}_value (MojoGenerator *);")
                parts.append(f"extern void {_base}_destroy (MojoGenerator *);")
            parts.append('')
        # `_coro_resume_fn`/`_coro_destroy_fn` (std.builtin.coroutine) used
        # as bare VALUES anywhere in this compile — even a module with NO
        # supported async function/closure of its OWN can still reference
        # them this way (e.g. std/runtime/asyncrt.mojo's `_async_execute`
        # generic, elaborated via monomorphize.py's own INDEPENDENT
        # GimpleGen instance per instantiation — a real, hand-verified
        # regression: that instance's `_funcptr_mojo_coro_resume_generic =
        # (void *)mojo_coro_resume_generic;` static initializer referenced
        # an undeclared symbol, since the header's inclusion was gated only
        # on this SAME instance's own _supported_async/_supported_async_
        # closures, which an elaborated fragment with no async function of
        # its own never populates) — so this must ALSO pull in the header,
        # independent of the `_supported_async`/`_supported_async_closures`/
        # `_nested_async_api` gate just below. NOTE: this gate's operands
        # are deliberately plain `len(...)` ints rather than bare container
        # truthiness — `bool(dictA or dictB or dictC or set_intersection)`
        # compiles the `or` chain to a boxed int64_t (the dict/set types
        # join to int64_t), and `bool(int64_t_holding_a_pointer)` compares
        # pointer-non-nullness, so three EMPTY dicts plus an empty
        # intersection still read as True — a native-vs-Python divergence
        # (Python `bool({})` is False; the self-hosted binary's was True).
        # Explicit lengths sidestep the boxing entirely.
        _needs_async_runtime_h = bool(
            len(self._supported_async) or len(self._supported_async_closures)
            or len(self._nested_async_api)
            or len(self._funcptr_builtins_needed
                  & {'mojo_coro_resume_generic', 'mojo_coro_destroy_generic'}))
        if _needs_async_runtime_h and not (self._supported_async or self._supported_async_closures
                                            or self._nested_async_api):
            parts.append('typedef struct MojoAsync MojoAsync;')
            parts.append('#include <mojo_async_runtime.h>')
            parts.append('')
        if self._supported_async or self._supported_async_closures or self._nested_async_api:
            # Step B: the extern "C" API (opaque handle + start/is_done/
            # value/destroy — no `_resume`, see _gen_cpp_async_unit's
            # docstring) for every supported async function in this module.
            # `_supported_async_closures` (device_context.mojo's nested
            # `async def wrapper(...) capturing -> None:` closures — see
            # gen_module's dedicated discovery pass) shares this exact same
            # extern "C" API shape, just keyed by (outer_ctx, inner_name)
            # instead of bare name, so it ALSO needs this preamble (the
            # `MojoAsync` opaque type + mojo_async_runtime.h) even when the
            # module has no genuinely TOP-LEVEL supported async function at
            # all — a name-only gate on _supported_async would silently
            # leave this file with implicit-declaration errors for
            # `_mojoasync_wrapper_start`/etc. instead.
            # A separate opaque `MojoAsync` type from `MojoGenerator` (not
            # reused) — matches _gen_cpp_async_unit's own promise_type being
            # a deliberately fresh, separate C++ type from the generator's;
            # keeping the C-side opaque pointer types distinct too means a
            # accidental cross-call (passing a MojoGenerator* where an
            # async handle is expected, or vice versa) is a real compile-
            # time type error here, not just a silent void*-shaped bug.
            # mojo_async_schedule_ready()/mojo_async_run_until_complete()
            # (Step A's own scheduler API, declared in mojo_async_runtime.h,
            # included just below) are called directly from the call-site
            # lowering in _lower_call — `MojoAsync *` converts to
            # mojo_async_schedule_ready's `void *` parameter implicitly in
            # C, no cast needed at the call site.
            parts.append('typedef struct MojoAsync MojoAsync;')
            parts.append('#include <mojo_async_runtime.h>')
            # Step I: nested async functions (self._nested_async_api,
            # qualified-key-only — see that dict's own docstring) get their
            # extern "C" declarations emitted here too, unconditionally,
            # alongside the top-level ones (self._async_api) — each has its
            # own already-unique, scope_prefix-qualified `base` (see
            # _gen_cpp_async_unit), so there is no name-collision risk in
            # emitting every nested unit's forward declarations regardless
            # of which one (if any) the module's own per-statement body
            # loop ends up actually calling into.
            for _api in list(self._async_api.values()) + list(self._nested_async_api.values()):
                _base, _vct = _api['base'], _api['value_ctype']
                _aptypes = ', '.join(_api.get('params') or []) or 'void'
                parts.append(f"extern MojoAsync *{_base}_start ({_aptypes});")
                parts.append(f"extern _Bool {_base}_is_done (MojoAsync *);")
                parts.append(f"extern {_vct} {_base}_value (MojoAsync *);")
                parts.append(f"extern void {_base}_destroy (MojoAsync *);")
                # Step E: the outermost-edge exception translation, called
                # ONLY from the `asyncio.run(...)` bridge below -- see
                # _gen_cpp_async_unit's own {base}_translate_pending_exc
                # docstring.
                parts.append(f"extern void {_base}_translate_pending_exc (MojoAsync *);")
            for _api in self._async_closure_api.values():
                _base, _vct = _api['base'], _api['value_ctype']
                _aptypes = ', '.join(_api.get('params') or []) or 'void'
                parts.append(f"extern MojoAsync *{_base}_start ({_aptypes});")
                parts.append(f"extern _Bool {_base}_is_done (MojoAsync *);")
                parts.append(f"extern {_vct} {_base}_value (MojoAsync *);")
                parts.append(f"extern void {_base}_destroy (MojoAsync *);")
                parts.append(f"extern void {_base}_translate_pending_exc (MojoAsync *);")
            parts.append('')
        for fn in func_defs:
            if fn.name == 'main':
                continue
            if (fn.name in self._supported_generators or fn.name in self._supported_async
                    or fn.name in self._supported_async_gen):
                continue
            if fn.name in self._unsupported_generator_names:
                # See _unsupported_generator_names's docstring — already has
                # its own `int64_t NAME (...);` stub declaration; do not ALSO
                # forward-declare it here with a second, differently-shaped
                # ordinary signature (a "conflicting types" compile error).
                continue
            ret    = self.func_return_types.get(fn.name, 'int64_t')
            # If any param is *args, the call convention uses a packed MojoList*
            has_varargs = any(pn.startswith('*') for pn, _ in (fn.params or []))
            if has_varargs:
                param_ctypes = self._signature_ctypes(fn.params, fn, sentinel='MojoList *')
                self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
                self._note_vararg_trailing_param_types(fn)
            else:
                param_ctypes = []
                inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
                for pn, pt in (fn.params or []):
                    if pn in inferred_params:
                        param_ctypes.append(inferred_params[pn])
                    else:
                        param_ctypes.append(self._param_ctype(pn, pt, fn))
                self.func_param_types[fn.name] = param_ctypes
            ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
            # For _C_RESERVED_FUNCS (e.g. getuid → mojo_getuid), use the renamed
            # C name as the guard so the original C name's util stub is not blocked.
            # _func_csym adds the overload suffix so this forward decl matches the
            # definition and call sites.
            _c_fn_name = self._func_csym(fn.name)
            _guard_name = _c_fn_name if fn.name in _C_RESERVED_FUNCS else fn.name
            stub_guard = _stub_guard_name(_guard_name)
            parts.append(f'#ifndef {stub_guard}')
            parts.append(f"{ret} {_c_fn_name} ({ptypes});")
            parts.append('#endif')

        # Forward declarations: struct methods
        # When do_imports=True, imported code is inlined and already contains its own
        # forward declarations — don't re-emit them with potentially stale types.
        struct_defs = [s for s in stmts if isinstance(s, StructDef)]
        if not self.do_imports:
            struct_defs += [s for s in (imported_stmts or []) if isinstance(s, StructDef)]
        for sd in struct_defs:
            # Overload-id per method, aligned with sd.methods — this used to
            # be a second, hand-rolled copy of _struct_method_overload_ids'
            # exact logic (a maintenance risk: the two copies could drift).
            # Calling the shared @staticmethod instead guarantees this loop's
            # forward-declared name always matches _gen_struct_method's own
            # emitted symbol.
            _moids = self._struct_method_overload_ids(sd)
            method_ids = {id(m): oid for m, oid in zip(sd.methods, _moids)}

            for m in sd.methods:
                if (sd.name, m.name) in self._supported_generator_methods:
                    # Milestone C step 3: no ordinary StructName_method(...)
                    # C function exists for this method at all — it has its
                    # own extern "C" <base>_start/_resume/_value/_destroy
                    # API instead (forward-declared separately, alongside
                    # the free-function generator API — see the
                    # `_generator_api`/`_generator_method_api` forward-decl
                    # block above). Emitting an ordinary forward declaration
                    # here would just be a harmless-looking but WRONG
                    # prototype for a symbol nothing defines or calls.
                    continue
                overload_suffix = method_ids.get(id(m), '')
                mangled_name = self._struct_method_csym(sd.name, m.name, overload_suffix)
                # Use per-overload key first; fall back to base name, then AST annotation
                ret = (self.func_return_types.get(f"{sd.name}_{m.name}{overload_suffix}")
                       or self.func_return_types.get(f"{sd.name}_{m.name}")
                       or self._resolve_type(m.return_type))
                method_full_name = f"{sd.name}_{m.name}"
                # Prefer param types stored during definition generation (exact match)
                per_overload_params = self.func_param_types.get(mangled_name)
                if per_overload_params is not None:
                    param_ctypes = per_overload_params
                elif any(pn.startswith('*') for pn, _ in (m.params or [])):
                    # *args method: fixed params (+ self) + MojoList*; **kwargs -> MojoDict*
                    param_ctypes = self._signature_ctypes(m.params, m, sd.name, sentinel='MojoList *')
                    self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, sd.name)
                else:
                    param_ctypes = []
                    for i, (pname, ptype) in enumerate(m.params):
                        if pname.startswith('**'):
                            continue  # skip **kwargs
                        if pname == 'self':
                            ct = f"{sd.name} *"
                        elif ptype is None and hasattr(self, '_inferred_param_types'):
                            if method_full_name in self._inferred_param_types and pname in self._inferred_param_types[method_full_name]:
                                ct = self._inferred_param_types[method_full_name][pname]
                            else:
                                ct = 'int64_t'
                        else:
                            ct = self._resolve_type(ptype)
                        param_ctypes.append(ct)
                ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
                parts.append(f"{ret} {mangled_name} ({ptypes});")

            # For overloaded methods, also emit a catch-all base-name decl so that
            # call sites that use the unmangled name (e.g. Slice___init__) don't fail
            # with "implicit declaration of function". Qualified the same way the
            # real per-overload decls above are, so it's declaring the same
            # (home-module-prefixed) symbol namespace, not a stray unqualified one.
            _emitted_base: set[str] = set()
            for m in sd.methods:
                if method_ids.get(id(m), ''):  # has an overload suffix
                    base_cname = self._struct_method_csym(sd.name, m.name, '')
                    if base_cname not in _emitted_base:
                        base_ret = (self.func_return_types.get(f"{sd.name}_{m.name}")
                                    or self._resolve_type(m.return_type))
                        parts.append(f"{base_ret} {base_cname} (...);")
                        _emitted_base.add(base_cname)

        if func_defs or struct_defs:
            parts.append('')

        # Forward decls for cross-module struct methods that may be called —
        # but ONLY for self-hosting compiles (see `_is_selfhost_file` above
        # and BUG-2026-014): these reference gimple_codegen's OWN bootstrap
        # `Parser`/`Interpreter` classes (e.g. Parser_parse_module from
        # mojo_compiler, Interpreter from myinterpreter), whose typedef is
        # only emitted when struct_field_types['Parser'/'Interpreter'] was
        # seeded by that same self-host-only gate. Emitting these
        # unconditionally for an external project with its own same-named
        # (and differently-shaped) Parser/Interpreter struct is exactly the
        # kind of leak that gate exists to prevent — the prototypes below
        # would either reference a type gcc never saw a typedef for
        # ("unknown type name 'Interpreter'") or, worse, silently collide
        # with the external struct's OWN typedef.
        if _is_selfhost_file:
            parts.append("MojoList * Parser_parse_module (Parser *);")
            parts.append("void Parser___init__ (Parser *, MojoList *);")
            parts.append("void Interpreter___init__ (Interpreter *, char *, MojoList *);")
            parts.append("int64_t Interpreter_execute (Interpreter *, int64_t);")
            parts.append("_Bool jit_compile_and_execute (char *, char *, int64_t, int64_t, int64_t);  /* from mojo.py */")
        # Forward decls for the generic reflection dispatch (see the
        # "Generic reflection dispatch" block emitted earlier in this same
        # gen_module call, near the struct alloc helpers) — that block's
        # full definitions land textually AFTER function bodies compiled in
        # an earlier phase (e.g. ast_rewriter.py's _ast_eq/_rewrite_node
        # calling dataclasses.fields()/getattr()/setattr()), so without a
        # declaration visible before those call sites, GCC treats the call
        # as an implicit (and wrong-typed) int-returning declaration.
        parts.append("static int64_t _mojo_dispatch_getattr (void *, char *);")
        parts.append("static void _mojo_dispatch_setattr (void *, char *, int64_t);")
        parts.append("static MojoList * _mojo_dispatch_fields (void *);")
        if self._asdict_dispatch_needed:  # see that flag's own declaration
            parts.append("static MojoDict * _mojo_dispatch_asdict (void *);")
        parts.append("static int _mojo_dispatch_is_dataclass (void *);")
        parts.append("static char * _mojo_dispatch_repr (void *);")
        parts.append("static char * _mojo_repr_list (MojoList *);")
        parts.append("static char * _mojo_repr_dict (MojoDict *);")
        parts.append("static char * _mojo_generic_elem_repr (int64_t);")
        if _emitted_type_name_emitted:
            parts.append("static char * _mojo_type_name (int64_t);")
        parts.append('')

        # Forward declarations for lifted closures + env allocator helpers
        # For imported modules (emit_struct_defs=False), emit closure env struct typedefs here
        # (main module emits them inside the emit_struct_defs block above)
        if not self.emit_struct_defs:
            for inner_map in self._all_closures.values():
                for ci in inner_map.values():
                    if ci.env_struct and ci.env_struct not in self._emitted_structs:
                        parts.append(f"typedef struct {ci.env_struct} {{")
                        for vname, vtype in ci.captures:
                            # A mutably-captured (`{mut}`-spec) name gets a
                            # pointer field instead of a value copy -- see
                            # ClosureInfo.mut_names.
                            field_ctype = f"{vtype} *" if vname in ci.mut_names else vtype
                            parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                        parts.append(f"}} {ci.env_struct};")
                        parts.append('')
                        self._emitted_structs.add(ci.env_struct)
        for outer_name, inner_map in self._all_closures.items():
            for inner_name, ci in inner_map.items():
                if ci.env_struct:
                    alloc_fn = f"_alloc_{ci.env_struct}"
                    parts.append(f"{ci.env_struct} * {alloc_fn} (void);")
                # Use cached types from Phase 2a if available (more accurate)
                ret  = ci.inferred_ret if ci.inferred_ret else self.func_return_types.get(ci.lifted_name, 'int64_t')
                if ci.is_re_sub_callback:
                    ret = 'char *'
                node = ci.inner_def
                ptypes_list = []
                if ci.env_struct:
                    ptypes_list.append(f"{ci.env_struct} *")
                for i, (pn, pt) in enumerate(node.params):
                    if ci.is_re_sub_callback and i == 0:
                        ptypes_list.append('char *')
                    elif pn in ci.inferred_params:
                        ptypes_list.append(ci.inferred_params[pn])
                    else:
                        ptypes_list.append(self._param_ctype(pn, pt, node))
                ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
                parts.append(f"{ret} {ci.lifted_name} ({ptypes});")
                # Emit static void* pointer for re.sub callback (avoids &func in GIMPLE)
                if ci.is_re_sub_callback:
                    static_name = f"_mojo_cb_{ci.lifted_name}"
                    # Regular C (not GIMPLE): valid function→void* assignment
                    parts.append(f"static void * {static_name} = (void *){ci.lifted_name};")
        if self._all_closures:
            parts.append('')

        # ── Static function pointer vars for builtins (avoids &func in GIMPLE) ──
        # `_funcptr_builtins_needed`/`_emitted_funcptr_builtins` are shared across
        # every _compile_imported_module temp_gen for the same reason
        # _emitted_ptr_helpers/_emitted_structs are: all modules' generated code
        # is textually concatenated into one translation unit for the self-hosted
        # build, so declaring the SAME `static void * _funcptr_X` twice (once per
        # module that happens to reference builtin X as a bare value) is a real
        # gcc redefinition error, not just wasted output — skip any name this run
        # (or an earlier sub-gen sharing the same sets) already emitted.
        if self._funcptr_builtins_needed:
            _new_names = sorted(self._funcptr_builtins_needed - self._emitted_funcptr_builtins)
            if _new_names:
                for c_name in _new_names:
                    # Sanitize name to be valid C identifier (skip casts like ((int)0))
                    if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                        parts.append(f"static void * _funcptr_{c_name} = (void *){c_name};")
                    self._emitted_funcptr_builtins.add(c_name)
                parts.append('')

        # ── Dispatch table initializations (from Phase C) ──────────────────
        # Emit static const initializations for all planned dispatch tables
        # Only for main module (same as dispatch solving)
        if self.emit_struct_defs and self._dispatch_solver and self._dispatch_tables:
            parts.append("/* Dispatch table initializations (virtual method tables) */")
            for callee_set, dispatch_table in self._dispatch_tables.items():
                if dispatch_table.name not in self._emitted_dispatch_tables:
                    table_init = dispatch_table.emit_table_init()
                    if table_init:
                        parts.append(table_init)
                        self._emitted_dispatch_tables.add(dispatch_table.name)
            parts.append('')

        # Function bodies (generated in Phase 2a)
        # Collect string literals from all GimpleGen instances used in Phase 2a
        # and emit them as true global char arrays (required by GIMPLE strict mode)
        str_pool: dict = {}
        for attr in dir(self):
            pass  # self is the GimpleGenModule-level object, not per-function gen
        # Gather _str_pool from all lowering contexts (stored on the module gen)
        if hasattr(self, '_str_pool') and self._str_pool:
            parts.append("/* String literal globals — array form so address is a compile-time r-value (required by GIMPLE strict mode) */")
            if self.emit_str_pool:
                # String pool symbols are TU-local; static avoids duplicate-symbol
                # errors when multiple modules are compiled into the same dylib.
                # Use char* (pointer) not char[] (array): assigning a char[] to a
                # char* temp inside __GIMPLE functions triggers a GCC ICE in convert_move.
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'static char * {sname} = "{escaped}";')
            else:
                # Imported module: emit tentative (uninitialised) declarations.
                # C allows multiple `static T foo;` tentative definitions in one TU;
                # the main module's full `static T foo = "..."` definition wins.
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'static char * {sname};')
            parts.append('')
        # Compile-time-known regex program data (see regex_compile.py,
        # _gen_for_regex_iter, BACKLOG-CODEGEN.md §4f) — one prog/ranges/
        # classinfo/names array set per distinct pattern actually used via
        # `.finditer()`, populated during Phase 2a body generation above.
        # self._regex_progs is a dict SHARED across every recursively-compiled
        # submodule's own GimpleGen instance (see _compile_imported_module),
        # same as _str_pool. Unlike a scalar, these are `static const ARRAY[]
        # = {...}` with a full initializer — C doesn't allow repeating that as
        # a tentative definition the way _str_pool's imported-module branch
        # does for `static char *`. A module can be reached (and therefore
        # have its own gen_module() run this same final-assembly code) via
        # more than one do_imports path (e.g. mojo_compiler.py compiled
        # directly AND via gimple_codegen.py's own `import mojo_compiler`),
        # and the submodule that actually POPULATES an entry (compiling its
        # own .finditer() call in ITS Phase 2a) is also the only one whose
        # own func_parts (right after this point, in ITS OWN returned code
        # string) ever reference it — so gate on "not yet emitted anywhere"
        # (self._regex_progs_defined, shared the same way) rather than on
        # emit_str_pool/root-ness, so it lands in the right submodule's own
        # output, before that submodule's own use of it.
        _regex_new = {p: i for p, i in self._regex_progs.items() if p not in self._regex_progs_defined}
        if _regex_new:
            parts.append("/* Compile-time-compiled regex programs (finditer support) */")
            for pattern, info in _regex_new.items():
                parts.append(info['decls'])
                self._regex_progs_defined.add(pattern)
            parts.append('')
        # Also collect from func_parts generators (they share self._str_pool via gen_func)
        parts.extend(func_parts)

        # Emit class-level attribute initializer (plain C, not GIMPLE; main module only)
        if self.emit_struct_defs:
            class_attr_inits = getattr(self, '_class_attr_inits', [])
            parts.append("static void _mojo_classattr_init (void)")
            parts.append("{")
            if class_attr_inits:
                parts.extend(class_attr_inits)
            parts.append("}")
            parts.append('')

        if self._generator_cpp_units:
            cpp_parts = [
                '/* Generated by gimple_codegen.py (Milestone B: C++20-coroutine',
                '   translation of this module\'s supported generator function(s);',
                '   Milestone C step 2 added `yield from`-delegation support;',
                '   Milestone C step 3 added generator METHODS on structs;',
                '   Milestone D added try/except/raise support;',
                '   Step B (async/await project) added compiled `async def`',
                '   functions -- a separate promise_type/extern "C" API from the',
                '   generator one above, deliberately not sharing a promise shape',
                '   -- see GimpleGen._gen_cpp_async_unit\'s docstring) */',
                '#include <coroutine>',
                '#include <cstdint>',
                '#include <cstdio>',
                '#include <cmath>',
                '#include <exception>',
                '#include <functional>',
                '#include <vector>',
                '#include <algorithm>',
                '#include <mojo_runtime.h>',
                '',
                'extern "C" { typedef struct MojoGenerator MojoGenerator; }',
                'extern "C" { typedef struct MojoAsync MojoAsync; }',
                '',
                '/* Milestone D: RAII `finally:` translation (see',
                '   GimpleGen._cpp_try_stmt) -- runs an arbitrary capturing',
                '   lambda from its destructor, so it fires on every way its',
                '   enclosing scope can be exited (normal fallthrough, break/',
                '   continue, co_return, an exception unwinding through/past it,',
                '   or -- same C++20 coroutine-frame-destruction rule as',
                '   `_mojogen_sub_guard` below -- this coroutine being destroyed',
                '   early while suspended inside the guarded scope). A capturing',
                '   lambda (not a local class) specifically: a local class\'s own',
                '   member functions have NO implicit access to the enclosing',
                '   function\'s locals, so a finally body referencing an outer',
                '   variable wouldn\'t compile with that approach. */',
                'struct _MojoScopeExit {',
                '    std::function<void()> fn;',
                '    explicit _MojoScopeExit(std::function<void()> f) : fn(std::move(f)) {}',
                '    ~_MojoScopeExit() { fn(); }',
                '};',
                '',
                '/* Milestone D: a Mojo exception thrown as a real C++ exception,',
                '   confined to this coroutine\'s own .cpp translation unit (see',
                '   GimpleGen._cpp_raise_stmt/_cpp_try_stmt). Carries exactly the',
                '   same tri-part representation the ordinary (non-generator) GIMPLE',
                '   path already uses for its mojo_exc_type/msg/obj globals (see',
                '   mojo_runtime.h) -- reused, not reinvented, so the extern "C"',
                '   `_resume` boundary below can translate one directly into the',
                '   other with no lossy conversion. */',
                'struct _MojoCppExc {',
                '    int64_t type_id;',
                '    char *msg;',
                '    void *obj;',
                '};',
                '',
                '/* RAII guard for a sub-generator a `yield from` delegates to (see',
                '   GimpleGen._cpp_yield_from) -- guarantees the sub-generator\'s own',
                '   `_destroy` runs exactly once, whether this scope exits because the',
                '   sub-generator was exhausted normally or because the OUTER coroutine',
                '   holding it is itself destroyed early (e.g. a consumer `break`s out',
                '   of the loop that\'s driving it): C++20 destroys every local object',
                '   in scope at a coroutine\'s suspension point when that coroutine\'s',
                '   frame is destroyed, exactly as if the enclosing block unwound',
                '   normally, so this destructor fires correctly in both cases with no',
                '   special-case code at either call site. Emitted unconditionally',
                '   whenever this module has ANY compiled generator -- harmless and',
                '   unused if none of them actually use `yield from`. */',
                'struct _mojogen_sub_guard {',
                '    MojoGenerator *g;',
                '    void (*destroy_fn)(MojoGenerator *);',
                '    ~_mojogen_sub_guard() { if (g) destroy_fn(g); }',
                '};',
                '',
            ]
            if (self._supported_async or self._supported_async_gen
                    or self._supported_async_closures or self._nested_async_api):
                # Step C (compiled-path async/await codegen project): this
                # module has at least one compiled `async def` that
                # actually uses `await asyncio.sleep(...)` (or could —
                # emitted unconditionally whenever ANY async function
                # compiled, harmless/unused otherwise, same convention as
                # `_mojogen_sub_guard` just above). `_mojoasync_
                # SleepAwaiter` is a real C++20 awaiter that arms Step A's
                # timer queue (mojo_async_schedule_timer, declared in
                # mojo_async_runtime.h) and genuinely suspends the awaiting
                # coroutine until the timer fires -- field-for-field the
                # same shape as the hand-written `SleepAwaiter` Step A's
                # own test_async_runtime_scaffold.py already proved works
                # end-to-end (see that file's HAND_WRITTEN_MAIN_CPP),
                # reused here as the one real, codegen-emitted awaiter
                # instead of inventing a second, parallel shape (see
                # CLAUDE.md: consolidate, don't duplicate). Emitted by
                # GimpleGen._cpp_stmt's own AwaitExpr case (see there for
                # the ns-conversion + co_await emission).
                cpp_parts.append('#include <mojo_async_runtime.h>')
                cpp_parts.append('#include <unistd.h>')
                cpp_parts.append('')
                cpp_parts.append('struct _mojoasync_SleepAwaiter {')
                cpp_parts.append('    uint64_t delay_ns;')
                cpp_parts.append('    bool await_ready() const { return false; }')
                cpp_parts.append('    void await_suspend(std::coroutine_handle<> h) const {')
                cpp_parts.append('        mojo_async_schedule_timer(h.address(), mojo_async_now_ns() + delay_ns);')
                cpp_parts.append('    }')
                cpp_parts.append('    void await_resume() const {}')
                cpp_parts.append('};')
                cpp_parts.append('')
                # Step F (compiled-path async/await codegen project): the
                # ONE real-socket-I/O awaiter this step adds, for `await
                # asyncio.sock_recv(<fd>)` (see _is_asyncio_sock_recv_call's
                # docstring for the API-shape rationale). Reuses Step A's
                # kqueue reactor EXACTLY as it already is
                # (mojo_async_register_read, declared in
                # mojo_async_runtime.h) -- this awaiter is a thin codegen-
                # emitted wrapper around it, not a reimplementation, mirroring
                # `_mojoasync_SleepAwaiter`'s own relationship to Step A's
                # timer queue exactly. `await_ready()` is unconditionally
                # false (same as SleepAwaiter) -- even when `fd` already has
                # data available BEFORE this await runs, kqueue's EV_ADD
                # registration reports an already-ready fd as ready on the
                # very next kevent() call (standard kqueue semantics, no
                # special-cased "check first" logic needed here), so the
                # "already readable" case still correctly resumes on the
                # very next scheduler turn instead of blocking -- see this
                # step's own test for an explicit timing assertion proving
                # that path resumes near-instantly rather than waiting on
                # some later, unrelated event.
                #
                # `await_suspend` only REGISTERS interest and returns to the
                # scheduler -- per the standard reactor pattern (and this
                # project's own Step A design doc), the reactor only tells
                # you WHEN a fd becomes readable, never IF a subsequent
                # read will fully succeed, so the actual `read(2)` syscall
                # happens here, in `await_resume`, once the coroutine has
                # genuinely been resumed by the reactor reporting readiness.
                # Fixed at exactly 1 byte (see _is_asyncio_sock_recv_call's
                # docstring: the smallest useful real transfer for this
                # step's narrow scope) -- a real multi-byte, short-read-safe
                # `nbytes`-parameterized read (looping until `nbytes` bytes
                # are collected, or building a proper buffer/String result
                # type to carry more than one scalar byte across this
                # codegen's still-scalar-only value boundary) is explicitly
                # NOT built here; a short/partial transfer for MORE than one
                # byte is a real possibility future work would need to
                # handle, noted here rather than silently glossed over.
                # Returns int64_t: the byte value read (0-255) on success,
                # -1 on a clean EOF (peer closed / recv() returned 0), or -2
                # on an actual read() error (recv() returned -1) -- three
                # results a single scalar int64_t can distinguish without
                # needing errno plumbed across this boundary too.
                cpp_parts.append('struct _mojoasync_SockRecvAwaiter {')
                cpp_parts.append('    int fd;')
                cpp_parts.append('    bool await_ready() const { return false; }')
                cpp_parts.append('    void await_suspend(std::coroutine_handle<> h) const {')
                cpp_parts.append('        mojo_async_register_read(fd, h.address());')
                cpp_parts.append('    }')
                cpp_parts.append('    int64_t await_resume() const {')
                cpp_parts.append('        unsigned char c;')
                cpp_parts.append('        ssize_t n = ::read(fd, &c, 1);')
                cpp_parts.append('        if (n == 1) return (int64_t)c;')
                cpp_parts.append('        if (n == 0) return (int64_t)-1;')
                cpp_parts.append('        return (int64_t)-2;')
                cpp_parts.append('    }')
                cpp_parts.append('};')
                cpp_parts.append('')
            if (self._supported_generator_methods or self._cpp_param_struct_names
                    or self._cpp_ctor_struct_names or self._cpp_value_struct_names):
                # Milestone C step 3: every struct a compiled generator
                # METHOD in this module binds `self` to needs its C layout
                # visible here too (for `self->field` access and for the
                # `self` parameter's own pointer type) — the EXACT same
                # typedef text the .c/.ci output got (see
                # self._struct_typedef_texts' docstring), not a
                # independently-derived copy, so gcc and g++ agree on the
                # struct's layout byte-for-byte. `_cpp_param_struct_names`
                # (bugs/hard/CODEGEN_generator_struct_typed_param_refused.md)
                # is the identical need for a struct accepted as a
                # generator/async function's own PARAMETER type, not just
                # via `self`; `_cpp_ctor_struct_names` is the same need for
                # a struct CONSTRUCTED inside the body (test_doctest.py's
                # `hook = TestHook(pathdir)`) — merged into the same
                # typedef-emission loop below rather than a separate one.
                cpp_parts.append('/* Struct layout(s) needed by this module\'s')
                cpp_parts.append('   compiled generator method(s) -- verbatim copy of')
                cpp_parts.append('   the same typedef(s) emitted into the .c/.ci output. */')
                # Comprehension variable names deliberately avoid the very
                # common `sn`/`_` — gen_module is one gigantic method that
                # this project's OWN self-hosting compiler flattens into a
                # single flat C function (every local across the whole
                # method shares one C declaration namespace by name), and
                # both those names are already used elsewhere in gen_module
                # with a different inferred C type (`sn` as int64_t, `_` as
                # int64_t) — reusing them here as char*/tuple-unpack targets
                # produced real "conflicting types for 'sn'"/"for '_'" GCC
                # errors under `make check-selfhost`, confirmed and fixed by
                # this rename (see CLAUDE.md's self-host quality gate).
                # Plain for-loop building a plain list (not a set/dict-key-
                # tuple-unpacking comprehension) — see the analogous rename/
                # rewrite a little further up (`_gen_only_names`/etc.) for
                # why: this project's self-hosting compiler mis-typed a
                # near-identical comprehension shape here too (confirmed via
                # `make check-selfhost`), so the same defensive plain-loop
                # style is used for consistency, not just to fix one spot.
                _gm_struct_names_seen: list = []
                for _gm_struct_method_key in self._supported_generator_methods:
                    _gm_sname2 = _gm_struct_method_key[0]
                    if _gm_sname2 not in _gm_struct_names_seen:
                        _gm_struct_names_seen.append(_gm_sname2)
                for _gm_sname3 in self._cpp_param_struct_names:
                    if _gm_sname3 not in _gm_struct_names_seen:
                        _gm_struct_names_seen.append(_gm_sname3)
                for _gm_sname4 in self._cpp_ctor_struct_names:
                    if _gm_sname4 not in _gm_struct_names_seen:
                        _gm_struct_names_seen.append(_gm_sname4)
                for _gm_sname5 in self._cpp_value_struct_names:
                    if _gm_sname5 not in _gm_struct_names_seen:
                        _gm_struct_names_seen.append(_gm_sname5)
                # Transitive closure over struct-pointer-typed FIELDS: a
                # struct pulled in above (test_doctest.py's `TestHook`) can
                # itself have a field typed as ANOTHER struct pointer
                # (`self.importer = TestImporter()` — a plain, no-`var`-
                # annotation instance attribute, so struct_field_types
                # infers its real constructed type, `TestImporter *`, same
                # as any other field) — that struct's own typedef needs to
                # be visible in this .cpp TU too, or the outer struct's
                # field declaration itself fails to compile ("'TestImporter'
                # does not name a type"). BFS rather than one flat pass:
                # the pulled-in struct can itself reference a THIRD struct
                # the same way, arbitrarily deep.
                _gm_frontier = list(_gm_struct_names_seen)
                while _gm_frontier:
                    _gm_cur = _gm_frontier.pop()
                    for _gm_fct in self.struct_field_types.get(_gm_cur, {}).values():
                        if isinstance(_gm_fct, str) and _gm_fct.endswith(' *'):
                            _gm_fld_sn = _gm_fct[:-2]
                            if (_gm_fld_sn in self.struct_field_types
                                    and _gm_fld_sn not in _gm_struct_names_seen):
                                _gm_struct_names_seen.append(_gm_fld_sn)
                                _gm_frontier.append(_gm_fld_sn)
                # Forward-declare every struct tag in this closure BEFORE
                # any of their full typedefs below — `sorted()` order
                # (alphabetical, e.g. "TestHook" before "TestImporter")
                # doesn't necessarily match the dependency order a pointer
                # FIELD needs (TestHook's own typedef, emitted first
                # alphabetically, has a `TestImporter *importer;` field —
                # C++ requires `TestImporter` to at least name a type by
                # that point). A plain forward `struct Name;` ahead of time
                # (legal C++, later redefined by the real `typedef struct
                # Name {...} Name;`) sidesteps needing real dependency-
                # order sorting entirely.
                for _gm_fwd_sn in sorted(_gm_struct_names_seen):
                    if _gm_fwd_sn in self._struct_typedef_texts:
                        cpp_parts.append(f'struct {_gm_fwd_sn};')
                if any(_fwd in self._struct_typedef_texts for _fwd in _gm_struct_names_seen):
                    cpp_parts.append('')
                for _gm_method_struct_name in sorted(_gm_struct_names_seen):
                    _td = self._struct_typedef_texts.get(_gm_method_struct_name)
                    if _td:
                        # `_Bool` is a valid C99 type but NOT a valid C++
                        # type name (`bool` is) — the .ci side keeps `_Bool`
                        # (it genuinely is C); this .cpp copy must spell it
                        # `bool` (ABI-identical, 1 byte, same representation).
                        # The struct's own field types can legitimately be
                        # `_Bool` because the same typedef is emitted into the
                        # .ci/.c output (see the `_struct_typedef_texts`
                        # docstring's "verbatim copy" comment above — that
                        # verbatim-ness is about the SHAPE of the struct, not
                        # this one type-name spelling, which must differ per
                        # language exactly like _c_to_cpp_scalar_type already
                        # does for every other `_Bool` in the .cpp text).
                        cpp_parts.append(_td.replace('_Bool', 'bool'))
                        cpp_parts.append('')
            # Module-level symbols referenced by compiled generator bodies
            # (see _cpp_expr's IdentExpr/CallExpr resolution): module globals
            # need the module globals-struct typedef + extern instance (read
            # as `_{module}_globals.<name>`), module functions need their
            # mangled-C-symbol extern declaration — both in THIS .cpp TU,
            # since it's compiled standalone and linked against the .ci's
            # object (the generator body can't see the .c side's own
            # declarations). Emission is opportunistic: a referenced name
            # that isn't actually a known module global/function is skipped
            # silently (the generator-body emitter only ever records a name
            # it already confirmed exists in the corresponding dict).
            if self._cpp_module_global_refs or self._cpp_module_func_refs:
                cpp_parts.append('/* Extern declarations for module-level symbols')
                cpp_parts.append('   referenced by this module\'s compiled generator')
                cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
                # Plain loops, NOT a set-comprehension with tuple-unpacking
                # (`{m for m, _ in ...}`): this project's OWN self-hosting
                # compiler has no clean translation of that shape — it
                # lowered it to a GIMPLE `int64_t m, _;` multi-declaration
                # that collided with gen_module's own `_` declarations
                # ("redeclaration of '_' with no linkage", caught by
                # `make check-selfhost`). See the identical note a few
                # hundred lines up in gen_module for the same class of bug.
                _mref_modules: list = []
                for _mref_pair in self._cpp_module_global_refs:
                    _mref_mod = _mref_pair[0]
                    if _mref_mod not in _mref_modules:
                        _mref_modules.append(_mref_mod)
                for _mref_safe_mod in sorted(_mref_modules):
                    _mt = f"_{_mref_safe_mod}_toplev"
                    _mg = f"_{_mref_safe_mod}_globals"
                    # The full struct typedef (field-by-field, matching the
                    # .ci side's own globals struct — see Phase 1.7/2b's
                    # `_module_globals` emission) so field reads like
                    # `_root_globals.sys` compile; a forward-declared struct
                    # alone would leave the instance incomplete. Field names
                    # that are valid in C but are C++ keywords (`operator`,
                    # `new`, ...) are escaped `_kw_<name>` — the .ci side can
                    # keep the raw name (it genuinely is C), this .cpp copy
                    # cannot (see the `_Bool`→`bool` spelling fix above: the
                    # struct SHAPE is identical, only C++-invalid spellings
                    # differ).
                    cpp_parts.append(f'typedef struct {_mt} {{')
                    for _gl in self._module_globals.get(
                            'root' if _mref_safe_mod == 'root' else _mref_safe_mod, []):
                        _gct = _gl[1].replace('_Bool', 'bool')
                        _gfname = _c_field_name(_gl[0])
                        if _gfname in _CPP_KEYWORD_FIELDS:
                            _gfname = f"_kw_{_gfname}"
                        cpp_parts.append(f'  {_gct} {_gfname};')
                    cpp_parts.append(f'}} {_mt};')
                    cpp_parts.append(f'extern struct {_mt} {_mg};')
                for _fname in sorted(self._cpp_module_func_refs):
                    try:
                        _fsym = self._func_csym(_fname)
                        _fret = self.func_return_types.get(_fname, 'int64_t')
                        _fparams = self.func_param_types.get(_fname, [])
                        _fret_cpp = _fret.replace('_Bool', 'bool')
                        _fparam_str = ', '.join(
                            p if p not in ('_Bool',) else 'bool' for p in _fparams)
                        cpp_parts.append(
                            f'extern "C" {_fret_cpp} {_fsym} '
                            f'({_fparam_str});')
                    except Exception:
                        continue
                # Unmangled module-level functions (os.py's fspath): the .ci
                # declares them `int64_t <name> (...);` — mirror that exact
                # variadic extern in the .cpp so a generator body calling
                # `fspath(top)` compiles (calls go through the same variadic
                # symbol, ABI-identical to the .ci side's own extern).
                for _vfn in sorted(self._cpp_module_variadic_func_refs):
                    cpp_parts.append(f'extern "C" int64_t {_vfn} (...);')
                cpp_parts.append('')
            if self._cpp_class_attr_refs:
                # Class-level-attribute globals read via `cls.<attr>` in a
                # compiled @classmethod generator body (`_cpp_expr`'s
                # MemberExpr `cls.<attr>` case / `self._cpp_class_attr_
                # refs`) — declared extern here for the SAME "standalone
                # .cpp TU" reason as the module-global refs just above:
                # the real C variable is DEFINED once in the .c/.ci side
                # (`_gen_toplevel`'s "Global variable declarations" pass,
                # which seeds every `self._class_attrs[...]` mangled name
                # into `self._global_var_types` at Phase-1-ish time — see
                # that class-attr-collection pre-pass's own comment), never
                # in this .cpp TU. Uses the SAME real (non-int64_t-boxed)
                # pointer-ish C type that pass gives a container-valued
                # class attribute (`MojoDict *`/`MojoList *`/`MojoSet *`/
                # `char *`) — `self._global_var_types` (not `_global_c_
                # decl_types`, which is only ever populated for OTHER
                # kinds of globals, never for this mangled `_classattr_`
                # name) is already that class attr's authoritative
                # declared type; a class attr this codegen doesn't
                # recognize as a container/scalar type defaults to
                # `int64_t`, matching the .c side's own identical default
                # for an unrecognized global.
                cpp_parts.append('/* Extern declarations for class-level')
                cpp_parts.append('   attribute globals (`cls.<attr>`) read by this')
                cpp_parts.append('   module\'s compiled generator bodies. */')
                for _cattr_gname in sorted(self._cpp_class_attr_refs):
                    _cattr_ctype = self._global_var_types.get(_cattr_gname, 'int64_t')
                    _cattr_ctype = _cattr_ctype.replace('_Bool', 'bool')
                    cpp_parts.append(f'extern {_cattr_ctype} {_cattr_gname};')
                cpp_parts.append('')
            if self._cpp_struct_method_refs:
                # Struct methods called from a compiled generator/async body
                # on `self` or a non-self struct-pointer-typed local (see
                # _cpp_struct_method_refs' own declaration comment and
                # bugs/hard/CODEGEN_generator_struct_typed_param_refused.md)
                # — declared extern "C" here exactly like a free function's
                # own declaration just above, using the SAME mangled-symbol/
                # signature lookup _struct_method_csym already populates for
                # the ordinary (non-generator) GIMPLE-compiled method.
                cpp_parts.append('/* Extern declarations for struct methods')
                cpp_parts.append('   called from this module\'s compiled generator')
                cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
                for _sm_struct, _sm_method in sorted(self._cpp_struct_method_refs):
                    try:
                        _smsym = self._struct_method_csym(_sm_struct, _sm_method, '')
                        _smkey = f"{_sm_struct}_{_safe_name(_sm_method)}"
                        _smret = self.func_return_types.get(
                            _smsym, self.func_return_types.get(_smkey, 'int64_t'))
                        _smparams = self.func_param_types.get(
                            _smsym, self.func_param_types.get(_smkey, [f"{_sm_struct} *"]))
                        _smret_cpp = _smret.replace('_Bool', 'bool')
                        _smparam_str = ', '.join(
                            p if p != '_Bool' else 'bool' for p in _smparams)
                        cpp_parts.append(
                            f'extern "C" {_smret_cpp} {_smsym} ({_smparam_str});')
                    except Exception:
                        continue
                cpp_parts.append('')
            for unit in self._generator_cpp_units:
                cpp_parts.append(unit)
                cpp_parts.append('')
            self.generated_cpp = '\n'.join(cpp_parts)

        return self._dedup_variadic_externs(parts)

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
    def _struct_method_csym(self, struct_name: str, method_name: str, overload_id: str) -> str:
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
    def _infer_return_elem_type(self, body, func_def=None) -> str | None:
        return grsl._infer_return_elem_type(self, body, func_def=func_def)
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
