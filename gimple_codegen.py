"""GIMPLE backend for the Mojo compiler.

Consumes AST produced by fire_compiler.py and emits C source with
__GIMPLE-annotated functions for gcc-mp-15 -fgimple.
"""
from __future__ import annotations

import os
import re
import sys
import hashlib
import dataclasses

from fire_compiler import (
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
    GlobalStmt, NonlocalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    py_tokenize, Parser, _as_str, _as_structdef_node, _as_funcdef_node,
    desugar_genexps, DESUGARED_GENEXP_NAMES,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import ownership_check
import mlir
import mojo.middle.coro as gimple_gen_coro
import regex_compile
from generated_dispatch import (
    _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT,
    _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS,
    _STMT_DISPATCH, _EXPR_DISPATCH,

)
# Dedup for the `_mojo_type_name` tag→name table (`static char *
# _mojo_type_name`, must appear exactly once in the flattened closure's
# single TU) now lives in `GimpleGen._emitted_singletons` under the
# 'type_name_table' key — a per-`gen` set shared by ref into every nested
# temp_gen (auto-reset each compile since each `_run_pipeline` builds a
# fresh `gen`). The old module-level bool couldn't be read/written
# cross-module in the compiled compile_to_gimple.


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
    'MojoCompletedProcess', 'MojoFileHandle', 'MojoStructFmt',
})




# Fixed-size-array struct-field-annotation shape: `var x: [ElemType; N]`
# (fire_compiler.py's `_parse_type_ann_inner` LBRACKET branch captures the
# bracket contents verbatim via `_capture_bracketed_text`, which joins
# tokens with single spaces — so `[Block; MAX_BLOCKS]` round-trips as the
# string "[Block ; MAX_BLOCKS]"). `N` may be a decimal-literal size or a
# NAME referencing a module-level `comptime NAME: Int = <int-literal-or-
# foldable-expr>` constant (the common real-world shape, e.g. box.3d/game's
# `comptime MAX_BLOCKS: Int = 4096`) — see GimpleGen._module_const_int.
# See BUG-2026-008 (box.3d/game) for the real-world motivating case.
_FIXED_ARRAY_ANN_RE = re.compile(
    r'^\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*([A-Za-z_0-9]+)\s*\]$')



# Runtime-owned, FIXED-layout C structs this codegen itself defines (in
# runtime/fire_runtime.h or its own emitted preamble), as opposed to a
# struct arising from a user's own `class`/`struct` statement (those are
# never hardcoded here — they're always discovered via StructDef
# processing into `self.struct_field_types`, which is mutable/extensible:
# a not-yet-seen field on a USER struct legitimately grows the struct, see
# `_collect_self_assigns`). A fixed-layout runtime struct has no such
# extensibility (`MojoBoundMethod` is exactly `{ void *fn; void *self; }`,
# hardcoded in fire_runtime.h, forever) — an attribute name that isn't one
# of its real C fields must route through the same dynamic-attribute
# dispatch (`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr` ->
# `mojo_obj_getattr`/`mojo_setattr`'s real per-object storage, see
# “setting/getting an arbitrary attribute on a generically-typed object” Step 4) instead
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
    'mojo_list_contains_bytes':   'int',
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
    'mojo_dict_setdefault_int':   'int64_t',
    'mojo_dict_setdefault_str':   'char *',
    'mojo_dict_contains':         'int',
    'mojo_dict_get_int_kw':       'int64_t',
    'mojo_dict_get_double_kw':    'double',
    'mojo_dict_get_str_kw':       'char *',
    'mojo_dict_setdefault_int_kw': 'int64_t',
    'mojo_dict_setdefault_str_kw': 'char *',
    'mojo_dict_contains_kw':      'int',
    'mojo_dict_pop_int_kw':       'int64_t',
    'mojo_dict_pop_str_kw':       'char *',
    'mojo_dict_pop_double_kw':    'double',
    'mojo_dict_pop_int':          'int64_t',
    'mojo_dict_pop_str':          'char *',
    'mojo_dict_pop_double':       'double',
    'mojo_dict_set_bytes_int':    'void',
    'mojo_dict_set_bytes_str':    'void',
    'mojo_dict_set_bytes_double': 'void',
    'mojo_dict_get_bytes_int':    'int64_t',
    'mojo_dict_get_bytes_str':    'char *',
    'mojo_dict_get_bytes_double': 'double',
    'mojo_dict_contains_bytes':   'int',
    'mojo_dict_setdefault_bytes_int': 'int64_t',
    'mojo_dict_pop_bytes_int':    'int64_t',
    'mojo_dict_pop_bytes_str':    'char *',
    'mojo_dict_pop_bytes_double': 'double',
    'mojo_dict_len':              'int64_t',
    'mojo_dict_iter_new':         'MojoDictIter *',
    'mojo_dict_iter_next':        'int',
    'mojo_dict_iter_key':         'char *',
    'mojo_dict_iter_key_int':     'int64_t',
    'mojo_dict_iter_val_int':     'int64_t',
    'mojo_dict_iter_val_double':  'double',
    'mojo_dict_iter_val_str':     'char *',
    'mojo_dict_iter_free':        'void',
    # set
    'mojo_set_new':               'MojoSet *',
    'mojo_set_contains_int':      'int',
    'mojo_set_contains_str':      'int',
    'mojo_set_add_bytes':         'void',
    'mojo_set_contains_bytes':    'int',
    'mojo_set_val_bytes':         'MojoBytes *',
    'mojo_set_iter_pos':          'int64_t',
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
    'mojo_cstr_reverse':          'char *',
    'mojo_cstr_region_eq':        'int',
    'mojo_str_from_char':         'MojoStr *',
    'mojo_str_repeat':            'MojoStr *',
    'mojo_str_to_int':            'int64_t',
    'mojo_str_to_float':          'double',
    # bytes
    # `sys.stdout.write(s)` & friends. The ast_rewriter rules for those
    # (`sys_stdout_write` / `sys_stderr_write` / `sys_stdin_write`) lower
    # to this one call, because `sys.<stream>` is a POSIX fd boxed as an
    # opaque handle and there is no file-object model to dispatch a
    # `.write()` against. See the runtime function's own comment.
    'mojo_stream_write':         'void',
    # GPU offload introspection (see mojo/backend_gimple/device_glue.py).
    # Registered so a call from compiled Mojo resolves to the sidecar's real
    # definition instead of colliding with a weak auto-stub.
    '_mojo_gpu_kernel_count':   'int64_t',
    '_mojo_gpu_have_device':    'int64_t',
    '_mojo_gpu_dispatch_count': 'int64_t',
    '_mojo_gpu_failure_count':  'int64_t',
    'mojo_bytes_new_lit':         'MojoBytes *',
    'mojo_bytes_empty':           'MojoBytes *',
    'mojo_bytes_zeros':           'MojoBytes *',
    'mojo_bytes_from_list':       'MojoBytes *',
    'mojo_bytes_from_str':        'MojoBytes *',
    'mojo_bytes_from_cstr':       'MojoBytes *',
    'mojo_bytes_len':             'int64_t',
    'mojo_bytes_get':             'int64_t',
    'mojo_bytes_eq':              'int',
    'mojo_bytes_truthy':          'int',
    'mojo_bytes_repr':            'char *',
    'mojo_bytes_concat':          'MojoBytes *',
    'mojo_bytes_repeat':          'MojoBytes *',
    'mojo_bytes_slice':           'MojoBytes *',
    'mojo_bytes_contains':        'int',
    'mojo_bytes_find':            'int64_t',
    'mojo_bytes_rfind':           'int64_t',
    'mojo_bytes_find_from':       'int64_t',
    'mojo_bytes_rfind_from':      'int64_t',
    'mojo_bytes_index_int':       'int64_t',
    'mojo_bytes_rindex_int':      'int64_t',
    'mojo_bytes_count_int':       'int64_t',
    'mojo_bytes_count':           'int64_t',
    'mojo_bytes_count_from':      'int64_t',
    'mojo_bytes_startswith':      'int',
    'mojo_bytes_endswith':        'int',
    'mojo_bytes_decode':          'char *',
    'mojo_bytes_hex':             'char *',
    'mojo_bytes_removeprefix':    'MojoBytes *',
    'mojo_bytes_removesuffix':    'MojoBytes *',
    'mojo_bytes_title':           'MojoBytes *',
    'mojo_bytes_capitalize':      'MojoBytes *',
    'mojo_bytes_swapcase':        'MojoBytes *',
    'mojo_bytes_ljust':           'MojoBytes *',
    'mojo_bytes_rjust':           'MojoBytes *',
    'mojo_bytes_center':          'MojoBytes *',
    'mojo_bytes_zfill':           'MojoBytes *',
    'mojo_bytes_fill_byte':       'int',
    'mojo_bytes_partition':       'MojoList *',
    'mojo_bytes_rpartition':      'MojoList *',
    'mojo_bytes_fromhex':         'MojoBytes *',
    'mojo_bytes_cstr_key':        'char *',
    'mojo_bytes_maketrans':       'MojoBytes *',
    'mojo_bytes_translate':       'MojoBytes *',
    'mojo_bytes_is':              'int',
    'mojo_bytes_replace':         'MojoBytes *',
    'mojo_bytes_replace_n':       'MojoBytes *',
    'mojo_bytes_strip':           'MojoBytes *',
    'mojo_bytes_upper':           'MojoBytes *',
    'mojo_bytes_lower':           'MojoBytes *',
    'mojo_bytes_split':           'MojoList *',
    'mojo_bytes_rsplit':          'MojoList *',
    'mojo_bytes_split_max':       'MojoList *',
    'mojo_bytes_splitlines':      'MojoList *',
    'mojo_bytes_splitlines_keep': 'MojoList *',
    'mojo_bytes_join':            'MojoBytes *',
    'mojo_bytes_copy':            'MojoBytes *',
    'mojo_bytes_reverse':         'MojoBytes *',
    'mojo_bytearray_new':         'MojoBytes *',
    'mojo_bytearray_copy':        'MojoBytes *',
    'mojo_bytearray_mark':        'MojoBytes *',
    'mojo_bytearray_pop':         'int64_t',
    'mojo_bytearray_insert':      'void',
    'mojo_bytearray_remove':      'void',
    'mojo_memoryview_new':        'MojoMemoryView *',
    'mojo_memoryview_from_bytes': 'MojoMemoryView *',
    'mojo_memoryview_len':        'int64_t',
    'mojo_memoryview_get':        'int64_t',
    'mojo_memoryview_slice':      'MojoMemoryView *',
    'mojo_memoryview_tobytes':    'MojoBytes *',
    'mojo_memoryview_eq':         'int',
    'mojo_memoryview_hex':        'char *',
    'mojo_memoryview_cast':       'MojoMemoryView *',
    'mojo_memoryview_repr':       'char *',
    'mojo_memoryview_nbytes':     'int64_t',
    'mojo_memoryview_itemsize':   'int64_t',
    'mojo_memoryview_format':     'char *',
    'mojo_memoryview_obj':        'MojoBytes *',
    'mojo_memoryview_readonly':   'int',
    # struct module (binary pack/unpack)
    'mojo_struct_compile':        'MojoStructFmt *',
    'mojo_struct_new':            'MojoStructFmt *',
    'mojo_struct_calcsize':       'int64_t',
    'mojo_struct_size':           'int64_t',
    'mojo_struct_format':         'char *',
    'mojo_struct_pack_list':      'MojoBytes *',
    'mojo_struct_pack_h':         'MojoBytes *',
    'mojo_struct_unpack':         'MojoList *',
    'mojo_struct_unpack_from':    'MojoList *',
    'mojo_struct_unpack_h':       'MojoList *',
    'mojo_struct_unpack_from_h':  'MojoList *',
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
    # A3 stack-switch coroutine shim (runtime/mojo_coro_gen.c) — called
    # from a generator's lowered `__mgco_<g>_body` (gimple_gen_coro.py).
    '__mojo_coro_yield_i':   'int64_t',
    '__mojo_coro_yield_p':   'int64_t',
    '__mojo_coro_yield_d':   'int64_t',
    '__mojo_gen_arg':        'int64_t',
    '__mojo_gen_arg_d':      'double',
    '__mojo_gen_set_return': 'void',
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
from mojo.middle.types import (
    TypeLattice, _debug_note, _TYPE_MAP, _FLOAT_TYPES, _split_top_level_commas,
    _class_attr_ctype, _mojo_type, _result_type, _elem_type, _c_id, _c_var_decl,
    _printf_fmt, _strip_mojo_param_modifiers, _walk_type_expr, _param_sig_str,
    _method_overload_id, demangle_overload, _COMMON_METHOD_NAMES, _C_KEYWORDS,
    _CPP_KEYWORD_FIELDS, _C_PARAM_EXTRA_KEYWORDS, _C_MACRO_NAMES,
    _PSEUDO_DUNDER_ATTRS, _safe_field, _C_RESERVED_FUNCS, _FORCE_RENAME_RESERVED,
    _LIBM_FN_RETVALS,
    _safe_name, _stub_guard_name, _c_field_name, _import_targets, _c_escape,
    _str_literal_value_is_fstring, _extract_init_expr, _module_toplevel_name,
    _module_init_name, _used_idents_node, _CPP_CALLABLE_CTYPE,
    _CPP_CALLABLE_CTYPE_1ARG,
    _compute_exc_descendants, _unpack_target_leaf_names, _declared_vars_body,
    dispatch_table_global_ctype,
)
from mojo.middle.solvers import (
    _find_idents, _scan_for_escaping, _find_escaping, EscapeAnalyzer,
    LayoutSolver, DispatchTable, DispatchPattern, DispatchSolver,
    FunctionCompilability, TypePromotionSolver, ClosureInfo,
)
from mojo.middle.exprtypes import (
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


def _selfhost_impl_py_files(sd: str) -> list[str]:
    """Compiler implementation sources under `sd`: root `gimple_*.py` plus
    `mojo/middle/*.py` and `mojo/backend_gimple/*.py`.

    Self-host field/global pre-seeds must see the real implementation, not
    only the root entry (post-2026-09 package split). Uses `os.listdir`,
    not `glob.glob`: glob silently returns 0 matches in the self-hosted
    binary regardless of directory correctness (confirmed in
    emit_funcs._selfhost_scan_gimplegen_extra_fields).
    """
    out: list[str] = []
    try:
        for n in sorted(os.listdir(sd)):
            if n.startswith('gimple_') and n.endswith('.py'):
                out.append(os.path.join(sd, n))
    except OSError:
        pass
    for sub in ('middle', 'backend_gimple'):
        d = os.path.join(sd, 'mojo', sub)
        try:
            for n in sorted(os.listdir(d)):
                if n.endswith('.py'):
                    out.append(os.path.join(d, n))
        except OSError:
            continue
    return out


# ── THE self-host forward-declaration table ──────────────────────────────
# Every C symbol the self-host forward-decl block (gen_module's
# `_is_selfhost_file` gate) declares with a CONCRETE signature, and the ONE
# place that signature is written down. Key: the bare (unqualified) name —
# `Struct_method` for a method, the plain name for a free function, matching
# `_struct_method_csym_static`'s `f"{struct}_{safe_name(method)}"`.
# Value: (return ctype, [param ctypes], defining module or None for a free
# function). The third field is what turns a bare key into the QUALIFIED C
# symbol the definition is actually emitted under
# (`f"{module}_{bare}"`), which is why gen_module needs it: many self-host
# files never import Parser/Interpreter, so its own
# `_imported_struct_home` lookup returns '' (bare) and would declare a name
# that disagrees with the definition at link time.
#
# There used to be FOUR hand-maintained copies of these facts — this
# frozenset of names, a return-type-only dict, gen_module's
# `_is_selfhost_file` `_sh_ret`/`_sh_params` seeding pair, and the
# literal `parts.append(f"...")` forward-declaration strings — and nothing
# checked any of them against each other or against the definitions the
# codegen actually infers. They drifted, and the drift cost a full
# `fire.py fire --dump-full` self-host compile (~30 min) to discover:
# `Parser__parse_expr` returned an AST node pointer, so the definition is
# emitted `UnaryOp *`, while all four copies said `int64_t`. The result
# was "conflicting types for 'fire_compiler_Parser__parse_expr'" plus a
# dozen `-Wint-conversion` errors at every `_parse_expr` call site (both
# across modules, because the bogus decl was emitted per-importer, and
# inside fire_compiler.py itself, because emit_calls.py consults
# `_SELFHOST_FUNC_RETURN_TYPES` unconditionally and so overrode even a
# correctly inferred type). `jit_compile_and_execute` had already drifted
# the same way and silently: its return type was `int64_t` here against
# `_Bool` in the emitted decl.
#
# All four consumers derive from this table now, so they cannot disagree
# with each other. They still CAN drift from the codegen's own inferred
# definition types — that is inherent to declaring a sibling module's
# symbol before that module has been inlined — which is what
# `test_selfhost_sigs.py` checks, in `make check` rather than in a
# 30-minute bootstrap.
_SELFHOST_SIGS = {
    # Parser (fire_compiler.py)
    'Parser_parse_module': (
        'MojoList *', ['Parser *'], 'fire_compiler'),
    'Parser___init__': (
        'void', ['Parser *', 'MojoList *'], 'fire_compiler'),
    'Parser_with_filename': (
        'Parser *', ['Parser *', 'char *'], 'fire_compiler'),
    # `int64_t`, matching what the codegen's own return-type inference
    # emits for the definition -- NOT a node pointer.
    #
    # It used to read `UnaryOp *` here, because at the time this table was
    # written the inference DID produce `UnaryOp *`: `_parse_expr`'s `left`
    # is first bound by the `not` branch's `left = UnaryOp(op="not", ...)`,
    # and first-binding-wins typed the whole Pratt parser that way. The
    # inference no longer says that, because `left` goes on to hold
    # CompareChain/BinaryOp/WalrusExpr/TernaryExpr as the operator loop
    # refines the expression, so no single node pointer describes it and the
    # honest answer is the box (`_prebound_local_ctypes`' conflicting-binding
    # rule -- the same rule `_scan_body_for_local_field_access` applies to
    # fields). The table kept the stale answer, and a declaration that
    # disagrees with the definition is what the self-host closure cannot
    # survive: 2 "conflicting types for 'fire_compiler_Parser__parse_expr'"
    # plus a `-Wint-conversion` at each of the ~24 call sites inside
    # fire_compiler.py itself.
    #
    # `int64_t` is not a truncation here. A node value in this backend is a
    # pointer, and a pointer round-trips through an `int64_t` slot on a
    # 64-bit target; the caller's field reads then go through the ordinary
    # `_mojo_dispatch_getattr` dynamic path the rest of the compiled world
    # uses for a value whose node type is not statically known. Every OTHER
    # Parser method here is `void`/`Parser *`/`MojoList *` because its
    # returns really are one type each; `_parse_expr` is the one that is not.
    'Parser__parse_expr': (
        'int64_t', ['Parser *', 'int64_t'], 'fire_compiler'),
    # Unannotated single-definition helpers imported by
    # gimple_module_gen.py's `from gimple_codegen import ...` — see
    # _NO_OVERLOAD_MANGLE for why the bare name is pinned. Their sole
    # `all_struct_defs` param is a list, usage-inferred `MojoList *` on
    # the definition side, and every call passes a real list.
    '_merge_struct_inheritance': (
        'void', ['MojoList *'], None),
    # A DICT, so `MojoDict *` and not the `int64_t` this table used to claim:
    # `mojo/middle/types.py`'s definition builds and returns
    # `descendants = {name: {name} for name in by_name}` and the codegen's own
    # inference agrees (`MojoDict * _compute_exc_descendants (MojoList *)`).
    # A stale `int64_t` here is not a coercion imprecision like the rest of the
    # table — the auto-stub path EMITS it as a declaration, and this free
    # function's `_NO_OVERLOAD_MANGLE` bare C name is what every self-host
    # fragment calls, so "conflicting types for '_compute_exc_descendants';
    # have 'MojoDict *(MojoList *)'" is a hard self-host build failure (two
    # declarations of one symbol in one translation unit).
    '_compute_exc_descendants': (
        'MojoDict *', ['MojoList *'], None),
    # Interpreter (myinterpreter.py)
    'Interpreter___init__': (
        'void', ['Interpreter *', 'char *', 'MojoList *'], 'myinterpreter'),
    'Interpreter_execute': (
        'int64_t', ['Interpreter *', 'int64_t'], 'myinterpreter'),
    # Arity AND width must match fire.jit's definition or the closure
    # gets "conflicting types for 'jit_compile_and_execute'".
    # `auto_gpu` is the 6th parameter, and the self-host lowers a
    # DEFAULTED parameter to int64_t, not int — measured: declaring it
    # `int` gave "have '_Bool(char *, char *, int64_t, int64_t,
    # int64_t, int64_t)'" against the declaration's `int`. The return is
    # `_Bool`, not the int64_t this table used to claim.
    'jit_compile_and_execute': (
        '_Bool', ['char *', 'char *', 'int64_t', 'int64_t', 'int64_t',
                  'int64_t'], None),
}

# Name set only. The lazy auto-stub path (`_lower_named_call`'s
# `_is_unknown` fallback) must NOT also emit a conflicting variadic
# `(...)` declaration for these — two declarations of one symbol in one
# translation unit is a hard GCC "conflicting types" error (confirmed via
# `make check-selfhost` / `make check-runner`: the concrete decl comes from
# the forward-decl block, the variadic stub from the auto-stub path, and
# they collide).
_SELFHOST_HARDCODED_FUNCS = frozenset(_SELFHOST_SIGS.keys())

# Return types keyed by the bare name. When a call site in a self-host file
# (that does not directly import the defining module) invokes one of these,
# the codegen needs to know the real return type so it declares the result
# temp with the correct C type — the `int64_t` default would silently
# truncate/pointer-widen (e.g. `Parser *` -> `int64_t` on arm64).
_SELFHOST_FUNC_RETURN_TYPES = {}
for _shs_name in _SELFHOST_SIGS:
    _SELFHOST_FUNC_RETURN_TYPES[_shs_name] = _SELFHOST_SIGS[_shs_name][0]

# Parameter ctypes keyed by the same bare name. gen_module seeds these into
# `func_param_types` so the argument coercion at a cross-module call site
# matches the definition's own parameter list.
_SELFHOST_PARAM_TYPES = {}
for _shs_name in _SELFHOST_SIGS:
    _SELFHOST_PARAM_TYPES[_shs_name] = list(_SELFHOST_SIGS[_shs_name][1])

# Where a `**kwargs` parameter sits, for the self-host callable shapes whose
# `**kwargs` slot gen_module's own registration pass cannot derive: that pass
# is `isinstance(s, FunctionDef)` at MODULE level, so a struct METHOD never
# reaches it and its `_func_kwargs_slot` row has to be written by hand. The
# value is the 0-based index of `**kwargs` in the method's own `params`
# (`self` is index 0; a `*args` occupies ONE index however many arguments it
# collects), which is exactly what the derived walk computes for a top-level
# `def` — same convention, same arithmetic in every consumer:
# `_lower_named_call`'s free-function packing counts `kw_i - 1` ordinary
# params, and `_lower_struct_method_call`'s counts `kw_i - 2` (its `arg_pairs`
# exclude the receiver). A row that does not match the source is not an
# imprecision: the packing keeps the wrong number of leading positionals as
# "fixed" arguments and the call gets one argument too many.
#
# Module level, not a literal inside `gen_module_impl`, so
# `test_gimple.py`'s `handwritten_selfhost_signature_tables_match_the_source`
# can read it and derive the index from `inspect` — the same treatment
# `_SELFHOST_SIGS` gets. It read `3` against an older
# `MojoFunction.__call__(self, interpreter, *args, **kwargs)`; the interpreter
# moved to the `_interp` field and the signature is now
# `(self, *args, **kwargs)`, so `**kwargs` is at index 2.
_SELFHOST_KWARGS_SLOTS = {
    'MojoFunction___call__': 2,
}

# Whether a real `*args` precedes that `**kwargs` (as opposed to `**kwargs`
# being the method's only vararg-style parameter, which gets ONE C
# `MojoDict *` param rather than a `MojoList *` + `MojoDict *` pair). The
# companion fact to `_SELFHOST_KWARGS_SLOTS`, and populated with it.
_SELFHOST_KWARGS_HAS_VARARG = {
    'MojoFunction___call__': True,
}


def _selfhost_syms():
    """`[(qualified C symbol, return ctype, [param ctypes])]` for every
    `_SELFHOST_SIGS` entry, in a DETERMINISTIC order.

    The qualified name is what the definition is emitted under:
    `f"{module}_{bare}"` for a method, the bare name for a free function.
    That is deliberately not `_struct_method_csym_static` — it is the same
    `f"{qualifier}_{struct}_{safe_name(method)}"` string, spelled once here
    so gen_module cannot derive a different symbol than the table's own
    `defining module` field says.

    Sorted through an explicit list rather than `sorted(<dict>)`: on the
    self-hosted path iterating a container is address order, and
    `sorted(<set>)` is too (see the `all_modules_to_declare` comment), so
    an explicit list is the form that is deterministic in both engines."""
    _out = []
    for _bare in _SELFHOST_SIGS:
        _ret, _params, _mod = _SELFHOST_SIGS[_bare]
        _sym = f"{_mod}_{_bare}" if _mod else _bare
        _out.append((_sym, _ret, _params))
    _out.sort()
    return _out


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

def _merge_struct_inheritance(all_struct_defs: list) -> None:
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
    # `_as_structdef_node(s)`: `s` is a loop var over a list, so it is boxed
    # on the self-hosted compiled path and `s.bases` / `s.fields` / `s.methods`
    # would erase to `_mojo_dispatch_getattr` on an int64_t — the entire
    # inheritance merge then silently no-op'd (every `class Child(Base):` lost
    # its inherited members: ArcPointer's `_value`, and ~thousands of
    # stage1-vs-stage2 `.ci` divergences under MOJO_NO_SHIM=1).
    by_name = {}
    for _s0 in all_struct_defs:
        if isinstance(_s0, StructDef):
            _sd0 = _as_structdef_node(_s0)
            by_name[_as_str(_sd0.name)] = _sd0
    resolved = set()

    def resolve(s):
        s = _as_structdef_node(s)
        _sn = _as_str(s.name)
        if _sn in resolved:
            return
        resolved.add(_sn)  # mark first: guards against an inheritance cycle
        _bases = getattr(s, 'bases', None) or []
        if not _bases:
            return
        merged_fields = []
        merged_methods = {}
        for base_name in _bases:
            base = by_name.get(_as_str(base_name))
            if base is None:
                continue
            base = _as_structdef_node(base)
            resolve(base)
            merged_fields.extend(base.fields)
            for m in base.methods:
                merged_methods[_as_str(_as_funcdef_node(m).name)] = m
        own_names = set()
        for m in s.methods:
            own_names.add(_as_str(_as_funcdef_node(m).name))
        inherited = [m for name, m in merged_methods.items() if name not in own_names]
        s.fields = merged_fields + s.fields
        s.methods = inherited + s.methods

    for s in all_struct_defs:
        if isinstance(s, StructDef):
            resolve(s)


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

import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.module_gen as gmg
import mojo.backend_gimple.emit_calls as ggc
import mojo.backend_gimple.emit_stmts as gst
import mojo.backend_gimple.emit_loops as glo
import mojo.backend_gimple.emit_funcs as gfn
import mojo.backend_gimple.cpp_async as gca
import mojo.backend_gimple.cpp_core as gcc_
import mojo.backend_gimple.emit_exprs as gex
import mojo.backend_gimple.emit_infra as ginf
import mojo.backend_gimple.emit_resolve as grsl
class GimpleGen:
    # Map Python builtin names to their C/runtime equivalents when used as values
    BUILTIN_VALUE_MAP: dict[str, str] = {
        # The libm entries (`sqrt`, `exp`, `log`, ...) are generated from
        # the KEYS of mojo.middle.types._LIBM_FN_RETVALS — the single place
        # that says which math functions this compiler supports. The value
        # is the identity because the C symbol and the Python name are the
        # same string for all of them; the RETURN TYPE lives in that table
        # and is read separately at the call site. (Putting the return type
        # here instead is a real trap: BUILTIN_VALUE_MAP's value is a
        # symbol, so `sqrt` mapped to `double` and the auto-stub pass
        # emitted `int64_t double(...);`.)
        #
        # `math` is not a resolvable module in this project (module_loader's
        # `can_resolve_module_path('math')` is False), so without these the
        # name fell through `_safe_name` to a `mojo_<name>` stub nothing
        # defines. See that table for the exact scope and for what is
        # deliberately excluded.
        **{_k: _k for _k in _LIBM_FN_RETVALS},
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
        # fire_async_runtime.h's own docstring on `mojo_coro_resume_generic`/
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
                 no_mangle=(), relaxed_imports: bool = False,
                 auto_gpu: bool = True):
        # Function names that must NOT be overload-mangled in this TU — e.g. a
        # generic instantiation's own symbol, which is already uniquely named by
        # its type args and is referenced by that exact name from call sites.
        self._extra_no_mangle: set = set(no_mangle)
        # (struct name, method name) pairs that are OVERLOADED in this compile —
        # declared more than once on one struct. The UNSUFFIXED C symbol for
        # such a pair is defined by NEITHER overload (each carries a hash of its
        # real C parameter types: `__iter___0120be`, `__iter___0120be_2`), so a
        # consumer that dispatches through the bare name has nothing to call.
        # Published as its own registry rather than inferred from
        # `func_return_types`, which cannot express it: the bare entry must
        # STAY there for the forward-declaration emitter (removing it was
        # measured — see mojo/backend_gimple/module_gen.py's registration loop).
        # Read by `emit_loops._gen_for_struct_iter` and by
        # `emit_calls._lower_call`'s `next(<struct>)` branch; both are the
        # struct-protocol dispatch this project relies on, and both used to
        # emit a call to a symbol nothing defines.
        self._ambiguous_struct_methods: set = set()
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
        # A3 stack-switch coroutine trampolines gimple_gen_coro.register()
        # emits as plain C (doc/COROUTINE.html) -- appended verbatim into
        # this module's .c/.ci output by gen_module. Declared here (not
        # just dynamically set) so the self-hosted compiler's own static
        # field table for this class knows about it.
        self._stackswitch_coro_c_units: list[str] = []
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
        # (home-module qualifier, ORIGINAL function name) -> the same api
        # dict _generator_api holds — the whole-program, cross-module view
        # of every compiled free-function generator. _generator_api itself
        # is keyed by bare name alone and is SHARED across a do_imports=
        # True build's nested temp_gens by object identity, so two sibling
        # modules' same-named generators overwrite each other's entry
        # (last-compiled-wins) even before any call site runs; this
        # registry keeps both discoverable. Shared with temp_gens in
        # _compile_imported_module (same block that shares
        # _generator_api/_generator_method_api); consumers are the
        # FromImportStmt registration sites, which snapshot an import's
        # api into the per-instance _imported_generator_bindings below.
        # Keyed by a composite STRING "<home-qualifier>::<name>", not a
        # genuine (str, str) tuple — this dict (like _xmod_gen_param_hints
        # below) is part of GimpleGen's own instance state, which is real
        # Python running the compiler normally but becomes actual compiled
        # Mojo/C when this compiler's own source is self-hosted (test_
        # selfhost.py / `fire.py --jit fire.py`). This runtime's MojoDict
        # has no representation for a tuple key (keys are always coerced
        # to char * at the C level, see _char_to_cstr), so a genuine tuple
        # key here would either silently mis-stringify on write or (worse,
        # confirmed) hard-fail to compile the moment BOTH a tuple literal
        # and a `for k in this_dict:` iteration bind the SAME loop-variable
        # name within one self-hosted function: this compiler's per-name
        # "first C declaration wins" variable-typing model then declares
        # that name once (as the tuple's boxed MojoList * shape) and later
        # tries to store the iteration's real char * key straight into it
        # — "assignment to 'MojoList *' from incompatible pointer type
        # 'char *'". A plain string composite key sidesteps the whole
        # class of problem in both the interpreted and self-hosted-
        # compiled paths identically, rather than special-casing self-host.
        self._generator_home_api: dict[str, dict] = {}
        # as-bound alias/symbol name -> api dict, for generators THIS
        # module only knows through `from M import name [as alias]`
        # (populated at FromImportStmt lowering/registration time, so it
        # reflects exactly this module's own bindings). Per-instance by
        # design — never shared across temp_gens: each module's imports
        # bind names for ITSELF. Consulted by _lower_call's cross-module
        # generator-call branch and _quick_type's construction-shape rule.
        self._imported_generator_bindings: dict[str, dict] = {}
        # (sanitized home-module qualifier, ORIGINAL fn name) ->
        # {param name -> unanimous literal scalar ctype} — cross-call
        # scalar contracts for IMPORTED compiled generators, collected
        # from THIS module's own call sites BEFORE any imported module is
        # inlined, and applied by _compile_imported_module into the
        # temp_gen's _inferred_param_types so its generator unit is
        # generated with the caller's real parameter types (char */double)
        # instead of the int64_t default. Mirrors Pass 1.3d's same-module
        # contract exactly (same unanimity rule, same two scalar types) —
        # without it an unannotated `def walk(top): yield top` inlined
        # from a sibling module compiles `top` as int64_t while every
        # importing call site passes a char *, and every yielded value
        # prints as a raw pointer integer.
        # Keyed by the same composite "<home-qualifier>::<name>" string as
        # _generator_home_api above, for the identical reason (see that
        # field's docstring) — this dict is iterated by key (`for k in
        # self._xmod_gen_param_hints:`) in gen_module's merge pass, which
        # is exactly the tuple-key-plus-iteration shape that breaks self-
        # hosted compilation.
        self._xmod_gen_param_hints: dict[str, dict[str, str]] = {}
        # Companion to _xmod_gen_param_hints for LIST-ELEMENT types:
        # "<home-qualifier>::<fn>" -> {param name -> unanimous element ctype}.
        # Collected from THIS module's own call sites whose argument is a
        # collection LITERAL of same-typed scalars (e.g. a list of string
        # literals), shared with temp_gens, and applied by the defining
        # temp_gen into its own _param_list_elem_types — which
        # _gen_cpp_generator_unit then seeds into _cpp_list_local_elem_types,
        # so `for line in lines:` over that param emits mojo_list_get_str and
        # types the loop variable char * instead of the boxed-int64_t default.
        # Without it, a foreign generator yielding strings always inferred an
        # int64_t promise type and every next()/for consumption downstream saw
        # a number instead of a string. Same composite-string-key rationale as
        # _xmod_gen_param_hints above.
        self._xmod_gen_elem_hints: dict[str, dict[str, str]] = {}
        # Cross-module CONSTRUCTOR field-type hints: "<home-qualifier>::
        # <struct>::<param>" -> a unanimous scalar/container ctype ('char *'
        # / 'double' / 'MojoList *' / 'MojoDict *' / 'MojoSet *'), collected
        # from THIS module's own constructor call sites (`Foo('s')`,
        # `Foo([1, 2])`) whose target struct is DEFINED in an imported
        # module, BEFORE that module is inlined — mirrors
        # `_xmod_gen_param_hints` exactly, for the identical reason: the
        # struct's OWN `__init__` is compiled by a temp_gen that never sees
        # THIS module's call sites, so a field whose only evidence is an
        # unannotated ctor argument stayed the `int64_t` default (a scalar
        # mismatch is a hard `gcc -fgimple` "non-trivial conversion"
        # failure; a container mismatch is the silent SIGSEGV
        # “the constructor-call-site field-typing pass understood only scalars” fixed for
        # the SAME-module case — that fix's new pass runs per-gen and so
        # already covers an imported module's OWN internal call sites, but
        # not a call from a DIFFERENT module reaching in). Applied by the
        # defining temp_gen directly into its own `struct_field_types`,
        # beside the `_xmod_gen_param_hints` merge.
        self._xmod_ctor_field_hints: dict[str, str] = {}
        self._xmod_ctor_field_conflict: dict[str, bool] = {}
        # This module's own free-function generators' param -> element ctype,
        # merged from _xmod_gen_elem_hints entries matching this module_name
        # (plus available for same-module seeding). Consumed only by
        # _gen_cpp_generator_unit's per-unit seeding of the coroutine-body
        # emitter's local-elem-type registry.
        self._param_list_elem_types: dict[str, dict[str, str]] = {}
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
        # Side channel from _gen_cpp_generator_unit (same stash pattern
        # as _cpp_last_tuple_slot_ctypes): whether THIS unit's body had
        # an eligible value-carrying `return <expr>` — read back into
        # the api dict gen_module registers, so `yield from` consumers
        # know `{base}_value` carries the return value post-completion.
        self._cpp_last_has_return_value: bool = False
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
        # A3 stack-switch lowered BODY function name -> `{param: generator
        # api}` for the SOURCE parameters whose declared default names one
        # of this module's generators (`def walk_tree(root, *,
        # walk=_walk_tree)`). Populated by
        # `mojo.middle.coro.register`'s second pass; read by `gen_func`,
        # which copies the entry into the per-function
        # `_callable_param_gen_api` that `_lower_fnptr_call_value` consults
        # so a call through such a parameter is driven as the generator it
        # defaults to. Keyed by BODY name (not the source name) because the
        # stack-switch lowering moves every source parameter into a
        # `var p = __mojo_gen_arg(...)` local, so the body FunctionDef the
        # ordinary codegen emits is what `gen_func` actually sees.
        self._coro_body_callable_param_apis: dict[str, dict] = {}
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
        # Coroutine-BODY (.cpp emitter) analogue of _generator_var_api:
        # local-variable name -> the {'base', 'value_ctype', ...} api dict
        # of a compiled generator whose start-call that local holds (`g =
        # sub(...)` / `lines = strutil._iter_significant_lines(f)` inside
        # a compiled generator's own body). The ordinary GIMPLE path's
        # own dict above is consumed by .c-side lowering (for-loops,
        # next()); THIS one is consumed exclusively by gimple_cpp_core's
        # _cpp_expr/_cpp_stmt — chiefly `next(g)` inside a coroutine
        # body, which lowers to {base}_resume/_value plus a real
        # StopIteration throw on exhaustion. Reset per unit via
        # _cpp_reset_unit_state (a local only means something within the
        # unit that declared it), same convention as _cpp_kw_param_renames.
        self._cpp_generator_var_api: dict[str, dict] = {}
        # Coroutine-body generator APIs this module's .cpp unit REFERENCES
        # but does not itself define: base name -> {'value_ctype', 'params'}.
        # Populated whenever a coroutine body emits a `{base}_start(...)`
        # construction (same-module-earlier or cross-module); gen_module
        # emits matching guarded extern "C" declarations of all four
        # `{base}_start/_resume/_value/_destroy` symbols into generated_cpp's
        # preamble, so a foreign sibling unit's own object file (compiled +
        # linked by _compile_imported_module -> _compile_link_inline_cpp_unit)
        # satisfies them at link time. Sorted at emission for deterministic
        # (CAS-cache-stable) output.
        self._cpp_xmod_generator_refs: dict[str, dict] = {}
        # Concatenated .cpp text (one C++20 translation unit) for every
        # supported generator in this module, or '' if none. Set at the very
        # end of gen_module, once the API is fully known — the caller
        # (fire.py / build_stdlib_dylib.py) reads this attribute off the
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
        # (see CODEGEN_generator_struct_typed_param_refused).
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
        # C-stdlib / POSIX names (keys of `_LIBC_SIGS`) called from this
        # module's compiled generator/coroutine bodies — each gets a
        # self-emitted `extern "C"` prototype in the .cpp preamble (see
        # gen_module), mirroring `_ensure_libc_self_extern` on the
        # ordinary path.
        self._cpp_libc_sig_refs: set[str] = set()
        # Module-level `X = Y` aliases where Y is itself a module-level
        # function (`fspath = _fspath` in Lib/os.py — a conditional
        # rebinding of a name to a plain-`def` fallback). A call to `X(...)`
        # inside a compiled generator/coroutine body resolves through this
        # map to Y's real symbol instead of hitting the honest
        # "unresolved callee" refusal. Only simple identifier-to-identifier
        # aliases are recorded; a name reassigned to anything else is not.
        self._cpp_module_fn_aliases: dict[str, str] = {}
        # Per-function refusal reason recorded whenever a generator/async
        # unit compile attempt raises _UnsupportedGeneratorShape (keyed by
        # the function's Python name, first reason wins). Surfaced in
        # gen_module's strict-mode whole-module refusal so `fire.py build`
        # failures name the actual unsupported shape instead of only the
        # generic category list (previously visible only under MOJO_DEBUG).
        self._cpp_refusal_reasons: dict[str, str] = {}
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
        # For a struct field annotated `dict[K, dict[K2, V2]]`: the INNER
        # dict's value C type (`struct_field_types: dict[str, dict[str, str]]`
        # -> 'char *'), so `field[k]` / `field.get(k, {})` / `field.items()`
        # one level down still carries a real value type instead of int64_t.
        self._field_dict_nested_val_types: dict[str, dict[str, str]] = {}
        # For a struct field that is a LIST OF TUPLES (`FunctionDef.params`
        # is a `list[tuple[str, str]]` of (name, annotation) pairs): the
        # INNER tuple's slot C type. `struct_field_types` only records that
        # the field is a `MojoList *`, and `_field_elem_types` only the
        # element type — without this third level every `for a, b in
        # node.params:` / `for i, (a, b) in enumerate(node.params):` unpacks
        # both slots with `mojo_list_get_int`, binding boxed pointers that
        # then compare unequal to every string literal. Consumed by
        # `_gen_for_list` / `_gen_for_enumerate` via `_nested_elem_types`.
        self._field_nested_elem_types: dict[str, dict[str, str]] = {}
        # FLAT `"Struct.field" -> raw annotation string` map — a `dict[str,
        # str]`, so it survives the self-host compile intact (unlike the
        # nested `_field_dict_val_types` / `struct_field_types`, whose inner
        # dict reads box to int64_t). `_lower_MemberExpr` derives a field's
        # container value/element type from the annotation here when the
        # pre-digested nested maps come back empty — the cycle-breaker that
        # lets `member in gen.struct_field_types[sn]` / `_known_field_type`
        # work in the compiled compiler.
        self._field_annotations: dict[str, str] = {}
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
        # Fixed-size-array struct fields (`var x: [ElemType; N]`, fire_compiler.py's
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
        # which understands this shape. See BUG-2026-008 (box.3d/game).
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
        # Module-level GLOBAL name -> the return type of the CALLABLE stored
        # in it (`e = lambda: False` at module scope), and module-level name
        # -> the single callable return type stored in that dict (`d = {"k":
        # lambda: False}`), '' for "more than one distinct type, so no
        # answer". Same module-scope rationale as the two tables above:
        # a module global's callable return type means the same thing in
        # every function, unlike a recycled temp name, so it must survive
        # _reset_func. Populated by gen_module's Phase 1.7 pre-scan (which
        # runs BEFORE any function body is emitted, since a function that
        # calls `e()` is emitted before `_toplevel` lowers the lambda) and
        # consulted by _reset_func to re-seed the per-function
        # _callable_ret_types/_container_callable_ret.
        #
        # Without this, a lambda bound to a MODULE global lost its return
        # type at the box: `e = lambda: False; print(e())` printed `0`, and
        # `e = lambda: "hi"; print(e())` printed the pointer decimal --
        # the same shapes that are correct for a lambda bound to a LOCAL,
        # because the local store propagates _callable_ret_types through
        # the name (see _gen_stmt_AssignStmt). See
        # “CODEGEN: a lambda whose body is a bool returns int64 0/1”.
        self._global_callable_ret_types: dict[str, str] = {}
        self._global_container_callable_ret: dict[str, str] = {}
        self._struct_field_owners: dict[str, list[tuple[str, str]]] = {}
        self._return_elem_types: dict[str, str] = {}
        # Which PARAMETER each function's result IS, for the functions whose
        # whole body is `return <param>` (`ident`, `passthrough`). Their
        # return ELEMENT type is then a property of the CALL, not of the
        # callee: `_return_elem_types` can hold one answer per function, and
        # `ident` called with both `[1, 2, 3]` and `["a", "b"]` has one answer
        # for two different element types — the string one wins, and every
        # other call site then reads its int slots through
        # `mojo_list_get_str`. Measured: `list(ident([1, 2, 3]))` printed five
        # garbage bytes out of a three-element list, and `sorted(ident([3,
        # 1, 2]))` handed `[3, 1, 2]` to the string comparator, which saw
        # three values below the pointer window, called them equal, and
        # returned the list UNSORTED. Keyed by function name, value is the
        # parameter index. See
        # bugs/CODEGEN_return_element_type_is_unified_across_call_sites.md.
        self._passthrough_param_idx: dict[str, int] = {}
        # Functions whose `return` statements produce containers of MORE THAN
        # ONE kind (`if k: return names` / `return {x for x in names}`). Such
        # a function's inferred return type is the int64_t BOX — there is no
        # single container C type for its value — so a call site cannot know
        # which kind it will get and every consumer of the result has to ask
        # the runtime registries instead. Module scope for the same reason
        # `_return_elem_types` is: the callee's body is emitted before the
        # caller's call site reads this.
        #
        # Without it, the call site recorded a single `_actual_types` entry
        # from whichever `return` was emitted last, and `print(f(...))` then
        # read a MojoSet's slots through `_mojo_repr_list` — an out-of-bounds
        # read past the set's own slot array, so a SEGV rather than a wrong
        # answer.
        self._multi_kind_return_funcs: dict[str, bool] = {}
        # Function name -> the container kinds its `return` statements have
        # produced SO FAR, so the multi-kind verdict above is only reached
        # when a second kind really shows up (a function with one container
        # return stays an ordinary `MojoList *`).
        self._multi_kind_return_kinds: dict[str, list] = {}
        # Function name -> the set of its locals bound to containers/structs
        # of MORE THAN ONE kind (see `resolve_shared._infer_local_var_types`'s
        # own comment). Such a local's declared C type must be the box, not
        # whichever kind its first assignment site carries. Module scope, like
        # `_inferred_var_types`' per-function half it is read beside.
        self._multi_kind_locals: dict[str, set] = {}
        # Call-result VALUE names holding a container whose kind the CALLER
        # cannot know statically (the result of a call to a
        # `_multi_kind_return_funcs` member). Per-function like the other
        # value-keyed side tables, since these names are per-function temps.
        self._boxed_container_vals: set = set()
        # Function name -> the return type of the CALLABLE it returns
        # (`def mk(): return lambda: False`). Module scope for the same
        # reason as `_return_slot_types` above: the point is to carry a
        # callee's knowledge to a call site, and a per-function reset would
        # discard a callee whose body was emitted before its caller's. The
        # call site records it on the CallExpr NODE (not on the lowered
        # value) because a call result is immediately cast to its lowered
        # type — `f = mk()` then `f()` reads `_root_globals.f`, and
        # `mk()()` casts the result into a fresh temp — so a value-keyed
        # table cannot match it. See
        # “CODEGEN: a lambda whose body is a bool returns int64 0/1”.
        self._return_callable_ret_types: dict[str, str] = {}
        # Function name -> per-slot C types of a MULTI-VALUE return's
        # tuple handle (`return cfg, Model(cfg)`). Deliberately module
        # scope, NOT re-created per function the way the value-keyed
        # `_tuple_slot_types` is: the whole point is to carry a callee's
        # slot types to a call site EMITTED LATER, which a per-function
        # reset would erase between the two.
        self._return_slot_types: dict[str, list] = {}
        # Device kernels this module offloaded, and their MSL. Filled by
        # gen_module_impl's Seam-3 pass and read by the sidecar emitter at
        # the very end of the module; module scope because the MSL is only
        # final once every function has been walked.
        # A translation-unit-monotonic counter for self-shadowing loop
        # targets (`for tail in tail:`). Deliberately NOT reset with the
        # per-function state in emit_infra's function prologue, and held in a
        # one-element BOX rather than a bare int so every per-module
        # temp_gen shares it by reference the way the dicts/sets above do --
        # a bare int would restart at 0 in each throwaway GimpleGen and
        # reproduce the very collision this fixes. See emit_infra's mint site.
        self._shadow_seq_box = [0]
        self._device_kernels: dict[str, bool] = {}
        self._device_parts: list[str] = []
        self._device_launch_args: dict = {}
        self._device_launch_count: dict = {}
        # Element C types needing a _mg_pack_/_mg_unpack_ helper pair. A
        # MojoList handed to a `T *` parameter cannot be cast (the cast points
        # at the struct header), so the call is routed through an explicit
        # pack/call/unpack/free instead. Emitted once per element type, and
        # only for a module that actually does it.
        self._list_marshalling_needed: set[str] = set()
        # dict.items()/values() result temp -> the dict's VALUE type. The
        # runtime stores item pairs as [char* key, boxed value] (append_str +
        # append_int — see mojo_dict_items), so the for-loop tuple branch needs
        # the value slot's real type to pick get_str vs get_int; the key slot
        # is always a string. Side-table pattern, like _generator_var_api.
        self._dict_items_val_elems: dict[str, str] = {}
        # Dict[Int, V] iteration: items-list temps whose key slot is an
        # INTEGER (mojo_dict_items_int), the pair loop vars bound to such a
        # pair, and the function's provably Int-keyed dict names.
        self._dict_items_int_keys: set = set()
        self._dict_item_int_key_vars: set = set()
        self._int_key_loop_vars: set = set()
        self._int_keyed_dicts: set = set()
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
        # Declared here (not lazily `gen._x = []` in gimple_gen_coro) so the
        # frozen self-host GimpleGen struct has the field — else `--dump-full`
        # of a source that emits a stack-switch coroutine hits
        # "'GimpleGen' has no member named '_stackswitch_coro_c_units'".
        self._stackswitch_coro_c_units: list = []
        # Declared here for the same reason (see comment just above), not
        # left to `gen._native_future_bridge = True` (gimple_gen_coro.py's
        # only write site) alone: every OTHER reader is a bare
        # `getattr(gen, '_native_future_bridge', False)` (gimple_gen_calls.py,
        # gimple_gen_methods.py, gimple_module_gen.py) expecting a real
        # `False` default when unset. Without an explicit `__init__`
        # assignment, the self-hosted struct field for a program that never
        # takes gimple_gen_coro.py's `gen._native_future_bridge = True`
        # branch is heap-allocated but never written — reading it back
        # returns whatever garbage bit pattern was already on that memory
        # (observed as `1`, a false-truthy "yes, coroutine shim needed" on
        # a trivial `def main(): print(42)` program with no coroutines at
        # all), which spuriously pulled in ~40 unrelated `extern __mojo_*`
        # declarations and crashed a `mojo_list_len` call downstream in
        # gen_module_impl's boilerplate assembly on `MOJO_NO_SHIM=1`.
        self._native_future_bridge: bool = False
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
        # auto_gpu: when False, do NOT synthesise a device kernel for a
        # recognised parallel loop nest (`--no-gpu`). A function that already
        # carries `@gpu`/`@kernel`, or that is reached through
        # `compile_function[...]`/`enqueue_function[...]`, is STILL a device
        # function: the flag turns off INFERENCE, not the device path. That
        # distinction is the whole contract -- `offload.synthesise_module`
        # already skips explicitly-marked functions, so the two mechanisms do
        # not overlap and there is no way to be surprised by a marked kernel
        # silently demoted to the host.
        self.auto_gpu = auto_gpu
        self.func_return_types: dict[str, str] = {}
        self.struct_field_types: dict[str, dict[str, str]] = {}
        # local alias -> the struct's own BARE name, for `from M import
        # Class as Alias`. `struct_field_types` is keyed by the name as
        # written in the DEFINING module and is the table the constructor
        # dispatch in emit_calls.py tests membership against, so an aliased
        # import has to be mapped BACK before that test or `Alias(...)`
        # misses every struct table and lands in the generic
        # single-string-argument "opaque constructor" fallback, which
        # returns the argument unchanged — `x` became the literal `"a"` and
        # `x.widgetName` then dispatched getattr on a `char *`
        # (“OPEN: `from mod import Class as Alias”).
        # Populated by `_note_struct_import_alias`, which is the single
        # writer for BOTH the module-scope (`_register_sym`) and the
        # function-scoped (`_gen_stmt_FromImportStmt`) spelling.
        self._struct_import_aliases: dict[str, str] = {}
        # Names of user structs that subclass the builtin `dict` (directly
        # or transitively) — populated by gen_module_impl. Such a struct
        # gets a synthesized `_data: MojoDict *` backing field, and
        # inherited container ops route to it. See
        # bugs/COMPILE_FAIL_collections___init__.md.
        self._dict_subclass_structs: set = set()
        # Names of user structs that subclass the builtin `bytes` (directly
        # or transitively) — populated by gen_module_impl. Such a struct
        # gets a synthesized `_data: MojoBytes *` payload field populated
        # by `__new__` / `super().__new__(cls, val)`, and inherited bytes
        # ops route to it. See bugs/COMPILE_FAIL_zipfile___init__.md.
        self._bytes_subclass_structs: set = set()
        self._bytes_subclass_payload_argidx: dict = {}
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
        # `dict[str, dict[str, str]]`, not bare `dict`: struct name ->
        # {attr name -> mangled C global}. A bare `dict` annotation gives
        # the self-hosted backend no nested-value-type hint (mirrors
        # `struct_field_types: dict[str, dict[str, str]]` a few lines up,
        # which DOES carry one) — every real-struct write site
        # (`self._class_attrs[s.name][aname] = mangled`, loop ~2198 in
        # gimple_module_gen.py) happened to dodge this because "mojo_
        # compiler.py" (the only entry point whose transitive closure ever
        # recompiles itself as a NESTED import — see _run_pipeline's
        # GimpleGen-registration comment) is the first build to reach the
        # synthetic-GimpleGen-classattr registration branch through a
        # fresh, never-before-exercised temp_gen recursion depth. There the
        # inner dict's value type fell back to a generic default and the
        # write lowered as `mojo_list_set_int`, SIGBUS. Confirmed via lldb.
        self._class_attrs: dict[str, dict[str, str]] = {}
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
        # classes reached via *different* modules (fire_compiler.py's
        # FunctionDef vs ast_nodes.py's own FunctionDef, both present once
        # myinterpreter.py — which imports ast_nodes purely for method-
        # signature type annotations — is compiled) are scanned by two
        # different temp_gen instances, each of which would otherwise start
        # from a fresh, empty "have I seen this name" view and merge its own
        # fields in regardless of what an earlier temp_gen already decided.
        self._struct_name_owner: dict = {}
        # id(StructDef) -> the C-level identity ("cname") this struct is
        # emitted under, and the whole-program maps derived from it. The C
        # IDENTITY of a struct is the single string every consumer keys on:
        # `struct_field_types`, `_class_attrs`, the `typedef struct X` name,
        # the `_alloc_X`/`_mojo_repr_X` helper names, and the `{cname}_
        # {method}` C symbols. Historically that string was just
        # `StructDef.name`, so two same-bare-named classes in different
        # modules collided on it (see
        # CODEGEN_same_bare_name_struct_collision_across_modules
        # — the loser's field table, its `self->field` accesses and its
        # `__init__` call sites all resolved against the WINNER's, so a `str`
        # field was silently stored into the winner's `int64_t` slot). These
        # maps ARE that identity, made explicit:
        #   _struct_cname_by_id     id(StructDef) -> cname
        #   _struct_cname_of_name   bare name -> the OWNER's cname (the
        #                          first-wins struct, so a name that never
        #                          collided resolves to the bare name and
        #                          every non-colliding struct's output is
        #                          byte-identical to what it was before)
        #   _struct_cname_by_home   "home_module::Name" -> cname, the
        #                          MODULE-QUALIFIED lookup a construction /
        #                          field-access site uses to tell two
        #                          same-named classes apart
        #   _struct_qualified_cnames  the cnames that are NOT some struct's
        #                          own bare name; they already carry their
        #                          module prefix, so `_struct_method_qualifier`
        #                          must answer '' for them
        #   _struct_home_by_id      id(StructDef) -> the module that module's
        #                          own gen_module call compiled it in. The
        #                          collision TEST: two same-named StructDefs
        #                          collide only when their homes DIFFER (same
        #                          home is one file redefining a class, which
        #                          the bare-name first-wins already models).
        self._struct_cname_by_id: dict = {}
        self._struct_cname_of_name: dict = {}
        self._struct_cname_by_home: dict = {}
        self._struct_qualified_cnames: set = set()
        self._struct_home_by_id: dict = {}
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
        self.imported_symbols: dict[str, dict] = {}  # symbol_name -> {module, original_name, return_type, c_return_type, signature, ...}
        # Subset of `imported_symbols` keys that are genuine MODULE/
        # NAMESPACE markers (`import X [as Y]`, or `from PKG import
        # submod` where `submod` names a real submodule FILE) — as
        # opposed to a plain VALUE/function bound via `from X import
        # name`. Both shapes populate `imported_symbols` with the exact
        # same `{'module': ..., 'return_type': ...}` dict shape whenever
        # the imported function's signature couldn't be resolved (see
        # `_gen_stmt_FromImportStmt`'s bare-stub fallback), so `name in
        # imported_symbols` alone can't tell "X is a namespace" from "X
        # is an unresolved imported function" — confirmed via a real
        # regression: `std/gpu/primitives/id.mojo`'s `block_idx`/
        # `thread_idx` (real zero-arg accessor FUNCTIONS, imported via
        # `from gpu.primitives import block_idx` somewhere in the
        # transitively-compiled builtin prelude, but never resolved to a
        # real signature) register into `imported_symbols` with the
        # IDENTICAL shape as a genuine `import signal`-style namespace
        # marker. Populated ONLY by the two `import`-statement sites
        # (`_gen_stmt_ImportStmt`, and gimple_module_gen.py's top-level
        # import-alias pre-scan) and the FromImportStmt submodule branch
        # — never by an ordinary `from X import name` value/function
        # binding — so a caller that needs "is this genuinely a
        # namespace, not a value" (e.g. `_lower_MemberExpr`'s unresolved-
        # module-attribute fallback) can check this set instead of the
        # ambiguous `imported_symbols` membership alone.
        self._module_alias_names: set[str] = set()
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
        # Also (re)initialised per-function in _reset_func; declared here so
        # the self-host field-union scanner records the `dict[str, str]`
        # value type — without it `_lower_closure_call`'s
        # `gen._closure_envs[name]` read lowered to `mojo_dict_get_int`
        # (boxing the `''` / `_env_<name>` string), so every non-capturing
        # nested `def` call prepended a bogus empty env arg.
        self._closure_envs: dict[str, str] = {}   # inner fn name -> env var ('' if none)
        self._inner_func_name: str = ''           # original inner name (recursive-call detection)
        self._self_ctor_stubs: dict = {}  # struct names needing `Name___new` stubs (see _lower_self_ctor); dict-not-set so self-hosted `sorted(...)` keeps str keys (mojo_dict_sorted_keys), not address-ordered boxed slots
        self._renamed_builtin_calls: dict = {}  # renamed C-reserved builtin -> ret type (see _lower_call)
        self._ptr_helpers_needed: set[str] = set()   # elem C types needing _mojo_at_ helpers
        self._emitted_ptr_helpers: set[str] = set()  # elem C types already emitted (shared)
        # Same, for the device-side pack/unpack pairs. Initialised HERE, not
        # lazily, because `emit_resolve` reads it off the parent gen to share
        # it with each temp_gen -- a lazily-created attribute does not exist on
        # the parent yet, and that read raised
        # "'GimpleGen' object has no attribute '_emitted_list_marshalling'"
        # on every module that had no GPU kernel to create it first.
        self._emitted_list_marshalling: set[str] = set()
        self.func_param_types: dict[str, list[str]] = {}  # func_name → [param_ctype, ...]
        self._global_inline_defs: set[str] = set()   # all func names with inline definitions (shared)
        self._struct_allocs_needed: set[str] = set() # struct names needing _alloc_ helpers
        self._emitted_allocs: set[str] = set()       # struct names for which _alloc_ was already emitted
        self._ptr_alloc_n_needed: set[str] = set()   # elem C types needing _alloc_n_ helpers (UnsafePointer[T].alloc(n))
        self._emitted_ptr_alloc_n: set[str] = set()  # elem C types for which _alloc_n_ was already emitted (shared)
        # Whole-compile "emitted exactly once" singletons keyed by a short
        # tag (e.g. 'type_name_table'). Shared by ref into every nested
        # temp_gen like _emitted_allocs — a plain module-global bool for
        # this (the old `_emitted_type_name_emitted`) can't be read/written
        # cross-module in the compiled compile_to_gimple (no module-global
        # accessor plumbing for a `.py` sibling), and raised AttributeError.
        self._emitted_singletons: set = set()
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
        # import, not the inheritance-merge machinery — `python3 fire.py
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
        # “setting/getting an arbitrary attribute on a generically-typed object”). Gates
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
        # A THIRD field-scan cache, for `_scan_stmt_member_assigns` (the
        # `o.m = <value>` evidence the phantom-field mint types a field
        # from). Separate dict, not a second entry in the one above: the
        # cache is keyed by `id(stmt)` alone, so two different walks of the
        # same statement would collide and whichever ran second would read
        # the other's candidates back.
        self._field_scan_assign_cache: dict = {}
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
        # Self-hosting bootstrap: `gen_module_impl` and its Pass-1.x helpers
        # now live in `gimple_module_gen.py` as MODULE functions taking
        # `self`, so the `class GimpleGen` field-type scan never sees their
        # `self.<attr> = {}` / `[]` writes and defaults these fields to the
        # opaque `int` — storing a real MojoDict*/MojoList* pointer into an
        # `int` field truncates it and the next use segfaults. Seed them
        # here with the right shape so the scan types the struct fields.
        # `dict[str, dict[str, str]]`, NOT bare `dict`: the field-type scan
        # needs the nested value shape so `gen._inferred_param_types[fn]`
        # reads as `MojoDict *` and `pname in that` lowers to a real
        # `mojo_dict_contains` (not the int64_t `/* TODO: 'in' */` stub) —
        # without it `_param_ctype` never found a usage-inferred parameter
        # type in the self-hosted backend and every unannotated free
        # parameter fell back to int64_t.
        self._inferred_param_types: dict[str, dict[str, str]] = {}
        self._toplevel_dep_init_modules: list = []
        self._struct_layout: dict = {}
        self._layout_hint: str = ''
        self._fn_returns_generator: dict = {}
        # `dict[str, dict[str, str]]`, NOT bare `dict` — so the field-type
        # scan types `gen._inferred_var_types[fn]` as `MojoDict *` and
        # `.get(varname)` on it works. Without it the cross-call scalar
        # contract (`_arg_scalar_type` reading a caller local's inferred
        # type) silently got 0 on the self-hosted path, so a string local
        # passed to an unannotated parameter never propagated its `char *`.
        self._inferred_var_types: dict[str, dict[str, str]] = {}
        # Genexp-bound-to-a-local narrowing (see _seed_genexp_list_narrowing):
        # `_genexp_narrow_names` is the per-function set of local names whose
        # `name = (<genexp>)` assignment qualifies to be materialised as a
        # list; `_genexp_list_locals` maps a name that WAS so materialised to
        # its list element ctype, so every subsequent read of that name lowers
        # as a real `MojoList *` (its C storage slot may still be `char *` —
        # an opaque pointer round-trip) until the name is rebound to a
        # non-genexp value.
        self._genexp_narrow_names: set = set()
        self._genexp_list_locals: dict[str, str] = {}
        self._param_generator_api: dict = {}
        self._all_async_fn_names: set = set()
        self._bound_method_ret_types: dict = {}
        # Any callable VALUE -> that callee's real return type; see
        # emit_infra._reset_func's `_callable_ret_types` entry.
        self._callable_ret_types: dict = {}
        # dict value -> the single callable return type stored into it ('' when
        # ambiguous); see emit_infra._reset_func's `_container_callable_ret` entry.
        self._container_callable_ret: dict = {}
        self._module_int_consts_cache: dict = {}
        self._seen_generator_base_names: dict = {}
        self._cpp_module_fn_asts: dict = {}
        self._ctor_lit_param_types: dict = {}
        self._global_literal_slot_ctypes: dict = {}
        self._local_def_param_types: dict = {}
        self._param_elem_types: dict = {}
        # The dict-VALUE twin of the row above: callee -> {pname -> the dict
        # value ctype its call sites agree on}. Read at the same place (see
        # emit_funcs.gen_func / _gen_struct_method), into `_dict_val_types`.
        self._param_dict_val_types: dict = {}
        # Per-function maps that `_reset_func` (a MODULE function in
        # gimple_gen_infra.py, taking `gen`) re-initialises with real
        # `dict[str, str]` annotations the `class GimpleGen` field-type
        # scan never sees — same gap / same fix as `_inferred_param_types`
        # above. Without the `char *` VALUE shape here, `self._c_names.get(
        # name, _func_csym(name))` in `_lower_IdentExpr` fell to the
        # int64_t dict path and its char* default was coerced through a
        # list accessor — a hard segfault on `--dump myinterpreter.py`
        # (`mojo_list_get_int("mojo_make_list", 0)`).
        self._c_names: dict[str, str] = {}
        self._gimple_mut_ptr: dict[str, str] = {}
        self._boxed_mut_locals: dict[str, str] = {}
        self._elem_types: dict[str, str] = {}
        # Unpack-result C value -> per-slot element kind ('int'/'double'/
        # 'bytes'), for a `struct.unpack(...)` tuple. A MojoList carries a
        # single element ctype, but a struct format has one kind PER SLOT
        # and the format is a compile-time constant, so recording them
        # separately is what lets a mixed int/float format read back
        # correctly. It is a property of the VALUE, not of whether the
        # value was bound to a local: a bare
        # `print(struct.unpack('<if', buf))` reprs through
        # `mojo_repr_list_kinds` on exactly this table. What it does NOT
        # cover is a read with no compile-time slot index — iteration and a
        # computed subscript both need ONE static C type for a read whose
        # slot is not known. That residue was closed by moving the kinds ONTO
        # the value (`mojo_list_set_kinds` / `mojo_list_get_boxed` /
        # `mojo_repr_boxed` in runtime/fire_runtime.c) rather than by trying
        # to make one static C type cover a heterogeneous slot.
        self._struct_slot_kinds: dict[str, list] = {}
        # `struct.Struct(...)` result C value -> its const-folded format
        # string, so the INSTANCE methods can derive the same per-slot kinds
        # the module functions get for free from their own format argument.
        # Without it `_lower_struct_instance_method` had no codes at all and
        # `s.unpack(struct.pack('<if', 1, 1.0))` degraded exactly like the
        # module-function spelling used to.
        self._struct_formats: dict[str, str] = {}
        # Attribute/field name -> the const-folded format of the
        # `struct.Struct('<fmt>')` it was declared with, or None for a name
        # two classes declare with DIFFERENT formats. Consulted only when a
        # `Struct` handle's own value key missed: the format of a handle
        # reached through a field or class attribute (`self.F.unpack(buf)`)
        # has no local name for `_struct_formats` to be keyed on, and without
        # it a mixed format's float slot came back as raw IEEE-754 bits on
        # every statically-indexed read. See gen_module_impl's class-attr
        # scan, which fills this in, and _struct_ctor_format in
        # mojo/middle/types.py, which decides what counts.
        self._struct_attr_formats: dict[str, str | None] = {}
        # The same, keyed by (owning struct, attribute). Consulted FIRST, and
        # the only table that can answer when the name-only one above is
        # ambiguous — two classes with a `var F = struct.Struct(...)` of
        # DIFFERENT formats is ordinary, and the owning type is recoverable
        # at the read site for `self.F`, `Cls.F` and a local of a known
        # struct type.
        self._struct_attr_formats_scoped: dict[tuple, str] = {}
        # C values that are `MojoList *`s which MAY carry their own per-slot
        # element kinds at runtime (runtime/fire_runtime.c's
        # mojo_list_set_kinds): a `struct.unpack` result for a format that
        # mixes kinds, and anything the codegen itself derived from one.
        # Only a value in this set is read through `mojo_list_get_boxed`, so
        # an ordinary int-list subscript keeps emitting the plain
        # `mojo_list_get_int` it always did — the cost of the mechanism is
        # confined to the lists that can actually need it.
        self._maybe_kinds_vals: set = set()
        # C values produced by `mojo_list_get_boxed`, and so may be a BOX
        # (a heap cell carrying a float that has no int64_t spelling) rather
        # than the value itself. Consulted by the two places that stringify
        # an `int64_t` — `print` and f-string/`str()` — so only a value that
        # could be a box pays for finding out. See mojo_repr_boxed.
        self._boxed_vals: set = set()
        # Function name -> True when some `return` in its body hands back a
        # value whose per-slot kinds are recorded on the VALUE (a
        # `struct.unpack` of a format that mixes kinds). Read back at the
        # call site so a derived list crossing a function boundary is still
        # lowered as a boxed read. Filled by Pass 2c's whole-program scan,
        # beside `_return_elem_types`, which is the same shape for the same
        # reason — see _infer_return_maybe_kinds in
        # mojo/backend_gimple/module_gen.py.
        self._return_maybe_kinds: set = set()
        # Function name -> the per-slot kind of EVERY slot of a returned
        # heterogeneous list literal, in `gen._struct_slot_kinds`' long-form
        # spelling ('double' / 'str' / 'bytes' / 'int'). The set above is the
        # boolean half of the same question and answers only "ask the
        # runtime", which is what a subscript with no compile-time index
        # needs; this one answers it per index, which is what `a[2]` on
        # `[x, 1, s]` needs to come back as a `char *` rather than the raw
        # word. Both filled by the same whole-program scan — see
        # _infer_return_maybe_kinds in mojo/backend_gimple/module_gen.py.
        self._return_value_slot_kinds: dict[str, list] = {}
        self._nested_elem_types: dict[str, str] = {}
        self._param_struct_types: dict[str, str] = {}
        self._dict_val_types: dict[str, str] = {}
        # Per dict C name, the `_mojo_elem_repr_<Struct>` shim its `kind == 5`
        # slots are rendered with — or '' once that dict has been seen to hold
        # values the one function cannot render (a second struct type, or a
        # plain int). Recorded at the STORE, where the value's type is still
        # readable, and read by the runtime at REPR time, where it is not: the
        # same bargain `mojo_list_set_elem_repr` makes for a list, keyed by the
        # same `_dict_val_types` beside it and with the same lifetime.
        self._dict_val_repr: dict[str, str] = {}
        # The structs whose element-repr shim (`_mojo_elem_repr_<Struct>`) the
        # reflection preamble EMITTED for this module, published by
        # module_gen's `_emit_reflection_dispatch` and read by
        # `gimple_exprtypes.struct_elem_repr_shim` — the one predicate the list
        # and dict store lowerings ask. Empty until that preamble is built
        # (which is before any body is lowered) and, for a unit compiled with
        # `emit_struct_defs=False`, empty for good: no shim, no reference.
        self._elem_repr_shims: set = set()
        # The structs a CONTAINER store has asked an element-repr shim for
        # (`gimple_exprtypes.struct_elem_repr_shim` records there when it names
        # one). `_emit_reflection_dispatch` emits a shim for every struct in
        # this set in addition to the ones its own filter finds, because the
        # NAME is written into the generated C at the store site: the store and
        # the emission cannot be decided independently without the two
        # disagreeing, and when they did the self-host closure failed to link
        # with `'_mojo_elem_repr_TrieNode' undeclared`. Filled while the bodies
        # are lowered, read after, so it is complete by the time the preamble
        # is built.
        self._elem_repr_needed: set = set()
        self._dict_nested_val_types: dict[str, str] = {}
        self._captures: dict[str, str] = {}
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
        # Which pool NAMES have already had their `static char * _slit_N;`
        # forward declaration emitted in THIS translation unit. Every imported
        # module emits a pool block of its own (the declaration form, since only
        # the root emits definitions) and the pool is shared, so without this
        # each module re-declared every name interned before it — quadratic in
        # the number of imported modules. Same shape and same purpose as
        # `_regex_progs_defined` below, which does the same for a regex
        # program's `static const ARRAY[] = {...}`.
        self._str_pool_declared: set[str] = set()
        # Compile-time-known regex support (see regex_compile.py, BACKLOG-CODEGEN.md §4f):
        self._regex_patterns: dict[str, str] = {}    # `X = re.compile("...")` var name → pattern source
        self._regex_progs: dict[str, dict] = {}      # pattern source → regex_compile.compile_pattern(...) result
        self._regex_progs_defined: set = set()       # pattern source → already emitted its C decl (avoid duplicate `static const ARRAY[] = {...}` across submodules)
        self._find_generic_visited: set = set()      # (module, name, kind) already visited by _find_generic_source (breaks import cycles)
        self._scalar_annotated_locals: set = set()   # per-function allow-list for _emit_call's BUG-2026-016 auto-address coercion (reseeded by gen_func)
        self._struct_home_cache: dict = {}           # "kind\x1fmodule\x1fname" -> defining-module ref | None, memo for _find_symbol_home_module (which _find_struct_home_module delegates to), and the re-export-cycle guard
        self._regex_match_vars: dict[str, dict] = {} # for-loop var name → live match context (set/cleared per loop)
        self._dataclass_fields_vars: set = set()     # for-loop vars bound from dataclasses.fields(x) — f.name is f itself (set/cleared per loop)
        self._const_str_locals: dict[str, str] = {}  # _pair_key(func_name, var_name) → compile-time-folded string constant
        self._struct_has_init: set[str] = set()      # structs that have __init__ methods
        self._struct_method_names: dict[str, set[str]] = {}  # struct name -> {real method names}, see its own population site's docstring
        # struct name -> {@property getter names} (the subset of
        # _struct_method_names decorated `@property`). Real Python
        # auto-INVOKES a property getter on every bare read — a
        # `self.<prop>` value IS the getter's result, never the callable
        # itself — so the coroutine-body emitter needs this to emit a
        # direct call for a property read instead of the bound-method-
        # as-value wrapper it correctly still emits for ordinary
        # methods. Populated alongside _struct_method_names (same AST
        # walk sees m.decorators).
        self._struct_property_names: dict[str, set[str]] = {}
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
        # free-fn name (both mangled and plain) -> (n_fixed, kind) for a
        # function that DECLARES a `*args`/`**kwargs`, exactly the pair
        # `_lower_LambdaExpr` records for a variadic lambda. Used ONLY when
        # the function is taken as a VALUE (`f = g`), where its real C
        # signature (packed `MojoList *`/`MojoDict *` parameters) no longer
        # matches the arity-based `mojo_fnptr_call_N` convention: `def f(*a)`
        # called through `f` passed loose scalars where a `MojoList *` was
        # wanted, and the callee dereferenced the integer 1 — a SIGSEGV.
        # Materializing such a value as a `MojoVarargFn` (see
        # runtime/fire_runtime.h's "Variadic callables") makes every holder
        # of it — local, argument, container, struct field, `sorted(key=)` —
        # pack correctly. A DIRECT call by name is unaffected and keeps going
        # through `_lower_named_call`'s own `...`-sentinel packing.
        self._variadic_func_shape: dict[str, tuple] = {}
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
        # “COMPILE_FAIL: Lib/importlib/_bootstrap.py”'s `_verbose_message`
        # instance.
        self._vararg_trailing_param_types: dict[str, list] = {}
        # (struct_name, method_name) -> list of candidate overloads, each a dict:
        #   {'overload_id', 'param_names', 'param_ctypes' (excl self), 'min_arity', 'max_arity'}.
        # Populated from the CURRENT file's own AST only (same-file resolution);
        # a struct imported from elsewhere without local source has no entry here.
        self._struct_method_signatures: dict[str, list] = {}  # _sms_key(struct, method) -> [candidate-overload dicts]
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
        # Which "unresolved import" stub symbols (e.g. GimpleGen's own
        # methods, referenced-but-not-yet-compiled from a nested fragment)
        # have already had their `#ifndef GUARD ... #endif`-guarded stub
        # declaration emitted, ACROSS THE WHOLE do_imports=True compile —
        # shared across every nested temp_gen the same way `_module_
        # globals`/`_module_global_inits` above are. gen_module_impl used
        # to shadow this with a bare LOCAL `set()`, reset to empty on
        # EVERY per-module call instead of shared: each of a heavily-
        # referenced class's (e.g. GimpleGen, ~363 methods) many
        # importing fragments independently decided "I haven't emitted
        # this one yet" and re-emitted its own copy — confirmed directly,
        # 20328 total stub-guard occurrences for only 363 unique names in
        # a real `fire.py --dump-full` (~56x duplication). Every copy was
        # individually harmless C (the `#ifndef` guard makes every
        # occurrence after the first a no-op), but the sheer bulk made
        # the whole-program output significantly more sensitive to
        # exactly which of a symbol's many importing fragments happens to
        # run first — a real, unnecessary source of whole-program
        # `--dump-full` shim-vs-self-host byte divergence. A shared
        # dict/set instance ATTRIBUTE (not the historical module-level
        # `gimple_codegen._emitted_unresolved_stub_syms` global this
        # replaces, which a past session found unreliable to read
        # cross-module self-hosted) is the same proven-safe sharing
        # pattern `_module_globals` etc. already use successfully.
        self._emitted_unresolved_stub_syms: set = set()
        self._global_to_module: dict[str, str] = {}  # global_name -> module_name (shared)
        self._current_module_ctx: str = ""  # current module name for global field access
        self._current_struct_name: str = ""  # struct whose method body is being lowered (for Self() ctor); declared here so self-host keeps it `char *` — a `getattr` read erases it to int64_t and the `Name___new` stub decl came out as `<addr>___new`, nondeterministic
        self._global_var_types: dict[str, str] = {}  # module-level global name -> C type (persists across functions)
        self._global_c_decl_types: dict[str, str] = {}  # global name -> actual C declaration type (int64_t or pointer)
        # Phase C: Dispatch solver for static dispatch table planning
        self._dispatch_solver: DispatchSolver | None = None  # Instantiated in gen_module Phase 1.5
        self._dispatch_tables: dict = {}  # dispatch_table_name → DispatchTable (from _dispatch_solver)
        self._emitted_dispatch_typedefs: set[str] = set()  # Track typedef names already emitted
        self._emitted_dispatch_tables: set[str] = set()    # Track table names already emitted
        self._funcptr_builtins_needed: set[str] = set()    # builtin C names needing static void* vars
        # Value name -> the source-level function name, for the values that
        # are FUNCTION OBJECTS rather than any other `void *`. A function
        # value has no `char *` spelling, so every consumer of one used to
        # fall through to `TypeLattice.printf_fmt`'s `%d` default and format
        # the POINTER as a decimal — undefined behaviour on a 64-bit target,
        # and the source of the decimal address `print(f)` used to emit where
        # CPython prints `<function f at 0x...>`. Recorded by the two
        # `_lower_IdentExpr` function-value branches and read only by `print`,
        # which is the one consumer whose output is a `str()` spelling.
        # Value-keyed like `_boxed_vals` and `_boxed_container_vals` beside
        # it, and reset per function for the same reason they are: these are
        # SSA temp names and temps do not outlive their function.
        self._func_value_names: dict[str, str] = {}
        # Name -> C source for small non-GIMPLE accessor functions that a
        # __GIMPLE body needs to call. Two operations are legal in ordinary C
        # but are NOT valid GIMPLE primary expressions:
        #   * `sizeof(T)`      -> "expected expression before 'sizeof'"
        #   * `(void *)fn`     -> "invalid operand in unary operation"
        # so each is reached through a tiny `static` accessor emitted into the
        # non-GIMPLE prelude, which a gimple call can then invoke. Registered
        # by `_c_sizeof_helper` / `_c_fnaddr_helper` and flushed by
        # `gen_module` before the function bodies. Shared with every
        # _compile_imported_module temp_gen the same way the _emitted_* sets
        # above are, because all modules' generated code is concatenated into
        # ONE translation unit for the self-hosted build and a duplicate
        # top-level `static` would be a redefinition.
        #
        # What the sharing makes true, and why no call site has to reason
        # about it: `_c_helper_def` is called at the POINT OF USE, and every
        # place it emits to is ordered ahead of that use. Two of the three
        # destinations are inside the module's own `parts`/`func_parts`, so a
        # definition precedes its caller by construction; the third,
        # `_elaborated_externs`, is deliberately NOT shared (see
        # emit_resolve's sharing block) and is flushed by gen_module_impl
        # BEFORE `imported_code` is appended to `parts`, so the root module's
        # externs-borne definitions still land above every imported module's
        # code, and an imported module that is handed `''` is relying on a
        # definition higher up the one translation unit rather than on
        # something it skipped. Imported modules are emitted in
        # `sorted(modules_to_compile)` order, so the module that needed the
        # helper first is also the one whose definition comes first.
        #
        # Before the sharing, each temp_gen started with its own empty dict AND
        # its own empty `_emitted_c_helpers` set, so none of the above held
        # for it and a second module emitted a second definition; correctness
        # came only from six independent per-call-site guards, none of them
        # this contract.
        self._c_helpers_needed: dict[str, str] = {}
        # Which of those have already had their DEFINITION emitted into the
        # final .ci. Definitions are emitted inline, immediately before the
        # function that calls them (see `_c_sizeof_helper_def`), because the
        # set of needed helpers is not final until the whole module — function
        # bodies, struct `_alloc_*`, lifted closures — has been walked, and a
        # single flush point would necessarily land either before some caller or
        # after a struct typedef the definition needs. Shared with every
        # _compile_imported_module temp_gen for the same reason the
        # _emitted_* sets are: all modules' generated code is concatenated into
        # ONE translation unit, so a duplicate top-level `static` is a
        # redefinition.
        self._emitted_c_helpers: set[str] = set()
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
        # CODEGEN_set_list_ctor_ignores_iterable_arg's quality-gate
        # notes: fixing set()/list() to actually walk their iterable argument
        # (reusing the comprehension iteration machinery) let previously
        # mid-lowering-abandoned functions in myinterpreter.py/
        # build_stdlib_dylib.py compile all the way through for the first
        # time, which is what newly exposed this latent cross-module
        # collision (only regex_compile.py used to reach a bare `dict`
        # reference at all).
        self._emitted_funcptr_builtins: set[str] = set()
        self._auto_stubbed: set[str] = set()               # function names auto-stubbed in _emit_call
        # doc/OWNERSHIP_MODEL.md Phase 3's per-function state (gimple_gen_
        # infra.py's begin_function/reset_no_candidates/emit_return_frees/
        # emit_fallthrough_frees). Previously only ever assigned dynamically
        # OUTSIDE __init__ (inside begin_function, called from gen_func) —
        # never declared here, so it was never part of GimpleGen's own
        # self-hosted STRUCT LAYOUT. That was invisible for a long time
        # because `_owned_free_candidates` was ALWAYS an empty set at
        # runtime under self-hosting (the separate `ownership_destruct.
        # analyze_function` self-host bugs its own docstring documents),
        # so `if gen._owned_free_candidates:` was always false and nothing
        # ever read the (uninitialized/undeclared) field. Fixing those
        # bugs made this one real for the first time: `begin_function`'s
        # write went to a field GimpleGen's own struct never allocated,
        # and the next read (`emit_fallthrough_frees`) crashed on garbage/
        # near-null memory (confirmed via lldb: EXC_BAD_ACCESS in
        # `mojo_set_len`, called via `gen._owned_free_candidates`).
        self._owned_free_candidates: set = set()
        self._owned_free_pushed: set = set()
        self._owned_stack_allocated: set = set()
        self._cstr_key_src: dict[str, str] = {}  # see _char_to_cstr(transient=)
        self._kw_key_src: dict[str, str] = {}    # see _char_to_cstr(word_ok=)
        # Value names this codegen has POSITIVELY established hold a plain
        # Python integer -- the exact complement of `_actual_types`, which
        # records the opposite (a real pointer seen through an int64_t slot).
        # `_actual_types` being silent is NOT evidence either way: a lambda
        # parameter, an erased dict value and a getattr result all arrive as
        # an untracked int64_t that may hold a string, which is why the
        # dict-key `_kw` entry points exist at all. But where the codegen
        # does KNOW, it must say so instead of leaving the runtime to guess:
        # `mojo_boxed_is_str` is a RANGE test, so it calls every positive
        # int64 in [2^31, 2^47) a pointer and hands it to `strcmp` --
        # `d[3000000000] = 1` was a SIGSEGV. See
        # bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md and
        # `_char_to_cstr`'s word_ok branch, the one consumer.
        self._int_word_vals: set = set()
        self._fresh_str_tmps: set = set()  # see emit_infra._emit_str_cat
        self._fresh_vals: set = set()  # see emit_infra.is_fresh_container_operand
        # Names bound to a bool, keyed by NAME across functions (see
        # emit_stmts._record_bool_valued). Declared HERE, not created lazily
        # behind `if not hasattr(gen, '_bool_valued')`: self-hosted, the field
        # exists in GimpleGen's struct from the start, so `hasattr` answered
        # True, the lazy `set()` never ran, and the first `add` went through
        # a NULL set -- the SIGSEGV that ended every `mojoc --dump-full
        # fire.py` in `mojo_set_add_str`.
        self._bool_valued: set = set()
        # Parameter names whose ANNOTATION says `bool`, for the struct method
        # `_gmi_collect_self_assigns` is scanning RIGHT NOW (module_gen.py
        # rebuilds it per method). That walk is the one place that knows both
        # halves -- "this parameter is a bool" and "`self.<field> = <param>`
        # makes it a field" -- and `struct_bool_fields` needs both, because a
        # `bool`-annotated field's own ctype is a plain `int` (`_TYPE_MAP`
        # maps `'bool'` to `'int'`) so nothing downstream can recover it from
        # the type. Declared here for the same self-hosting reason as
        # `_bool_valued` directly above: a field created lazily behind
        # `hasattr` reads as existing-but-NULL self-hosted.
        self._gmi_bool_params: set = set()
        # current_func_name -> the parameter names whose ANNOTATION says
        # `bool`, written by `mojo.middle.exprtypes.record_bool_params` at the
        # two sites that lower a function/method body and read back by
        # `bool_param_in_scope` from the one shared bool predicate. A
        # `bool`-annotated parameter's own ctype is a plain `int` (same
        # `_TYPE_MAP` reason `struct_bool_fields` exists), and it is NOT
        # distinguishable from a small int LITERAL's lowering, so the
        # annotation has to be captured rather than re-derived from the type.
        # Declared here for the same self-hosting reason as `_bool_valued`:
        # a field created lazily behind `hasattr` reads as existing-but-NULL.
        self._bool_param_names: dict = {}
        # Struct -> method names whose every `return` hands back a `bool`
        # field of that struct (see module_gen.py's second method loop). The
        # method's own C return type is `int` -- the field's ctype -- so this
        # is what lets `print(b.get())` answer `True`; it is deliberately NOT
        # a `_Bool` return type, which would make `b.get() + 1` a GIMPLE
        # operand-type error.
        self.struct_bool_methods: dict[str, set[str]] = {}
        # Pool of reusable scratch dicts for the hermetic type scans, handed out
        # in stack order: see resolve_shared._scan_scratch_dict.
        self._scan_scratch: list = []
        self._scan_scratch_top: int = 0
        # Block-scoped destruction state — see emit_infra's block-scope section.
        self._analysis_funcs: dict = {}   # see infra_infer._build_analysis_funcs
        self._fresh_returning: set = set()   # names whose calls return a fresh container
        self._analysis_structs: dict = {}    # see infra_infer._build_analysis_structs
        self._cur_func_body: list = []  # the AST body being lowered (see _reset_func)
        self._decl_value_node = None   # see lower_expr: the decl statement's RHS node
        self._decl_rhs_val: str = ''   # and the value it lowered to
        self._literal_storage: str = ''        # see emit_infra.emit_container_new
        self._literal_storage_ctype: str = ''
        self._scoped_free_candidates: set = set()
        self._scope_armed: set = set()
        self._scope_live: list = []
        self._scope_live_depth: list = []
        self._scope_live_fn: list = []
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
        # fix (“COMPILE_FAIL: Tools/cases_generator/parser.py”'s lexer.py/
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
        # local name -> the module string, for a bare `import M [as L]` whose
        # module this compile cannot resolve; '' for every other name. The
        # consumer is `_uncompiled_module_marker` in emit_methods.py, which
        # needs the filesystem answer (`module_loader.can_resolve_module_path`)
        # once per name rather than once per call site. Keyed on the SAME
        # `_module_alias_names` set, for the ambiguity that set's own docstring
        # records: `imported_symbols` also holds every `from X import name`
        # binding, and an unresolved one has the same dict shape.
        self._uncompiled_marker_cache: dict = {}
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
        # placeholder a per-module-independent `fire dylib` compile
        # previously fell through to for this shape.
        self._imported_global_accessors: dict = {}
        # Concrete imported structs used as parameter types here: their StructDefs
        # (so the layout typedef is emitted in dylib mode) and their names (so only
        # these — not local structs — get the authoritative struct-pointer param
        # typing, keeping the blast radius tight).
        self._imported_typedef_structs: list = []
        self._imported_struct_names: set = set()
        # Self-host GimpleGen registration state — initialised here (not
        # only in `_selfhost_register_gimplegen`) so every read is a direct
        # field load, never a `getattr` that erases to a boxed int64 on the
        # compiled path (which made the `_gg_stmts is not None` guard in
        # gimple_module_gen.py mis-fire and drop the ~1400-line GimpleGen
        # method-extern block from stage2's fire.ci under MOJO_NO_SHIM=1).
        self._selfhost_gimplegen_stmts = None
        # Bare `dict = {}` left the value ctype unresolved self-hosted, so
        # `gen._selfhost_gimplegen_extra_fields[k]` read back the raw
        # MojoDict-value pointer bits reinterpreted as int64_t (e.g. printed
        # as a huge decimal like 4374397560) instead of dereferencing it as
        # `char *` -- explicit `dict[str, str]` forces the correct value
        # ctype. Root cause of Finding 4 Bug C's GimpleGen struct_field_
        # types corruption (257/183-wrong vs 290 fields shim).
        self._selfhost_gimplegen_extra_fields: dict[str, str] = {}
        self._selfhost_gimplegen_sigs = None
        self._selfhost_gimplegen_dict_vts: dict = {}
        self._selfhost_gimplegen_registered = False
        self._selfhost_src_dir = ""
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
        # Imported module name -> the absolute path its source was actually
        # read from. Populated by _compile_imported_module as each nested
        # temp_gen is created (it already computes the canonical `_abspath`
        # for its own `#line` directives), and shared into every temp_gen so
        # any ancestor can name the right FILE for a statement that physically
        # came from another module — see `_line_src_file` in gen_stmt
        # (mojo/backend_gimple/emit_stmts.py) and its use around
        # `_gen_struct_method` for the inheritance-merge case, where a base
        # class's method body is emitted a second time as a SUBCLASS method
        # and would otherwise be attributed to the subclass's file.
        self._module_source_paths: dict = {}
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
        self._inline_module_qualifiers: dict[str, str] = {}
        # Imported free-function bare name -> its home module's qualifier,
        # populated ONLY from the CURRENT gen_module call's own top-level
        # FromImportStmt scan (_emit_stdlib_import_externs /
        # _register_link_imports, both of which operate on `stmts` — this
        # instance's own compile unit — never a nested/sibling module's).
        # Deliberately NOT shared across nested temp_gens (contrast
        # _imported_func_home above): a real bug (found via `fire.py build`
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
        # The VALUE half of `_own_imported_func_home` above: the bare name a
        # `from b import K` (module-level, this gen_module call's own
        # top-level stmts) binds, -> the module whose `_<mod>_globals` struct
        # actually declares the field, and -> that field's name (different
        # from the bare name under `from b import K as J`). Two dicts rather
        # than one `local -> (module, field)` 2-tuple because a 2-tuple lowers
        # to a MojoList on the self-hosted compiled path, so every reader of
        # it boxes its slots to int64_t (see `_module_global_field_type`'s own
        # closing note, which reads the same triples by index for this reason).
        #
        # Why it exists at all, when `_global_to_module` already maps a bare
        # name to its owning module: that map is whole-transitive-tree and
        # name-keyed, so a bare `K` in THIS module's body could be resolved
        # through it to a SIBLING's `K` that this module never imported — the
        # `filename` mis-resolution `_lower_IdentExpr`'s gate documents. This
        # dict answers the stricter question "did THIS module's own source
        # import it, and from where", which is the only question whose YES
        # makes a bare read mean another module's field (real Python: `from
        # b import K` binds b's object into this module's namespace, so `K`
        # here IS b's K).
        #
        # The qualified `b.K` spelling never needed it: `_lower_MemberExpr`
        # reads `_module_global_field_type(bound_module, member)` and the
        # owning module's own `(name, c_type, g_mtype)` triple, so the field
        # and its type agree by construction. This is the bare-name half of
        # that same pair, and both are needed or the two spellings of one
        # name disagree — the argument `_module_global_field_type` already
        # makes for the homonym case.
        self._own_imported_global_home: dict = {}
        self._own_imported_global_field: dict = {}
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
        self._imported_home_param_types: dict[str, list] = {}  # _pair_key(sanitized-home-qualifier, fn-name) -> [param ctypes]
        # _pair_key(sanitized home-module qualifier, fn name) -> [param ctypes] —
        # the WHOLE-PROGRAM-SHARED definition-side truth for free-function
        # signatures, written ONLY by a unit that actually defines the name
        # (when its `_local_def_pts` resolves the FunctionDef it owns) and
        # read FIRST by every importer's `_imported_def_pts`, ahead of that
        # importer's own eager `_signature_ctypes` snapshot. The definer's
        # committed signature is authoritative — exactly one definition
        # symbol gets emitted — while an importer's snapshot can disagree
        # because each gen's `_inferred_param_types` is per-instance
        # (c_parser/parser/_global.py's literal-`group` call sites froze
        # log_match's `group` to char * while _common.py's own definer had
        # no call sites and froze int64_t: two different overload suffixes
        # for one symbol — "implicit declaration of function" at g++).
        self._home_def_param_types: dict[str, list] = {}  # _pair_key(sanitized-home-qualifier, fn-name) -> [param ctypes]
        # _pair_key(sanitized home-module qualifier, fn name) -> return ctype —
        # the RETURN-type twin of the store just added, and written for the same
        # reason with the same key, writer discipline and reader order, because
        # `func_return_types` is keyed by the BARE name and a whole-translation-
        # unit closure routinely has several modules each defining a function of
        # one bare name with DIFFERENT return types (`mojo/middle/offload.py`'s
        # `_mentions(...) -> bool` against `mojo/backend_gimple/elab_intu.py`'s
        # unannotated `_mentions(ann)` -> `MojoList *`). One bare slot holds one
        # arbitrary module's answer, so the other module's call sites read the
        # wrong type: `assignment to 'MojoList *' from 'int' makes pointer from
        # integer without a cast`. Only a unit that DEFINES the name writes here
        # (`_record_home_def_return_type`), only `_func_csym` reads it, and it
        # reads it keyed by the very qualifier that call site built its symbol
        # from — so both halves of one mangled symbol name the same definition.
        # `_quick_type`'s bare read was the second reader (return-type
        # INFERENCE compounds: a forwarder's own return type is inferred from
        # the callee), and it reaches this store through
        # `_func_return_type_for_call` below. Regression coverage:
        # `test_gimple.py`'s
        # `two_modules_one_same_named_function_keep_their_own_return_types`.
        self._home_def_return_types: dict[str, str] = {}
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
        # Why an imported generic struct could NOT be elaborated for a
        # construction, one entry per occurrence. The codegen falls back to
        # the un-elaborated template (see
        # `emit_resolve._ensure_generic_struct`, which measures that fallback
        # as load-bearing), so this list is the only evidence that what came
        # out is a DIFFERENT program from the one the source says — and
        # `build_stdlib_dylib.compile_module_to_c_cached` reads it to refuse
        # to publish such a module into the content-addressed store, where a
        # one-off failure would otherwise be served forever.
        self._generic_struct_elaboration_failures: list = []
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
        # Under the A3 stack-switch coroutine backend (MOJO_CORO=stackswitch),
        # `_coro_resume_fn`/`_coro_destroy_fn` (std.gpu.host.DeviceContext's
        # detached-async dispatch, device_context.mojo) must resolve to the
        # stack-switch generic resume/destroy pair (__mojo_gen_resume_once/
        # __mojo_gen_destroy, runtime/mojo_coro_gen.c — operating on a
        # `MojoGenerator *` handle) instead of the cpp-path's C++20-coroutine
        # pair (mojo_coro_resume_generic/destroy_generic, which expect a raw
        # std::coroutine_handle<> address and would misinterpret a
        # MojoGenerator* the same way). An instance override (not a class
        # dict edit) so this never leaks into a cpp-path compile running in
        # the same process. See bugs/hard/CODEGEN_coro_detached_async_
        # take_handle.md and gimple_gen_coro.py's own resume_fn/destroy_fn
        # docstring.
        if gimple_gen_coro.enabled():
            self.BUILTIN_VALUE_MAP = dict(GimpleGen.BUILTIN_VALUE_MAP)
            self.BUILTIN_VALUE_MAP['_coro_resume_fn'] = '__mojo_gen_resume_once'
            self.BUILTIN_VALUE_MAP['_coro_destroy_fn'] = '__mojo_gen_destroy'
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
        'mojo_is_bound_method':     ('int', ['void *']),
        # Variadic callables (see runtime/fire_runtime.h's "Variadic
        # callables" comment): a value whose real callee wants its
        # arguments packed into a MojoList/MojoDict rather than passed
        # positionally. Registered in its own runtime registry so
        # mojo_fnptr_call_N / mojo_maybe_bound_call_N can tell it apart
        # from a bare function pointer at a dynamically-dispatched call.
        'mojo_vararg_fn_new':  ('MojoVarargFn *', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_is_vararg_fn':   ('int', ['void *']),
        'mojo_vararg_call_0':  ('int64_t', ['void *', 'void *']),
        'mojo_vararg_call_1':  ('int64_t', ['void *', 'void *', 'int64_t']),
        'mojo_vararg_call_2':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t']),
        'mojo_vararg_call_3':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_vararg_call_4':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_0':  ('int64_t', ['void *', 'void *']),
        'mojo_fnptr_call_kw_1':  ('int64_t', ['void *', 'void *', 'int64_t']),
        'mojo_fnptr_call_kw_2':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_3':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_4':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_0': ('int64_t', ['void *', 'void *']),
        'mojo_maybe_bound_call_kw_1': ('int64_t', ['void *', 'void *', 'int64_t']),
        'mojo_maybe_bound_call_kw_2': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_3': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_4': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_vararg_call_5':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_5':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_5':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_5': ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_5': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_vararg_call_6':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_6':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_6':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_6': ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_6': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_vararg_call_7':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_7':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_7':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_7': ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_7': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_vararg_call_8':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_8':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_fnptr_call_kw_8':  ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_8': ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_kw_8': ('int64_t', ['void *', 'void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_0':  ('int64_t', ['void *']),
        'mojo_maybe_bound_call_1':  ('int64_t', ['void *', 'int64_t']),
        'mojo_maybe_bound_call_2':  ('int64_t', ['void *', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_3':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t']),
        'mojo_maybe_bound_call_4':  ('int64_t', ['void *', 'int64_t', 'int64_t', 'int64_t', 'int64_t']),
        'conforms_to':           ('_Bool',      ['int64_t', 'int64_t']),
        'llabs':                 ('int64_t',   ['int64_t']),
        'labs':                  ('int64_t',   ['int64_t']),
        'mojo_str_split':        ('MojoList *', ['char *', 'char *']),
        'mojo_str_rjust':        ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_ljust':        ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_center':       ('char *',     ['char *', 'int64_t', 'char *']),
        'mojo_str_splitlines':   ('MojoList *', ['char *']),
        'mojo_str_count':        ('int64_t',    ['char *', 'char *']),
        'mojo_str_count_from':   ('int64_t',    ['char *', 'char *', 'int64_t', 'int64_t']),
        'mojo_str_rsplit':       ('MojoList *', ['char *', 'char *', 'int64_t']),
        'mojo_str_partition':    ('MojoList *', ['char *', 'char *']),
        'mojo_str_rpartition':   ('MojoList *', ['char *', 'char *']),
        'mojo_c_getenv':         ('char *',     ['char *']),
        'mojo_char_to_str':      ('char *',     ['char']),
        'mojo_char_at_str':      ('char *',     ['char *', 'int64_t']),
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
        'mojo_repr_list_bools':      ('char *',    ['MojoList *']),
        'mojo_repr_list_bytes':      ('char *',    ['MojoList *']),
        'mojo_repr_list_kinds':      ('char *',    ['MojoList *', 'const char *']),
        'mojo_repr_list_slotkinds': ('char *',   ['MojoList *', 'const char *']),
        'mojo_repr_boxed':           ('char *',    ['int64_t']),
        'mojo_list_get_boxed':       ('int64_t',   ['MojoList *', 'int64_t']),
        'mojo_box_double':           ('double',    ['int64_t']),
        'mojo_box_int':              ('int64_t',   ['int64_t']),
        'mojo_list_set_kinds':       ('void',      ['MojoList *', 'const char *']),
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
        'mojo_str_rfind':        ('int64_t',   ['char *', 'char *']),
        'mojo_str_rfind_from':   ('int64_t',   ['char *', 'char *', 'int64_t', 'int64_t']),
        'mojo_str_find_from':    ('int64_t',   ['char *', 'char *', 'int64_t', 'int64_t']),
        'mojo_str_cat':          ('char *',    ['char *', 'char *']),
        'mojo_str':              ('char *',    ['void *']),
        # mojo_map/mojo_filter (runtime/fire_runtime.{h,c}): `void *mojo_map(void
        # *func, void *iterable)` is a pointer-returning passthrough shim (it
        # just hands back `iterable` today — no actual per-element mapping is
        # performed at the runtime-helper level). Without this entry, the temp
        # holding the call result defaulted to int64_t (this dict's absence is
        # exactly what BUG-2026 CODEGEN_map_over_untyped_param_arg's "assignment
        # ... from void * makes integer from pointer" GCC error came from) —
        # see CODEGEN_map_over_untyped_param_arg.
        'mojo_map':              ('void *',    ['void *', 'void *']),
        'mojo_filter':           ('void *',    ['void *', 'void *']),
        'mojo_shlex_join':       ('char *',    ['MojoList *']),
        'mojo_str_isalnum':      ('int',       ['char *']),
        'mojo_str_isdigit':      ('int',       ['char *']),
        'mojo_str_isalpha':      ('int',       ['char *']),
        'mojo_str_isspace':      ('int',       ['char *']),
        'mojo_str_istitle':      ('int',       ['char *']),
        'mojo_str_isascii':      ('int',       ['char *']),
        'mojo_str_isprintable':  ('int',       ['char *']),
        'mojo_str_isnumeric':    ('int',       ['char *']),
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
        'int64_t_realpath':      ('char *',    ['char *']),  # os.path.realpath(path)
        'mojo_make_int':         ('int64_t',    ['char *']),
        'mojo_make_float':       ('double',     ['char *']),
        'mojo_make_bool':        ('int',        ['int']),   # runtime: int mojo_make_bool(int)
        'mojo_list_new':         ('MojoList *', []),
        'mojo_list_append_int':  ('void',      ['MojoList *', 'int64_t']),
        'mojo_list_append_double': ('void',    ['MojoList *', 'double']),
        'mojo_list_append_str':  ('void',      ['MojoList *', 'char *']),
        'mojo_struct_compile':      ('MojoStructFmt *', ['char *']),
        'mojo_struct_new':          ('MojoStructFmt *', ['char *']),
        'mojo_struct_calcsize':     ('int64_t',   ['char *']),
        'mojo_struct_size':         ('int64_t',   ['MojoStructFmt *']),
        'mojo_struct_format':       ('char *',    ['MojoStructFmt *']),
        'mojo_struct_pack_list':    ('MojoBytes *', ['char *', 'MojoList *']),
        'mojo_struct_pack_h':       ('MojoBytes *', ['MojoStructFmt *', 'MojoList *']),
        'mojo_struct_unpack':       ('MojoList *', ['char *', 'MojoBytes *']),
        'mojo_struct_unpack_from':  ('MojoList *', ['char *', 'MojoBytes *', 'int64_t']),
        'mojo_struct_unpack_h':     ('MojoList *', ['MojoStructFmt *', 'MojoBytes *']),
        'mojo_struct_unpack_from_h': ('MojoList *', ['MojoStructFmt *', 'MojoBytes *', 'int64_t']),
        'mojo_struct_pack_into':    ('void',      ['char *', 'MojoBytes *', 'int64_t', 'MojoList *']),
        'mojo_struct_pack_into_h':  ('void',      ['MojoStructFmt *', 'MojoBytes *', 'int64_t', 'MojoList *']),
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
        'mojo_cstr_or_int_str':  ('char *',    ['int64_t']),
        'mojo_int_str_transient': ('char *',   ['int64_t']),
        'mojo_cstr_or_int_release': ('void',   ['int64_t', 'char *']),
        'mojo_dict_new':         ('MojoDict *', []),
        'mojo_dict_set_str': ('void',      ['MojoDict *', 'char *', 'char *']),
        'mojo_dict_set_int': ('void',      ['MojoDict *', 'char *', 'int64_t']),
        'mojo_dict_get_str':     ('char *',    ['MojoDict *', 'char *']),
        'mojo_dict_get_int':     ('int64_t',   ['MojoDict *', 'char *']),
        'mojo_dict_setdefault_int': ('int64_t', ['MojoDict *', 'char *', 'int64_t']),
        'mojo_dict_setdefault_str': ('char *',  ['MojoDict *', 'char *', 'char *']),
        'mojo_dict_contains':    ('int',       ['MojoDict *', 'char *']),
        'mojo_dict_get_int_kw':     ('int64_t',  ['MojoDict *', 'int64_t']),
        'mojo_dict_get_double_kw':  ('double',   ['MojoDict *', 'int64_t']),
        'mojo_dict_get_str_kw':     ('char *',   ['MojoDict *', 'int64_t']),
        'mojo_dict_set_int_kw':     ('void',     ['MojoDict *', 'int64_t', 'int64_t']),
        'mojo_dict_set_double_kw':  ('void',     ['MojoDict *', 'int64_t', 'double']),
        'mojo_dict_set_str_kw':     ('void',     ['MojoDict *', 'int64_t', 'char *']),
        'mojo_dict_contains_kw':    ('int',      ['MojoDict *', 'int64_t']),
        'mojo_dict_pop_int_kw':     ('int64_t',  ['MojoDict *', 'int64_t', 'int64_t']),
        'mojo_dict_pop_str_kw':     ('char *',   ['MojoDict *', 'int64_t', 'char *']),
        'mojo_dict_pop_double_kw':  ('double',   ['MojoDict *', 'int64_t', 'double']),
        'mojo_dict_pop_int':        ('int64_t',  ['MojoDict *', 'char *', 'int64_t']),
        'mojo_dict_pop_str':        ('char *',   ['MojoDict *', 'char *', 'char *']),
        'mojo_dict_pop_double':     ('double',   ['MojoDict *', 'char *', 'double']),
        'mojo_dict_pop_bytes_int':  ('int64_t',  ['MojoDict *', 'MojoBytes *', 'int64_t']),
        'mojo_dict_pop_bytes_str':  ('char *',   ['MojoDict *', 'MojoBytes *', 'char *']),
        'mojo_dict_pop_bytes_double': ('double', ['MojoDict *', 'MojoBytes *', 'double']),
        'mojo_dict_setdefault_int_kw': ('int64_t', ['MojoDict *', 'int64_t', 'int64_t']),
        'mojo_dict_setdefault_str_kw': ('char *',  ['MojoDict *', 'int64_t', 'char *']),
        'mojo_replace_argv':   ('void',    ['MojoList *']),
        'mojo_is_registered_list': ('int',     ['int64_t']),
        'mojo_is_registered_dict': ('int',     ['int64_t']),
        'mojo_set_new':          ('MojoSet *', []),
        'mojo_set_add_str':      ('void',      ['MojoSet *', 'char *']),
        'mojo_set_add_int':      ('void',      ['MojoSet *', 'int64_t']),
        'mojo_set_contains_str': ('int',       ['MojoSet *', 'char *']),
        'mojo_set_contains_bytes': ('int',      ['MojoSet *', 'MojoBytes *']),
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
        # `re.Pattern.split(text)` over this codegen's own regex engine — the
        # entry point that makes fire_compiler.py's `_source_lines` (and so the
        # whole self-hosted tokenizer) work; see its own comment in
        # emit_methods.py's `<pattern>.split(...)` arm.
        'mojo_regex_split':      ('MojoList *', ['const ReNode *', 'const ReRange *',
                                                'const ReClassInfo *', 'int', 'int',
                                                'char *']),
        # Matches runtime/fire_runtime.h's own declaration exactly
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
        'mojo_set_discard_int':  ('void',      ['MojoSet *', 'int64_t']),
        'mojo_set_discard_str':  ('void',      ['MojoSet *', 'char *']),
        'mojo_str_startswith':   ('int',       ['char *', 'char *']),
        'mojo_str_startswith_from': ('int',    ['char *', 'char *', 'int64_t', 'int64_t']),
        'mojo_str_endswith':     ('int',       ['char *', 'char *']),
        'mojo_str_endswith_from':   ('int',     ['char *', 'char *', 'int64_t', 'int64_t']),
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
        'int_getcwd':            ('int64_t',   ['int64_t']),
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
        'mojo_dict_items_int':   ('MojoList *', ['MojoDict *']),
        'mojo_sorted':           ('MojoList *', ['void *']),
        'mojo_list_sorted_str':  ('MojoList *', ['MojoList *']),
        # `l.sort()`: the kind byte is a MOJO_KIND_* alphabet constant and
        # `keys` is NULL unless a `key=` built one, so the two are passed as
        # plain C text rather than as a coerced temp.
        'mojo_list_sort':        ('void', ['MojoList *', 'int', 'int', 'MojoList *']),
        'mojo_set_sorted':       ('MojoList *', ['MojoSet *']),
        'mojo_set_to_list':      ('MojoList *', ['MojoSet *']),
        'mojo_dict_sorted_keys': ('MojoList *', ['MojoDict *']),
        'mojo_dict_items_sorted': ('MojoList *', ['MojoDict *']),
        'mojo_reversed':         ('void *',     ['void *']),
        # POSIX / C stdlib functions with non-int64_t returns (util stubs table)
        # NOTE: bare `isdir` (as opposed to `int_isdir`, the real os.path.isdir
        # runtime helper just below) is intentionally NOT listed here — see
        # COMPILE_FAIL_Modules_getpath. Being "known" here forced
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
        'int_isfile':            ('int',         ['int64_t', 'int64_t']),  # os.path.isfile(path)
        'int64_t_path_split':    ('MojoList *',  ['char *']),              # os.path.split(path) -> [head, tail]
        'int64_t_path_splitdrive': ('MojoList *', ['char *']),            # os.path.splitdrive(path) -> [drive, tail]
        'int64_t_path_splitroot':  ('MojoList *', ['char *']),            # os.path.splitroot(path) -> [drive, root, tail]
        'mojo_listdir':          ('MojoList *',  ['char *']),              # os.listdir(path)
        'isatty':                ('int',         ['int']),
        'getpid':                ('int',         []),
        'getppid':               ('int',         []),
        'getuid':                ('unsigned int', []),
        'getgid':                ('unsigned int', []),
        'sysconf':               ('long',        ['int']),
        # Python's hex()/oct()/bin() builtins -- real implementations in
        # runtime/fire_runtime.c, routed here via BUILTIN_VALUE_MAP. (The
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
        'mojo_list_inherit_kinds': ('void',     ['MojoList *', 'MojoList *']),
        'mojo_list_get_kinds':     ('const char *', ['MojoList *']),
        'mojo_list_slot_kind':     ('char',     ['MojoList *', 'int64_t']),
        'mojo_is_boxed':           ('int',      ['int64_t']),
        'mojo_cstr_reverse':     ('char *',     ['char *']),
        'mojo_bytes_reverse':    ('MojoBytes *', ['MojoBytes *']),
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
        # ONE parameter, matching `def py_tokenize(src: str)` and the pinned
        # declaration in runtime/fire_runtime.h. The filename-carrying variant
        # is `py_tokenize_named(src, filename)`, an ordinary function whose arity
        # this codegen derives from its definition.
        #
        # This used to list two, describing `py_tokenize(src, filename="")` — a
        # DEFAULTED second parameter. That is right about the failure mode (a
        # defaulted parameter still occupies a slot, and the self-host
        # MATERIALIZES it at every call site, so `filename=""` is an ABI change
        # however invisible it looks in Python) and wrong about the fix, because
        # the default is gone: the function is one argument now. A two-parameter
        # entry is wrong at both ends — every caller passes one argument and the
        # C function takes one — so GCC rejected the whole self-host build with
        # ~24 x "too few arguments to function 'py_tokenize'; expected 2, have 1"
        # while fire.ci's own prototype and definition were already correct.
        #
        # `py_tokenize_named` deliberately gets NO entry here. Nothing calls it
        # from generated code (its callers are Python: formal/build.py and the
        # lexing tests), and it is not in `_NO_OVERLOAD_MANGLE`, so a generated
        # call would reach it under a mangled name that this bare-name table
        # could never match. An entry here would be an unchecked fact about an
        # unreachable name — and nothing checks this table at all: the
        # signature-vs-source test in test_gimple.py reads `_SELFHOST_SIGS`, not
        # `_LIBC_SIGS`, so the real protection for `py_tokenize` is the pinned
        # header declaration that test_selfhost.py's
        # `pinned_prototypes_match_their_definitions` checks.
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
        # `puts`: in _LIBC_DECLARED (so <stdio.h> supplies the prototype and no
        # self-extern is emitted — correct) but with no pinned signature here,
        # which left `_emit_call` nothing to coerce its argument against, so a
        # call lowered as `puts (<int64_t>)`. GCC rejects that outright
        # ("passing argument 1 of 'puts' makes pointer from integer without a
        # cast") — the stdlib's
        # test/ffi/compile_fail/test_external_call_num_fixed_args.mojo hits it.
        # Pinned as `char *` rather than `const char *`: every other entry in
        # this table uses the unqualified spelling (they are the coercion
        # targets, and a `char *` argument converts to `const char *` freely,
        # where the reverse would not).
        'puts':         ('int', ['char *']),
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
        # char_replace is a macro in fire_runtime.h — suppress conflicting stub declaration
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
        'symlink', 'readlink', 'link', 'chmod', 'chown', 'getcwd', 'chdir',
        'scalbf',
        # POSIX fd/process calls our prelude headers don't pull in → emit the
        # extern ourselves (using the _LIBC_SIGS prototype) to avoid implicit decls.
        # fcntl confirmed missing here 2026-07-15: a generic (e.g. a comptime
        # fcntl[Int]/fcntl[Int64] instantiation via monomorphize.py) compiled
        # in isolation has no <fcntl.h> in its preamble and no other call
        # site to inherit an extern from, so it hit "implicit declaration of
        # function 'fcntl'" on every cold-CAS-cache stdlib build.
        'dup', 'pipe', 'fcntl', 'close',
        # dup2: same class as `dup` immediately above, and it was simply
        # missing. `dup2` is in `_LIBC_DECLARED` (it is a real <unistd.h>
        # symbol) but <unistd.h> is NOT in this compile's prelude, so the
        # external_call path took the "the headers will declare it" branch and
        # emitted no prototype at all — while `dup`, sitting beside it in the
        # same std/sys/_libc.mojo wrapper file, did get one. Result: a module
        # whose only libc call is `dup2` compiles to a bare `dup2 (...)` and
        # GCC 15 rejects it ("implicit declaration of function 'dup2'; did you
        # mean 'dup'?"). The pinned `_LIBC_SIGS` prototype already existed.
        'dup2',
        # fork/waitpid/execv: headers (<unistd.h>/<sys/wait.h>) not in our prelude,
        # so _emit_stdlib_import_externs must not skip them (the new
        # _LIBC_DECLARED check would otherwise suppress them).
        'fork', 'waitpid', 'execv',
        # execve: same class, found via Lib/os.py's own body — execl/execle
        # call this BARE name (real Python gets it from the C posix module),
        # and with no visible prototype every call site was an implicit
        # declaration plus pointer-coercion mismatches against GCC's builtin
        # knowledge. Deliberately NOT 'unsetenv': <stdlib.h> IS in the
        # prelude and already declares it — a self-emitted
        # `int unsetenv(char *)` there conflicts with the header's
        # `int unsetenv(const char *)`; unsetenv needed only the pinned
        # _LIBC_SIGS entry (argument coercion), not a prototype.
        'execve',
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
        'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown', 'chdir',
        'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork',
        'ioctl', 'fcntl', 'dup', 'dup2', 'pipe', 'close',
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
        # runtime/fire_async_runtime.h — already declared there (included in
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
        # runtime/fire_async_runtime.h's own honest-synchronous-simplification
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
        # POSIX file/env calls whose headers our prelude lacks (see
        # _NEEDS_SELF_EXTERN): pin the signatures so bare calls (Lib/os.py's
        # own wrappers) both coerce their int64_t-lowered args and get a
        # self-emitted extern instead of an implicit declaration.
        'mkdir': ('int', ['char *', 'int']),
        'rmdir': ('int', ['char *']),
        # POSIX fd close (<unistd.h>, not in prelude) — used bare inside
        # Lib/os.py's `_fwalk` generator via `from posix import *`.
        'close': ('int', ['int']),
        # POSIX path ops (<unistd.h>, not in prelude) — reached bare via
        # os_helper.unlink(...) / similar `from os import *`-style
        # bindings inside a compiled generator (Lib/test/libregrtest/
        # save_env.py's restore_urllib_requests__url_tempfiles).
        'unlink': ('int', ['char *']),
        'symlink': ('int', ['char *', 'char *']),
        'readlink': ('int64_t', ['char *', 'char *', 'int64_t']),
        'link': ('int', ['char *', 'char *']),
        'chdir': ('int', ['char *']),
        'execve': ('int', ['char *', 'char *', 'char *']),
        'unsetenv': ('int', ['char *']),
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
        'MojoBytes *': 'mojo_bytes_len',
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
        # Self-hosting bootstrap: gimple_module_gen.py's `from gimple_codegen
        # import _merge_struct_inheritance, _compute_exc_descendants` — the
        # `gimple_codegen` `.py` sibling isn't resolvable by module_loader,
        # so the call sites can't learn a mangled suffix that matches the
        # definition. Both are single-definition helpers with no overloads;
        # pinning the bare C name (plus a concrete forward decl in
        # gen_module's `_is_selfhost_file` block) makes call and definition
        # agree without any cross-module signature negotiation.
        '_merge_struct_inheritance', '_compute_exc_descendants',
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
    def _lower_maybe_bound_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return gmp._lower_maybe_bound_call(self, fname_raw, node)
    def _lower_builtin_method_value(self, ot: str, ov: str, method: str) -> tuple[str, str]:
        return gmp._lower_builtin_method_value(self, ot, ov, method)
    def _lower_builtin_bound_method_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        return gmp._lower_builtin_bound_method_call(self, fname_raw, node)
    def _lower_method_call(self, node: CallExpr) -> tuple[str, str]:
        return gmp._lower_method_call(self, node)
    def _lower_dict_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_dict_method(self, ov, method, args)
    def _lower_list_method(self, ov: str, method: str, args: list,
                           kwargs: list = None) -> tuple:
        return gmp._lower_list_method(self, ov, method, args, kwargs)
    def _lower_set_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_set_method(self, ov, method, args)
    def _lower_pointer_method(self, ov: str, ot: str, method: str, args: list) -> tuple:
        return gmp._lower_pointer_method(self, ov, ot, method, args)
    def _lower_file_method(self, ov: str, method: str, args: list) -> tuple:
        return gmp._lower_file_method(self, ov, method, args)
    def _lower_str_method(self, ov: str, method: str, args: list, kwargs=None) -> tuple:
        return gmp._lower_str_method(self, ov, method, args, kwargs)
    def _lower_bytes_method(self, ov: str, method: str, args: list, kwargs=None) -> tuple:
        return gmp._lower_bytes_method(self, ov, method, args, kwargs)
    def _lower_memoryview_method(self, ov: str, method: str, args: list, kwargs=None) -> tuple:
        return gmp._lower_memoryview_method(self, ov, method, args, kwargs)
    def _repack_method_call_spread_args(self, mangled: str, struct_name: str, method: str, call_args: list, arg_pairs: list) -> list:
        return gmp._repack_method_call_spread_args(self, mangled, struct_name, method, call_args, arg_pairs)
    def _lower_struct_method_call(self, ov: str, ot: str, method: str, node) -> tuple:
        return gmp._lower_struct_method_call(self, ov, ot, method, node)


    # ---- delegates: calls family (bodies in gimple_gen_calls.py) ----

    def _ident_call_name(self, func_node) -> str:
        return ggc._ident_call_name(self, func_node)
    def _lower_call(self, node: CallExpr) -> tuple[str, str]:
        _ct, _cv = ggc._lower_call(self, node)
        # A call to a module function proven to return a brand-new container
        # (analysis_funcs / analyze_returns_fresh): its result is fresh for
        # whoever binds or consumes it. Not when the name is a local of this
        # function (a function pointer / parameter shadowing the module name).
        if (isinstance(node.func, IdentExpr) and node.func.name in self._fresh_returning
                and node.func.name not in self.var_types):
            self._fresh_vals.add(_cv)
        # A constructor call of a struct the ownership analysis vetted
        # (infra_infer._build_analysis_structs) builds a brand-new instance.
        if (isinstance(node.func, IdentExpr) and node.func.name in self._analysis_structs
                and node.func.name not in self.var_types):
            self._fresh_vals.add(_cv)
        return _ct, _cv

    def _lower_pointer_alloc(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_pointer_alloc(self, node)

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

    def _lower_builtin_reversed(self, node: CallExpr) -> tuple[str, str]:
        return ggc._lower_builtin_reversed(self, node)

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

    def _default_expr_to_pair(self, _dflt, cxx: bool = False, param_ctype=None) -> tuple:
        return ggc._default_expr_to_pair(self, _dflt, cxx=cxx, param_ctype=param_ctype)

    def _pack_vararg_trailing_params(self, fname, fname_raw, arg_pairs, kwarg_dict, call_has_spread=False):
        return ggc._pack_vararg_trailing_params(self, fname, fname_raw, arg_pairs, kwarg_dict, call_has_spread)

    def _expand_sole_spread_into_fixed_slots(self, node, fname, fname_raw, arg_pairs, expected_params):
        return ggc._expand_sole_spread_into_fixed_slots(self, node, fname, fname_raw, arg_pairs, expected_params)

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

    def _lower_struct_constructor(self, struct_name: str, args: list, kwargs: list=None) -> tuple[str, str]:
        return ggc._lower_struct_constructor(self, struct_name, args, kwargs)

    def _array_field_elem_ptr(self, member_expr) -> tuple[str, str] | None:
        return ggc._array_field_elem_ptr(self, member_expr)

    def _struct_data_field(self, ctype: str):
        return ggc._struct_data_field(self, ctype)

    def _dict_subclass_of(self, ctype: str) -> str:
        return ggc._dict_subclass_of(self, ctype)

    def _bytes_subclass_of(self, ctype: str) -> str:
        return ggc._bytes_subclass_of(self, ctype)

    def _coerce_to_bytes(self, t: str, v: str) -> str:
        return gmp._coerce_to_bytes(self, t, v)

    def _struct_defines_method(self, sn: str, mname: str) -> bool:
        return ggc._struct_defines_method(self, sn, mname)

    def _dict_subclass_defines(self, sn: str, method: str) -> bool:
        return ggc._dict_subclass_defines(self, sn, method)

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

    def _gen_stmt_NonlocalStmt(self, node):
        return gfn._gen_stmt_NonlocalStmt(self, node)
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
    def overload_suffix_for(c_param_types) -> str:
        return gfn.overload_suffix_for(c_param_types)
    def _overload_suffix(self, bare_name: str) -> str:
        return gfn._overload_suffix(self, bare_name)
    def _note_own_func_home(self, bare_name: str, module_name: str, record_scope: bool=True) -> None:
        return gfn._note_own_func_home(self, bare_name, module_name, record_scope)
    def _func_return_type_for_call(self, bare_name: str, default: str = 'int64_t') -> str:
        """`func_return_types[bare_name]`, unless the module this reference
        resolves to PUBLISHED its own answer for that definition, which wins.

        `func_return_types` is keyed by the BARE name and a whole-translation-
        unit closure routinely has several modules defining one bare name with
        different return types, so its single slot holds one arbitrary module's
        answer. An INFERENCE reader is as exposed to that as emission is, and
        the exposure compounds: `def found(x): return _mentions(x, 'b')` infers
        `found`'s own return type from whatever `_mentions` the shared slot
        holds, so the wrong answer does not stay confined to the colliding
        pair — it propagates into every function that forwards the call. The
        per-definition store (`_home_def_return_types`) is what stops it, and
        this is the one place a caller with no emitted symbol in hand can reach
        it.

        Reads the store through `_func_home_qualifier`, which never raises: an
        ambiguous reference has no definition of its own to consult, so `''` is
        the honest "no answer" and the bare slot remains the fallback.
        """
        _hit = gfn._home_def_return_type(
            self, gfn._func_home_qualifier(self, bare_name), bare_name)
        if _hit is not None:
            return _hit
        return self.func_return_types.get(bare_name, default)
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
    def _own_overlay_global_ctype(self, name: str) -> str | None:
        """Resolve global `name`'s C type from THIS instance's own overlay
        (`_own_global_var_types`), or return None when this instance never
        recorded a conclusion for it. Shared helper for BOTH global-type
        consumers that must agree with each other — the assignment-site
        destination coercion (`_global_dst_ctype`) and the module-globals
        struct field declaration (gen_module_impl's `_declared_globals`
        loop) — so a cross-module same-bare-name homonym can never make
        one side coerce/store with a different type than the other side
        declared (the observed c_analyzer/info.py failure: root's
        `UNKNOWN = _misc.Labeled('UNKNOWN')` frozen int64_t by its own
        scan, then c_common/tables.py's string `UNKNOWN = '???'` landed
        'char *' in the SHARED `_global_c_decl_types` between root's
        field-freeze step and root's body-emission step, and the
        assignment coerced its RHS to `char *` against the already
        frozen `int64_t UNKNOWN` field).

        Resolution rules, in order:
        1. A CONTAINER-pointer entry in the shared cdecl dict
           (`MojoDict *`/`MojoList *`/`MojoSet *` — the
           `dispatch_table_global_ctype` dispatch-table registrations and
           boxed containers) still wins over a scalar own-conclusion exactly
           as before: those name compiler-internal tables whose real boxed
           pointer representation this codegen must preserve even when the
           owning module's own scan froze an int64_t placeholder.
        2. Otherwise a SCALAR own-conclusion (`int64_t`, `double`,
           `_Bool`, `char *`) wins unconditionally — including over a
           foreign homonym's NON-container pointer cdecl ('char *',
           struct pointers). This is the narrowing that fixes the
           homonym class: the old code deferred to ANY pointer-shaped
           cdecl, so a foreign module's string global silently
           re-typed this module's own assignment.
        3. A non-scalar own-conclusion (a real pointer the overlay
           recorded itself — e.g. gen_module_impl's late reconcile loop
           mirrors widened callee-return pointer types into the overlay)
           defers to the shared cdecl when one exists, else uses its own
           value — byte-for-byte the prior behavior.
        4. A non-dispatch CONTAINER own-conclusion (`MojoDict *` /
           `MojoList *` / `MojoSet *`) boxes to `int64_t` even when a
           shared cdecl entry exists, PROVIDED that entry is not itself a
           container pointer. Rule 1 already handled the container-cdecl
           case (dispatch tables); this rule handles the one it could
           not, which is the SAME homonym class rule 2 fixes, read from
           the other side.

           Rule 2 narrows "a foreign homonym's pointer cdecl must not
           re-type this module's own SCALAR conclusion". Its exact
           mirror — "a foreign homonym's pointer cdecl must not re-type
           this module's own CONTAINER conclusion" — was missing, and it
           is not reachable by narrowing: a container own-conclusion
           falls straight past rule 2 (own is not a scalar) into rule 3,
           which deferred to ANY shared cdecl. So the one entry that
           could re-type it was a foreign module's NON-container cdecl.

           That is the Tools/c-analyzer shape: `c_analyzer/info.py`'s own
           `UNKNOWN = _misc.Labeled('UNKNOWN')` is boxed `int64_t` on
           `UNKNOWN`'s field, while `c_common/tables.py`'s unrelated
           `UNKNOWN = '???'` cdecl'd `'char *'` into the shared dict.
           Every consumer of this helper then disagreed with the frozen
           field, in both directions at once: `_global_dst_ctype`
           (assignment sites) coerced the RHS to `char *`, and
           `_lower_IdentExpr` loaded the `int64_t` field through a
           `char *` temp — 4 x "assignment to 'int64_t' from 'char *'
           makes integer from pointer without a cast" plus 6 x
           "non-trivial conversion in 'component_ref'" (bugs/
           COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md).

           The guard is `cdecl` NOT a container pointer rather than
           `cdecl is None`, because a non-container shared cdecl can only
           be a foreign homonym's conclusion or the `int64_t` box the
           convention writes when `_gscan_declare_global` DID run — and
           both mean the same boxed `int64_t` field this rule returns, so
           keying on "not a container pointer" is what makes the
           assignment site, the field freeze, and the read agree
           regardless of WHICH module happened to be scanned first."""
        own = self._own_global_var_types.get(name)
        if own is None:
            return None
        cdecl = self._global_c_decl_types.get(name)
        if (cdecl is not None and cdecl.endswith(' *')
                and cdecl in ('MojoDict *', 'MojoList *', 'MojoSet *')):
            return cdecl
        if own in ('int64_t', 'double', '_Bool', 'char *'):
            return own
        if (own in ('MojoDict *', 'MojoList *', 'MojoSet *')
                and not (cdecl is not None
                         and cdecl in ('MojoDict *', 'MojoList *', 'MojoSet *'))
                and dispatch_table_global_ctype(name) is None):
            # A NON-dispatch CONTAINER own-conclusion whose shared cdecl is
            # absent OR non-container: the module-global C struct-field
            # convention boxes these as `int64_t`. Returning the raw container
            # type here declared `MojoList * arr` for a plain
            # `arr = [1,2,3]` on the self-hosted compiled path — where
            # `_gscan_declare_global`'s ListExpr branch didn't run to set the
            # cdecl — vs stage1's boxed `int64_t arr` (array_ops_jit parity
            # under MOJO_NO_SHIM=1); and a FOREIGN module's non-container
            # cdecl under the same bare name re-typed this module's own
            # container global (rule 4 above). The hardcoded dispatch tables
            # keep the bare pointer and are excluded (their
            # `_gscan_declare_global` branch, when it runs, DOES set the
            # cdecl; when it doesn't, this exclusion preserves the
            # pre-existing raw-type return).
            return 'int64_t'
        return cdecl if cdecl is not None else own

    def _module_global_field_type(self, module: str, name: str) -> tuple[str, str] | None:
        """The `(c_type, mojo_type)` that module `module`'s OWN globals struct
        declares for `name`, or None when that module declares no such field.

        The per-module counterpart to `_own_overlay_global_ctype`, and needed
        for the same reason with the same limitation fixed: that helper answers
        "what type does THIS instance's own overlay conclude", which is the
        right question for a BARE name (only ever this module's global). It
        cannot answer the `submod.NAME` question, because there the field
        belongs to a DIFFERENT module and this instance's overlay says nothing
        about it.

        `_module_globals[mod]` already holds the answer as its
        `(name, c_type, g_mtype)` triples — it is the exact list the struct
        typedef, the initializer, and the `_<mod>_mojo_global_get_<name>`
        accessors are all generated from, so consulting it guarantees the read
        agrees with the field by construction rather than by a second,
        independently-drifting inference.

        Without it, `submod.NAME` resolved the FIELD module-correctly (via
        `_global_to_module`) but took the TYPE from the shared, name-keyed
        `_global_var_types`, i.e. whichever of two same-named globals was
        scanned first. Two modules each declaring their own `MARKER` — a list
        in one, a string in the other — then read the *string* field through an
        `int64_t` temp: "assignment to 'int64_t' from 'char *' makes integer
        from pointer without a cast". The bare-name half of that same pair is
        `_own_overlay_global_ctype`; this is the qualified half, and both are
        needed or the two spellings of one name disagree.

        Compared elementwise through `_as_str` like every other consumer of
        `_module_globals`, since a tuple lowers to a MojoList on the
        self-hosted compiled path and `==` would compare handles."""
        entries = self._module_globals.get(module)
        if not entries:
            return None
        from mojo.middle.module_shared import _as_str
        for entry in entries:
            if _as_str(entry[0]) == name:
                return _as_str(entry[1]), _as_str(entry[2])
        return None

    def _global_dst_ctype(self, name: str) -> str:
        """The destination C type for an assignment to a bare-name module
        global: THIS instance's own-overlay conclusion when it has one
        (see `_own_overlay_global_ctype`), else the shared-dict chain the
        four global-assignment emission sites in gimple_gen_stmts.py used
        to inline as `_global_c_decl_types.get(name, _global_var_types[
        name])`. The shared dicts are keyed by bare name across every
        module compiled together, so a later-scanned module declaring the
        same bare name (tokenize.py vs io.py/inspect.py's `__author__`,
        tarfile.py vs token.py's `ENCODING`) would otherwise make this
        module's own assignment coerce its RHS to the OTHER module's type
        (the observed "assignment to 'char *' from 'int64_t'" family)."""
        own_t = self._own_overlay_global_ctype(name)
        if own_t is not None:
            return own_t
        return self._global_c_decl_types.get(name, self._global_var_types.get(name, 'int64_t'))
    def _locally_binds_name(self, bare_name: str) -> bool:
        return gfn._locally_binds_name(self, bare_name)
    def _func_mangleable(self, name: str) -> bool:
        return gfn._func_mangleable(self, name)
    def _func_csym(self, bare_name: str) -> str:
        return gfn._func_csym(self, bare_name)
    def _c_sizeof_helper(self, struct_name: str) -> str:
        """Name of a `static int64_t` accessor returning `sizeof(struct_name)`,
        registering it for emission into the non-GIMPLE prelude.

        Needed because `sizeof` is not a valid GIMPLE primary expression: a
        `__GIMPLE` body writing `_p = malloc (sizeof(S));` is rejected with
        "expected expression before 'sizeof'". The size has to come from
        somewhere real C can compute, and a gimple call to an ordinary `static`
        function is a valid operand. Returns the helper's name.
        """
        hname = '_mojo_sizeof_' + struct_name
        if hname not in self._c_helpers_needed:
            self._c_helpers_needed[hname] = (
                f'static int64_t {hname} (void) '
                f'{{ return (int64_t)sizeof({struct_name}); }}')
        return hname
    def _c_fnaddr_helper(self, func_name: str) -> str:
        """Name of a `static void *` accessor returning `(void *)func_name`,
        registering it for emission into the non-GIMPLE prelude.

        Needed because casting a function designator is not a valid GIMPLE
        operand: `_p = (void *)some_fn;` inside a `__GIMPLE` body is rejected
        with "invalid operand in unary operation", and the same cast as a
        gimple call argument is rejected as "invalid argument to gimple call".
        Returns the helper's name.
        """
        hname = '_mojo_fnaddr_' + func_name
        if hname not in self._c_helpers_needed:
            self._c_helpers_needed[hname] = (
                f'static void * {hname} (void) '
                f'{{ return (void *){func_name}; }}')
        return hname
    def _c_helper_def(self, hname: str) -> str:
        """The full C definition of a registered helper, or '' if this
        translation unit already has it.

        Emitted inline at the single point that needs it, which is what keeps
        it correctly ordered against both the caller and the struct typedefs
        the body refers to — see `_c_helpers_needed`'s docstring for why there
        is no single flush point that satisfies both.
        """
        if hname in self._emitted_c_helpers:
            return ''
        src = self._c_helpers_needed.get(hname)
        if not src:
            return ''
        self._emitted_c_helpers.add(hname)
        return src
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
    def _find_symbol_home_module(self, module: str, name: str, kind: str,
                                 depth: int = 0, want_abs: bool = False):
        return gfn._find_symbol_home_module(self, module, name, kind,
                                           depth=depth, want_abs=want_abs)
    def _register_imported_symbol(self, name: str, info, original_name=None,
                                  write_param_types: bool = True):
        import mojo.middle.funcs_shared as _fn2
        return _fn2.register_imported_symbol(self, name, info, original_name,
                                            write_param_types)
    def _resolved_export_entry(self, module: str, name: str, info):
        return gfn._resolved_export_entry(self, module, name, info)
    def _resolve_test_relative_module(self, module: str) -> str | None:
        return gfn._resolve_test_relative_module(self, module)
    def _parsed_import(self, module: str):
        return gfn._parsed_import(self, module)
    def _note_struct_import_alias(self, module: str, alias: str, orig_name: str):
        return gfn._note_struct_import_alias(self, module, alias, orig_name)
    def _note_struct_attr_alias(self, module: str, alias: str, member: str):
        return gfn._note_struct_attr_alias(self, module, alias, member)
    def _local_sibling_module_exports(self, module: str):
        return gfn._local_sibling_module_exports(self, module)
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
    def _struct_method_overload_ids(stmt) -> list:
        return gfn._struct_method_overload_ids(stmt)
    def _struct_method_qualifier(self, struct_name: str) -> str:
        return gfn._struct_method_qualifier(self, struct_name)
    def _struct_method_csym(self, struct_name: str, method_name: str, overload_id: str='') -> str:
        return gfn._struct_method_csym(self, struct_name, method_name, overload_id)
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
    def _gen_for_zip(self, node):
        return glo._gen_for_zip(self, node)
    def _gen_for_zip_longest(self, node):
        return glo._gen_for_zip_longest(self, node)
    def _gen_for_list(self, var: str, it_val: str, body: list, shadow_name: str | None=None,
                       share_var_with_sibling_arm: bool=False):
        return glo._gen_for_list(self, var, it_val, body, shadow_name, share_var_with_sibling_arm)
    def _gen_for_str(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_str(self, var, it_val, body, shadow_name)
    def _gen_for_cstr(self, var: str, it_val: str, body: list):
        return glo._gen_for_cstr(self, var, it_val, body)
    def _gen_for_bytes(self, var: str, it_val: str, body: list):
        return glo._gen_for_bytes(self, var, it_val, body)
    def _gen_for_memoryview(self, var: str, it_val: str, body: list):
        return glo._gen_for_memoryview(self, var, it_val, body)
    def _gen_for_dict(self, var: str, it_val: str, body: list, shadow_name: str | None=None, int_keys: bool=False):
        return glo._gen_for_dict(self, var, it_val, body, shadow_name, int_keys)
    def _gen_for_set(self, var: str, it_val: str, body: list, shadow_name: str | None=None):
        return glo._gen_for_set(self, var, it_val, body, shadow_name)
    def _gen_lifted_closure(self, ci: ClosureInfo, outer_name: str=None) -> str:
        return glo._gen_lifted_closure(self, ci, outer_name)
    def _emit_generator_tuple_unpack(self, var_names: list, slot_types: list, list_ptr: str, nested_flags: list | None=None) -> None:
        return glo._emit_generator_tuple_unpack(self, var_names, slot_types, list_ptr, nested_flags)
    def _gen_for_generator_iter(self, var: str, gen_val: str, api: dict, body: list, destroy_after: bool=True):
        return glo._gen_for_generator_iter(self, var, gen_val, api, body, destroy_after)
    def _emit_generator_pending_exc_check(self, gen_val: str, base: str, destroy_after: bool, bb_not_pending: str):
        return glo._emit_generator_pending_exc_check(self, gen_val, base, destroy_after, bb_not_pending)
    def _gen_for_struct_iter(self, var: str, struct_type: str, obj_val: str, body: list, shadow_name: str | None=None, node=None):
        return glo._gen_for_struct_iter(self, var, struct_type, obj_val, body, shadow_name, node)

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
    def _annotation_dict_nested_val_type(self, ann) -> str | None:
        return gst._annotation_dict_nested_val_type(self, ann)
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
    def _seed_genexp_list_narrowing(self, func_node):
        return gst._seed_genexp_list_narrowing(self, func_node)
    def _gen_stmt_AugAssignStmt(self, node):
        return gst._gen_stmt_AugAssignStmt(self, node)
    def _gen_stmt_ReturnStmt(self, node):
        return gst._gen_stmt_ReturnStmt(self, node)
    def _ensure_bool_cond(self, ctype: str, val: str) -> str:
        return gst._ensure_bool_cond(self, ctype, val)
    def _narrow_key_for_expr(self, e) -> str:
        return gst._narrow_key_for_expr(self, e)
    def _isinstance_narrow_struct(self, type_arg) -> str:
        return gst._isinstance_narrow_struct(self, type_arg)
    def _collect_isinstance_narrowings(self, cond, out: list) -> None:
        return gst._collect_isinstance_narrowings(self, cond, out)
    def _apply_isinstance_narrowings(self, cond) -> dict:
        return gst._apply_isinstance_narrowings(self, cond)
    def _restore_isinstance_narrowings(self, saved: dict) -> None:
        return gst._restore_isinstance_narrowings(self, saved)
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
    def _emit_except_handler(self, handler, node, bb_after: str):
        return gst._emit_except_handler(self, handler, node, bb_after)
    def _loop_continue_bb(self) -> str:
        return gst._loop_continue_bb(self)
    def _loop_break_bb(self) -> str:
        return gst._loop_break_bb(self)
    def _gen_stmt_TryStmt(self, node):
        return gst._gen_stmt_TryStmt(self, node)
    def _gen_stmt_WithStmt(self, node):
        return gst._gen_stmt_WithStmt(self, node)

    # ---- delegates via gex ----
    def _lower_strided(self, node, store: bool):
        return gex._lower_strided(self, node, store)
    def lower_expr(self, node) -> tuple[str, str]:
        _lt, _lv = gex.lower_expr(self, node)
        # The declaration being lowered wants to know which temp its right-hand
        # side produced (emit_infra.maybe_push_owned_local checks it for
        # freshness); the top-level RHS node is the one to remember.
        if node is self._decl_value_node:
            self._decl_rhs_val = _lv
        # A call to a function that RETURNS A CALLABLE (`def mk(): return
        # lambda: False`) carries that callable's return type on the node,
        # for the `mk()(...)` callee branch in `_lower_call` to read. The
        # value-keyed `_callable_ret_types` cannot serve there: the result is
        # cast into a fresh temp before the outer call sees it.
        #
        # The table is keyed by the name the DEF's body was generated under,
        # and for a NESTED `def` that is the LIFTED symbol
        # `f'{current_func_name}_{fname}'` — `gen.current_func_name` is
        # `main_outer_str` while a `def outer_str` inside `main` is being
        # generated — while the call site spells the bare `outer_str`. So the
        # bare lookup alone silently loses the answer for every factory
        # defined inside a function, and the second lookup uses
        # `_lower_closure_call`'s OWN composition, which is the string the
        # call it precedes goes on to emit. Measured: `def main(): def
        # outer(): s = 'x'; return (lambda: s)` then `outer()()` printed the
        # `char *`'s own decimal address where the identical factory at
        # MODULE scope printed `x` — nothing about the nested scope's codegen
        # differs except this key.
        if isinstance(node, CallExpr) and isinstance(node.func, IdentExpr):
            _fname = _as_str(node.func.name)
            _frt = self._return_callable_ret_types.get(_fname)
            if _frt is None and _fname in getattr(self, '_closure_envs', ()):
                _frt = self._return_callable_ret_types.get(
                    f'{self.current_func_name}_{_fname}')
            if _frt:
                node._callable_ret = _frt
        return _lt, _lv
    def _lower_IntLiteral(self, node) -> tuple[str, str]:
        return gex._lower_IntLiteral(self, node)
    def _lower_FloatLiteral(self, node) -> tuple[str, str]:
        return gex._lower_FloatLiteral(self, node)
    def _lower_BoolLiteral(self, node) -> tuple[str, str]:
        return gex._lower_BoolLiteral(self, node)
    def _lower_EllipsisLiteral(self, node) -> tuple[str, str]:
        return gex._lower_EllipsisLiteral(self, node)

    def _lower_DottedLiteral(self, node) -> tuple[str, str]:
        return gex._lower_DottedLiteral(self, node)
    def _lower_StringLiteral(self, node):
        return gex._lower_StringLiteral(self, node)
    def _lower_TstringLiteral(self, node) -> tuple[str, str]:
        return gex._lower_TstringLiteral(self, node)
    def _lower_IdentExpr(self, node: IdentExpr) -> tuple[str, str]:
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
    def _cpp_build_container_from_iterable(self, kind: str, iter_node, target_name: str, elem_node, cond_nodes: list) -> str:
        return gcc_._cpp_build_container_from_iterable(self, kind, iter_node, target_name, elem_node, cond_nodes)
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
    def _reset_func(self, body: list=None, params: list=None,
                    allow_lambda_reduction: bool=True):
        return ginf._reset_func(self, body, params, allow_lambda_reduction)
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
    def _dict_val_is_known(self, name: str) -> bool:
        return ginf._dict_val_is_known(self, name)
    def _dict_val_of_expr(self, expr) -> str:
        return ginf._dict_val_of_expr(self, expr)
    def _dict_union_val_type(self, lv, rv) -> str:
        return ginf._dict_union_val_type(self, lv, rv)
    def _operand_is_dict(self, node, t: str, v=None) -> bool:
        return grsl._operand_is_dict(self, node, t, v)
    def _prepare_analysis_funcs(self, stmts: list) -> None:
        self._analysis_funcs = ginf._build_analysis_funcs(stmts)
        self._analysis_structs = ginf._build_analysis_structs(stmts)
        self._fresh_returning = ginf._build_fresh_returning(self._analysis_funcs, self._analysis_structs)
    def _emit_container_new(self, t: str, ctype: str) -> None:
        return ginf.emit_container_new(self, t, ctype)
    def _note_fresh_result(self, t: str) -> None:
        return ginf.note_fresh_result(self, t)
    def _is_fresh_container_operand(self, node, val: str) -> bool:
        return ginf.is_fresh_container_operand(self, node, val)
    def _free_fresh_container(self, val: str, ctype: str) -> None:
        return ginf.free_fresh_container(self, val, ctype)
    def _claim_loop_iterable_temp(self, node, val: str, ctype: str) -> None:
        return ginf.claim_loop_iterable_temp(self, node, val, ctype)
    def _gen_loop_body(self, body: list) -> None:
        return ginf.gen_loop_body(self, body)
    def _emit_str_cat(self, lv: str, rv: str, free_left: bool=False, free_right: bool=False) -> str:
        return ginf._emit_str_cat(self, lv, rv, free_left, free_right)
    def _is_fresh_operand(self, node, val: str) -> bool:
        return ginf._is_fresh_operand(self, node, val)
    def _emit_call(self, ret_type: str, result_var: str, fname: str, arg_pairs: list[tuple[str, str]],
                    arg_nodes: list = None) -> None:
        return ginf._emit_call(self, ret_type, result_var, fname, arg_pairs, arg_nodes)
    def _emit_dict_int_value_store(self, dict_val: str, key_ctype: str, key_val: str,
                                   val_ctype: str, val: str, val_node) -> None:
        return ginf.emit_dict_int_value_store(self, dict_val, key_ctype, key_val,
                                              val_ctype, val, val_node)
    def _declared_int_ctype(self, val: str) -> str | None:
        return ginf._declared_int_ctype(self, val)
    def _ensure_local(self, ctype: str, val: str) -> str:
        return ginf._ensure_local(self, ctype, val)
    def _char_to_cstr(self, typ: str, val: str, transient: bool=False, word_ok: bool=False) -> tuple[str, str]:
        return ginf._char_to_cstr(self, typ, val, transient, word_ok)
    def _resolve_type(self, ann: str | None) -> str:
        return ginf._resolve_type(self, ann)
    def _infer_param_types(self, func: FunctionDef,
                           owner_struct: str | None = None) -> dict[str, str]:
        return ginf._infer_param_types(self, func, owner_struct)
    def _declare_var(self, name: str, ctype: str, elem: str | None=None, force: bool=False):
        return ginf._declare_var(self, name, ctype, elem, force)
    def _write_dest(self, name: str) -> str:
        return ginf._write_dest(self, name)
    def _seed_mut_captured_local_types(self, func_name: str):
        return ginf._seed_mut_captured_local_types(self, func_name)
    def _plan_mut_captured_params(self, node, func_name: str):
        return ginf._plan_mut_captured_params(self, node, func_name)
    def _seed_addressed_locals(self, body: list):
        return ginf._seed_addressed_locals(self, body)
    def _emit_mut_local_box_allocs(self):
        return ginf._emit_mut_local_box_allocs(self)
    def _new_jbp_temp(self) -> str:
        return ginf._new_jbp_temp(self)
    def _closure_info_for_ident(self, name: str):
        return ginf._closure_info_for_ident(self, name)
    def _generator_value_ctype_for_next(self, arg):
        return ginf._generator_value_ctype_for_next(self, arg)
    def _collect_return_types(self, stmts: list, acc: list):
        return ginf._collect_return_types(self, stmts, acc)
    def _coerce_to_type(self, src_type: str, dst_type: str, value: str) -> str:
        return ginf._coerce_to_type(self, src_type, dst_type, value)
    def _materialize_as_list(self, src_type: str, value: str) -> str:
        return ginf._materialize_as_list(self, src_type, value)
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
    def _list_repr_call(self, key: str, lst: str | None = None) -> tuple[str, list]:
        return ginf._list_repr_call(self, key, lst)
    def _stringify_value(self, et: str, ev: str, enode=None) -> str:
        return ginf._stringify_value(self, et, ev, enode)
    def _apply_fstring_spec(self, part_val: str, spec: str) -> str:
        return ginf._apply_fstring_spec(self, part_val, spec)
    def _subst_in_value(self, v, mapping: dict):
        return ginf._subst_in_value(self, v, mapping)
    def _is_known_field(self, member: str) -> bool:
        return ginf._is_known_field(self, member)
    def _known_field_elem_type(self, member: str) -> str | None:
        return ginf._known_field_elem_type(self, member)
    def _known_field_nested_elem_type(self, member: str) -> str | None:
        return ginf._known_field_nested_elem_type(self, member)
    def _known_field_type(self, member: str) -> str | None:
        return ginf._known_field_type(self, member)
    def _try_lower_slice_region_eq(self, slice_node, other_node, negate: bool):
        return ginf._try_lower_slice_region_eq(self, slice_node, other_node, negate)
    def _sprintf_one(self, c_spec: str, arg_val: str) -> str:
        return ginf._sprintf_one(self, c_spec, arg_val)
    def _sprintf_n(self, c_spec: str, arg_vals: list) -> str:
        return ginf._sprintf_n(self, c_spec, arg_vals)
    def _to_c_int_arg(self, ctype: str, val: str) -> str:
        return ginf._to_c_int_arg(self, ctype, val)
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

    def _compr_cursor_loop(self, node, gen0, res, res_type, rec):
        return ginf._compr_cursor_loop(self, node, gen0, res, res_type, rec)
    def _compr_generator_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_generator_loop(self, node, gen0, res, res_type, it_val)
    def _compr_dict_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_dict_loop(self, node, gen0, res, res_type, it_val)
    def _compr_set_loop(self, node, gen0, res, res_type, it_val):
        return ginf._compr_set_loop(self, node, gen0, res, res_type, it_val)
    def _gen_print(self, args: list, kwargs: list=None):
        return ginf._gen_print(self, args, kwargs)
    def _note_container_callable_ret(self, container_val: str, value_text: str,
                                     value_ctype: str = 'int64_t',
                                     value_node=None) -> None:
        return ginf.note_container_callable_ret(self, container_val, value_text,
                                                value_ctype, value_node)
    def _emit_dict_int_value_store(self, dict_val: str, key_ctype: str,
                                   key_val: str, val_ctype: str, val: str,
                                   val_node=None) -> None:
        return ginf.emit_dict_int_value_store(self, dict_val, key_ctype, key_val,
                                              val_ctype, val, val_node)
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
    def _inc_val(self, base: str) -> str:
        return grsl._inc_val(self, base)
    def _call_expr(self, ret_type: str, fname: str, arg_pairs: list, arg_nodes: list = None) -> str:
        return grsl._call_expr(self, ret_type, fname, arg_pairs, arg_nodes)
    def _bool_not(self, ctype: str, val: str) -> str:
        return grsl._bool_not(self, ctype, val)
    def _bool_and(self, left: str, right: str) -> str:
        return grsl._bool_and(self, left, right)
    def _void_call(self, fname: str, arg_pairs: list) -> tuple:
        return grsl._void_call(self, fname, arg_pairs)
    def _emit_label(self, label: str, freq_hint: str=''):
        return grsl._emit_label(self, label, freq_hint)
    def _scalar_arg_is_addressable_local(self, aval) -> bool:
        return ginf._scalar_arg_is_addressable_local(self, aval)
    def _addressable_to_target(self, ctype: str, aval: str) -> bool:
        return ginf._addressable_to_target(self, ctype, aval)
    def _strided_data_ptr(self, pt: str, pv: str) -> str:
        return grsl._strided_data_ptr(self, pt, pv)
    def _safe_coerce_emit(self, src: str, dst: str, val: str, lhs: str) -> None:
        return grsl._safe_coerce_emit(self, src, dst, val, lhs)
    def _cname(self, name: str) -> str:
        return grsl._cname(self, name)
    def _param_safe_name(self, bare: str) -> str:
        return grsl._param_safe_name(self, bare)
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
    def _scratch_dict_copy(self, src: dict) -> dict:
        return grsl._scratch_dict_copy(self, src)

    def _infer_local_var_types(self, func: FunctionDef) -> dict[str, str]:
        return grsl._infer_local_var_types(self, func)
    def _collect_calls(self, expr, out):
        return grsl._collect_calls(self, expr, out)
    def _calls_in_stmts(self, stmts, out):
        return grsl._calls_in_stmts(self, stmts, out)
    def _split_expr_format(self, src: str) -> str:
        return grsl._split_expr_format(src)
    def _parse_fstring_parts(self, inner: str) -> list[tuple[str, str, str, str]]:
        return grsl._parse_fstring_parts(self, inner)
    def _repr_value(self, rat: str, rav: str, enode=None) -> str:
        return grsl._repr_value(self, rat, rav, enode)
    def _decode_str_literal_text(self, val: str) -> tuple[str, str]:
        return grsl._decode_str_literal_text(self, val)
    def _stub_result(self, ctype: str, value: str, note: str) -> tuple[str, str]:
        return grsl._stub_result(self, ctype, value, note)
    def _intern_string(self, escaped: str) -> str:
        return grsl._intern_string(self, escaped)
    def _str_literal_to_slit(self, str_literal: str) -> str:
        return grsl._str_literal_to_slit(self, str_literal)
    def _subst_idents(self, expr, mapping: dict):
        return grsl._subst_idents(self, expr, mapping)
    def _format_percent_spec(self, full_spec: str, conv: str, et: str, ev: str,
                             enode=None, width_ints: list | None = None) -> str:
        return grsl._format_percent_spec(self, full_spec, conv, et, ev, enode,
                                         width_ints)
    def _cast_for_list(self, elem_type: str, val: str, suf: str) -> str:
        return grsl._cast_for_list(self, elem_type, val, suf)
    def _type_expr_to_ann(self, node) -> str:
        return grsl._type_expr_to_ann(self, node)
    def _static_generic_return_ctype(self, func_name: str) -> str | None:
        return grsl._static_generic_return_ctype(self, func_name)
    def _elaborate_generic_call(self, node: CallExpr):
        return grsl._elaborate_generic_call(self, node)
    def _refine_generic_return_type(self, info: dict, module_src: str, g: str, mangled_type_args: list, arg_count: int, materialize=None) -> None:
        return grsl._refine_generic_return_type(self, info, module_src, g, mangled_type_args, arg_count, materialize=materialize)
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

_SELFHOST_GG_CACHE: dict = {}


def _selfhost_load_gimplegen_class(_src_dir=None):
    """Parse `<src_dir>/gimple_codegen.py` and return its `class GimpleGen`
    StructDef node (or None). `gimple_codegen` is a bare `.py` sibling —
    module_loader can't resolve `import gimple_codegen` as a Mojo module, and
    the `gimple_codegen ↔ gimple_module_gen` import cycle keeps `class
    GimpleGen` out of `imported_stmts` during gimple_module_gen.py's own
    compile — so parse the file directly. Cached on path+mtime.

    `_src_dir` (passed from `_run_pipeline`'s resolved entry-file dir) is
    tried first: in the COMPILED binary `_SELFHOST_DIR` is the process CWD
    (`stage2/`), not the real source dir, so the old
    `os.path.join(_SELFHOST_DIR, ...)` did not exist and this returned
    None."""
    _p = None
    for _cand_dir in (_src_dir, _SELFHOST_DIR, '.', '..'):
        if _cand_dir is None:
            continue
        _c = os.path.join(_cand_dir, 'gimple_codegen.py')
        if os.path.isfile(_c):
            _p = _c
            break
    if _p is None:
        return None
    try:
        _mt = os.path.getmtime(_p)
    except OSError:
        return None
    _hit = _SELFHOST_GG_CACHE.get('c')
    if _hit is not None and _hit[0] == _mt:
        return _hit[1]
    try:
        _mod = ast_rewriter.rewrite(
            Parser(py_tokenize(open(_p).read())).with_filename(_p).parse_module())
    except Exception:
        return None
    _cls = None
    for _s in _mod:
        if getattr(_s, 'name', None) == 'GimpleGen' and hasattr(_s, 'methods'):
            _cls = _s
            break
    _SELFHOST_GG_CACHE['c'] = (_mt, _cls)
    return _cls


def _selfhost_register_gimplegen(gen):
    """One-time (per top-level compile) GimpleGen self-host registry seed.

    The function-extraction refactor moved `gen_module_impl` + ~330 former
    `GimpleGen` methods into `gimple_module_gen.py` / `gimple_gen_*.py` as
    module functions taking the instance as an ordinary `self`/`gen` first
    parameter. For that parameter to be typed `GimpleGen *` (so `self.field`
    / `self.method()` resolve statically instead of stubbing to a no-op —
    which made the compiled `compile_to_gimple` silently produce nothing),
    THIS compile needs `class GimpleGen`'s full field + method registry.

    This seed only PARSES and stashes; `gimple_module_gen.gen_module_impl`
    routes the parsed StructDef through `_imported_typedef_structs` so the
    ordinary struct-registration passes build everything, and applies the
    extracted-helper field union + frozen signature lock. The stashed
    attributes are shared into every nested temp_gen (gimple_gen_resolve.py)."""
    _cls = _selfhost_load_gimplegen_class(gen._selfhost_src_dir or None)
    if _cls is None:
        return
    gen._selfhost_gimplegen_stmts = _cls
    gen._selfhost_gimplegen_extra_fields = \
        gfn._selfhost_gimplegen_field_types(_cls, gen._selfhost_src_dir or None)
    gen._selfhost_gimplegen_sigs = gfn._selfhost_gimplegen_frozen_sigs(gen, _cls)
    gen._selfhost_gimplegen_dict_vts = gfn._selfhost_gimplegen_dict_val_types(_cls)
    # Seed `struct_field_types['GimpleGen']` from the extracted-helper field
    # scan HERE, unconditionally, exactly once (this function itself only
    # runs once per top-level compile) — NOT inside `gen_module_impl`'s
    # per-file "not _gg_have_infile" branch. `gimple_module_gen.py`'s own
    # unconditional re-merge of this same dict (`if _gg_sigs and 'GimpleGen'
    # in self.struct_field_types:`) only fires once the key already exists,
    # so whether these extracted-helper fields (`_cpp_gen_self_fields`,
    # `_prepass_struct`, `_dispatch_solver`, ... — written ONLY in
    # extracted-helper files like gimple_gen_infra.py, never inside class
    # GimpleGen's own body, since those methods were extracted OUT of the
    # class) end up in the final struct at all previously depended on
    # whether some OTHER temp_gen happened to take the synthetic-
    # registration path BEFORE the one processing the real `class
    # GimpleGen` — a self-hosted-vs-shim dict/set-iteration-order
    # difference (the same recurring bug class as everywhere else in this
    # codebase) that produced a real shim-vs-noshim `--dump-full` byte
    # divergence (~5.8MB, first differing at the GimpleGen typedef). Always
    # seeding here makes the baseline deterministic regardless of temp_gen
    # processing order; the real struct's own later field-scan passes
    # (class-body annotations, `self.X = <literal>` in its OWN methods) can
    # only ADD to this baseline, never remove from it, so the two runs
    # converge on the same final field set either way. See bugs/CODEGEN_
    # noshim_dumpfull_preexisting_divergence.md's Finding 4 Bug C.
    if 'GimpleGen' not in gen.struct_field_types:
        gen.struct_field_types['GimpleGen'] = {}
    _gg_ft_seed = gen.struct_field_types['GimpleGen']
    # `_as_str()` on BOTH key and value, not a bare `.items()` unpack —
    # the self-hosted backend's dict `.items()`/copy path has a known,
    # separately-documented unreliability for this exact shape (see the
    # sibling comment at gimple_module_gen.py's own former identical copy,
    # "Rebuild via an indexed loop, not `dict(x)`... build the copy
    # through explicit key iteration + `_as_str`"): confirmed by hand here
    # too — without the `_as_str()` calls, self-hosted `mojoc` silently
    # dropped every value back to the `int64_t` default (`_actual_types`,
    # `_all_closures`, ... all lost their real `MojoDict *`/`MojoSet *`
    # type) while the python3 shim, running the exact same source,
    # preserved them correctly — a real, reproduced shim-vs-noshim
    # `--dump-full` byte divergence this cast fixes.
    for _gg_fk in gen._selfhost_gimplegen_extra_fields:
        _gg_fk_s = _as_str(_gg_fk)
        _gg_fc_s = _as_str(gen._selfhost_gimplegen_extra_fields[_gg_fk])
        _gg_cur = _gg_ft_seed.get(_gg_fk_s)
        # A generic default must yield to ANY more specific ctype, not just
        # a pointer type -- see the matching fix + comment on
        # `_selfhost_merge_field` in gimple_gen_funcs.py (identical bug: a
        # `_Bool` field seen after an `int64_t` default was silently kept
        # at `int64_t` because only `_ct.endswith(' *')` was accepted).
        if _gg_cur is None or (_gg_cur in ('int', 'int64_t', '_Bool')
                                and (_gg_fc_s.endswith(' *') or _gg_fc_s == '_Bool')):
            _gg_ft_seed[_gg_fk_s] = _gg_fc_s
    gen._selfhost_gimplegen_registered = True


# doc/OWNERSHIP_MODEL.md Phase 4 — `mut` exclusivity ENFORCEMENT (Phase 2's
# analysis had been landed and validated since 2026-09-15 but never actually
# wired into a real compile — `ownership_check.check_module` was reachable
# only from its own test suite and `__main__` block, so a real violation
# compiled clean either way). Wired in here, right after parsing and BEFORE
# `ast_rewriter.rewrite` (matching exactly the AST shape the 664-file real
# Modular stdlib sweep + this project's own 60-file self-hosted-compiler/
# test-corpus sweep were run against on 2026-09-15 before this was wired in:
# 0 diagnostics, 0 crashes across all 724 files — the empirical basis for
# treating this as a hard error rather than a warning). `MOJO_SKIP_OWNERSHIP_
# CHECK=1` is the escape hatch (matching this project's own MOJO_CORO=cpp/
# MOJO_NO_SHIM=1 convention) for the first time this surfaces a real false
# positive on code broader than that sweep, so a single bad diagnostic can't
# block an otherwise-working build while it's investigated.
def _check_ownership(stmts, filename: str) -> None:
    if os.environ.get('MOJO_SKIP_OWNERSHIP_CHECK'):
        return
    diags = ownership_check.check_module(stmts)
    if not diags:
        return
    label = filename or '<source>'
    lines = [f"{label}:{d}" for d in diags]
    raise SyntaxError(
        "ownership violation" + ("s" if len(diags) > 1 else "") + ":\n"
        + "\n".join(lines)
        + "\n(set MOJO_SKIP_OWNERSHIP_CHECK=1 to bypass while investigating)"
    )


def _dedup_guarded_blocks(code: str) -> str:
    """Strip every REPEAT `#ifndef <GUARD>\\n#define <GUARD>\\n...#endif`
    block sharing the same GUARD name, keeping only the first (textually
    earliest) occurrence — for ANY guard, not just one specific prefix.

    A `do_imports=True`/link-mode whole-program compile inlines many
    independently-generated per-module code fragments, and this
    codebase's OWN generated-C conventions (`_stub_guard_name`'s own
    docstring: "share ONE guard namespace so a real definition always
    wins over a later auto-generated stub of that SAME symbol") already
    make every one of these blocks INTENTIONALLY safe to collapse to
    "keep whichever occurs first" — that's exactly what the C
    preprocessor itself would do at compile time anyway (a later
    `#ifndef X`/`#define X` is a no-op once `X` is already defined); this
    just does it as a text-level pass ahead of time, for determinism.
    Two real, independent duplication sources this fixes:

    1. A module's full `typedef struct _<mod>_toplev {...}` (gen_module_
       impl's "sorted(all_modules_to_declare)" preamble loop AND its "this
       is MY module" block both independently emit this SAME struct any
       time a fragment references a sibling module whose globals happen
       to already be known at that fragment's own generation time) — a
       module reachable from many importers (e.g. `build_config`) gets
       its full struct definition emitted once per REFERENCING fragment,
       not once per program.
    2. A heavily-referenced struct's own auto-stub method declarations
       (gimple_module_gen.py's `self._elaborated_externs` list — NOT
       shared across nested temp_gen instances, and can't safely be: its
       own consumption pattern re-dumps the WHOLE list's current contents
       once per fragment, so sharing it just makes duplication WORSE, not
       better — confirmed directly, tried and reverted). GimpleGen itself
       (~363 methods) showed 20328 total stub-guard occurrences for only
       363 unique names in a real `fire.py --dump-full` (~56x
       duplication) before this fix.

    Both are individually valid C in every occurrence (the `#ifndef`
    guard makes every occurrence after the first a compile-time no-op) —
    wasteful, not broken, for an ordinary build. But WHICH of a symbol's
    several nested, independently-recursing referencing fragments happens
    to be the one whose own compile runs (in PYTHON CALL-STACK / EXECUTION
    order, not the deterministic textual splice order the outer
    `sorted(modules_to_compile)` loop uses to assemble the final file) at
    a point where the symbol is already known is itself compile-order-
    dependent, and not guaranteed identical between the python3 shim and
    the self-hosted binary — a real, confirmed source of whole-program
    `--dump-full` shim-vs-self-host byte divergence.

    Deliberately a POST-PROCESSING pass over the FINAL, fully-assembled
    code string (called exactly once, only at the true top-level
    `_run_pipeline` entry point — never on an individual nested fragment)
    rather than a dedup guard threaded through the recursive per-module
    compiles themselves: an earlier attempt at exactly that (tracking
    "already emitted" during generation, shared across nested temp_gen
    instances) broke `make mojoc`'s own build with "invalid use of
    undefined type" errors, because that in-flight tracking follows
    PYTHON EXECUTION order, which can genuinely differ from the file's
    own final TEXTUAL order (a module compiled early, in Python call-
    stack terms, because an EARLIER-executing importer happens to depend
    on it, can still end up spliced LATER in the final file, since the
    outer splice order is `sorted(modules_to_compile)` by NAME, not by
    execution order) — a module needing an EARLIER textual position's
    full definition could end up with only a later one, an actual
    "incomplete type" compile error. Operating on the finished text
    sidesteps that mismatch entirely: every occurrence found here is
    already in genuine final file order, so keeping strictly the first
    of several occurrences that are ALL already in real, final file order
    can never move a definition to a position later than any of its own
    real uses.

    Deliberately PLAIN STRING SCANNING (line-based), NOT `re` — an
    earlier version used a backreferenced, non-greedy regex, which this
    codebase's self-hosted regex engine (a POSIX-regex-based
    reimplementation, not Python's real `re`) does not support:
    backreferences and non-greedy quantifiers are both outside POSIX
    ERE. This function is compiled into the self-hosted binary as part
    of `_run_pipeline`'s own closure (it runs on every do_imports=True
    compile, including the self-hosted compiler's own `--dump-full` of
    itself), so the regex version silently made the NATIVE
    `compile_to_gimple` raise/fail self-hosted every time — invisible
    while `gimple_codegen_compile_to_gimple`'s python3-subprocess
    fallback still existed (a native failure just silently fell back to
    the subprocess, which used real Python's `re` and worked fine), but
    a hard failure (native returns NULL, no fallback left) the moment
    that subprocess path was removed.

    NESTING-AWARE: a guarded block can legitimately contain ANOTHER
    nested `#ifndef .../#endif` pair (confirmed real: `_guarded_ctor`'s
    own `#ifndef {stub_guard}\\n#ifndef {guard}\\n#define {guard}\\n...
    #endif\\n#endif` wrapping) — a naive "first #endif found = end of
    block" scan would cut such a block short. This tracks nesting depth
    so only the OUTER `#ifndef`'s own matching `#endif` closes the
    block."""
    lines = code.split('\n')
    n = len(lines)
    seen: set = set()
    out_lines: list = []
    i = 0
    while i < n:
        line = lines[i]
        if line.startswith('#ifndef ') and i + 1 < n:
            guard = line[len('#ifndef '):]
            if lines[i + 1] == f'#define {guard}':
                depth = 1
                j = i + 1
                closed = False
                while j + 1 < n:
                    j += 1
                    if lines[j].startswith('#ifndef ') or lines[j].startswith('#if '):
                        depth += 1
                    elif lines[j] == '#endif':
                        depth -= 1
                        if depth == 0:
                            closed = True
                            break
                if closed:
                    if guard in seen:
                        i = j + 1
                        continue
                    seen.add(guard)
                    out_lines.extend(lines[i:j + 1])
                    i = j + 1
                    continue
        out_lines.append(line)
        i += 1
    return '\n'.join(out_lines)


def _relocate_module_instance_defs(code: str) -> str:
    """After `_dedup_guarded_blocks` canonicalizes each module's
    `typedef` to a single, deterministic position, ALSO relocate that
    module's one-time `struct _<mod>_toplev _<mod>_globals = {...};`
    instance-definition-WITH-INITIALIZERS block (emitted exactly once
    overall, by whichever nested temp_gen's own gen_module_impl call
    happens to process that module "as itself" — see gimple_module_gen.py's
    per-module globals-struct block) to immediately follow that same
    module's now-canonical `extern struct _<mod>_toplev _<mod>_globals;`
    declaration line.

    Unlike the typedef (deduped above because it is genuinely emitted more
    than once), this instance-definition block is emitted EXACTLY ONCE —
    confirmed via `grep -c` on a real `--dump-full` — so the divergence
    here is pure ORDERING, not duplication: WHICH nested temp_gen's own
    fragment happens to embed it (hence where in the final spliced file it
    lands) is compile-order-dependent in the same way the typedef's
    emission was, and not guaranteed identical between the python3 shim
    and the self-hosted binary (confirmed directly: `struct _build_config_
    toplev _build_config_globals = {...}` at line 3388 self-hosted vs line
    4840 in the shim, for the byte-identical typedef at line 2135 in both).
    Anchoring its position on the already-canonical typedef/extern-decl
    (governed by textual order, already made deterministic above) instead
    of leaving it wherever Python-execution order happened to splice it
    makes this deterministic too.

    Plain line-based string scanning, no `re` (see
    `_dedup_guarded_blocks`'s docstring for why regex is unsafe in
    a function that runs inside the self-hosted compiler's own compiled
    closure)."""
    lines = code.split('\n')
    n = len(lines)

    # Pass 1: find every module name that has a REAL (non-"incomplete")
    # typedef elsewhere in the file — i.e. an "extern struct _<name>_
    # toplev _<name>_globals;" line immediately preceded by that typedef's
    # closing `#endif`. A module's OWN "gen_module_impl processing itself"
    # block (root, or any module never referenced by ANOTHER module's own
    # "sorted(all_modules_to_declare)" loop before its own compile — e.g.
    # `root`/fire.py itself, since that loop explicitly skips `our_mod`)
    # has NO such separate extern line anywhere: its typedef+instance-
    # with-initializers pair is emitted together, once, with nothing else
    # to anchor a relocation on. Only relocate names that DO have this
    # anchor; leave everything else exactly where it already is — moving
    # an unanchored block would just delete it (nothing left to insert it
    # after) or, worse, anchor on the WRONG thing (a module can ALSO have
    # an `__attribute__((incomplete))` forward-declaration variant, whose
    # own "extern struct X Y;" line is NOT preceded by `#endif` — splicing
    # real initializers onto that incomplete type is a hard GCC error,
    # confirmed by hand: "'struct _root_toplev' has no member named ..."
    # for every field, before this anchor-detection pass was added).
    anchor_names: set = set()
    for i in range(1, n):
        if (lines[i - 1] == '#endif' and lines[i].startswith('extern struct _')
                and lines[i].endswith('_globals;')):
            after = lines[i][len('extern struct _'):]
            toplev_idx = after.find('_toplev _')
            if toplev_idx >= 0:
                anchor_names.add(after[:toplev_idx])

    if not anchor_names:
        return code

    # Pass 2: extract each ANCHORED module's instance-with-initializers
    # block from wherever it currently sits — PLUS its immediately-
    # following per-global accessor functions (gimple_module_gen.py emits
    # `{ctype} {mod}__mojo_global_get_{field} (void) { return ...; }` for
    # each global, right after the instance def, as part of the SAME
    # one-time "this is MY module" unit — these must move together with
    # the instance def or they're left orphaned at the old, non-
    # deterministic position (confirmed by hand: `build_config__mojo_
    # global_get___all__` etc. still at the old splice point after only
    # the instance-def half was relocated).
    instance_blocks: dict = {}
    kept_lines: list = []
    i = 0
    while i < n:
        line = lines[i]
        if line.startswith('struct _') and line.endswith(' = {'):
            after_struct = line[len('struct _'):]
            toplev_idx = after_struct.find('_toplev _')
            if toplev_idx >= 0:
                name = after_struct[:toplev_idx]
                if name in anchor_names:
                    block_lines = [line]
                    j = i + 1
                    while j < n and lines[j] != '};':
                        block_lines.append(lines[j])
                        j += 1
                    if j < n:
                        block_lines.append(lines[j])
                        j += 1
                        # Consume the accessor functions immediately
                        # following (a blank line, then one line per
                        # global whose name contains this module's own
                        # `__mojo_global_get_` accessor prefix, then the
                        # trailing blank line the emitter always appends).
                        accessor_prefix = f'{name}__mojo_global_get_'
                        if j < n and lines[j] == '':
                            k = j + 1
                            acc_lines = []
                            while k < n and accessor_prefix in lines[k]:
                                acc_lines.append(lines[k])
                                k += 1
                            if acc_lines:
                                block_lines.append('')
                                block_lines.extend(acc_lines)
                                j = k
                                if j < n and lines[j] == '':
                                    j += 1
                        instance_blocks[name] = '\n'.join(block_lines)
                        i = j
                        continue
        kept_lines.append(line)
        i += 1

    if not instance_blocks:
        return code

    # Pass 3: re-insert each block immediately after its own anchor line.
    final_lines: list = []
    inserted: set = set()
    prev_line = ''
    for line in kept_lines:
        final_lines.append(line)
        if (prev_line == '#endif' and line.startswith('extern struct _')
                and line.endswith('_globals;')):
            after = line[len('extern struct _'):]
            toplev_idx = after.find('_toplev _')
            if toplev_idx >= 0:
                name = after[:toplev_idx]
                if name in instance_blocks and name not in inserted:
                    inserted.add(name)
                    final_lines.append('')
                    final_lines.append(instance_blocks[name])
        prev_line = line
    return '\n'.join(final_lines)


def _run_pipeline(mojo_src: str, *, do_imports: bool = False, filename: str = "",
                  link_mode: bool = False, auto_gpu: bool = True):
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
    # call). Cross-file dedup state (e.g. `_emitted_unresolved_stub_syms`)
    # now lives on the `GimpleGen` instance itself, fresh per instantiation,
    # so it can't leak stale "already emitted" markers between unrelated
    # compiles that happen to share this process (e.g. compile_stdlib.py
    # compiling many independent modules) with no explicit reset needed
    # here, while still deduping correctly *within* one call across every
    # nested GimpleGen instance recursive import-inlining creates (shared
    # by reference — see `_compile_imported_module`'s sharing block).
    gfn._selfhost_begin_compile()
    tokens = py_tokenize(mojo_src)
    stmts = Parser(tokens).with_filename(filename).parse_module()
    _check_ownership(stmts, filename)
    stmts = ast_rewriter.rewrite(stmts)
    # Generator expressions (`(x * 2 for x in xs)`) become REAL lazy
    # generators here, not the eager list this used to materialize: each
    # one is rewritten into a call to a synthesized module-level generator
    # function (fire_compiler.genexp_body builds the statement body both
    # this and the interpreter use). Must run BEFORE the coroutine
    # lowering below so those synthesized functions are seen — and lowered
    # — as ordinary top-level generators like any hand-written one. See
    # fire_compiler._GenexpDesugarer for the one capture shape
    # (a name rebound later in the enclosing function, or `self`) it
    # deliberately leaves alone.
    stmts = desugar_genexps(stmts)
    _desugared_names = list(DESUGARED_GENEXP_NAMES)
    # A3 stack-switch coroutine lowering (doc/COROUTINE.html §5.4), gated by
    # MOJO_CORO=stackswitch. Replaces eligible generator FunctionDefs with a
    # plain `__mgco_<g>_body` the ordinary codegen lowers; ineligible ones
    # fall through to the gimple_cpp_* C++20-coroutine path unchanged.
    stmts, _coro_meta = gimple_gen_coro.lower(stmts)
    gen = GimpleGen(do_imports=do_imports, link_imports=link_mode,
                    auto_gpu=auto_gpu)
    gimple_gen_coro.register_abi_externs(gen)
    if _coro_meta or gimple_gen_coro._NATIVE_FUTURE_CLASSES:
        gimple_gen_coro.register(gen, _coro_meta)
        grsl.publish_a3_generators(gen, _coro_meta)
    gen._current_filename = filename
    # Self-hosting bootstrap: when compiling this compiler's own source as a
    # transitive closure (`python3 fire.py build fire.py`, `--dump-full
    # fire.py`, `--dump-full fire_compiler.py`, `make bootstrap` stage 1,
    # `make check-selfhost`), seed the GimpleGen registry so the extracted
    # backend helpers can be typed. do_imports/link only, and only for a
    # file directly under the compiler's own source dir — never for
    # `--dump <userfile>` or a compile_stdlib.py worker.
    #
    # Originally gated to `basename in ('fire.py', 'mojo_main.py')` only —
    # too narrow: `--dump-full fire_compiler.py`'s transitive closure also
    # reaches gimple_gen_exprs.py (e.g. `_lb_as_set`/`_lower_binary_set_op`,
    # hoisted module-level helpers taking `gen` as their first param per
    # `_selfhost_gen_self_param_ctype`'s own documented convention), but
    # with `filename == 'fire_compiler.py'` the registration above never
    # ran, so `_selfhost_gimplegen_registered` stayed False for the WHOLE
    # compile and every such `gen` param fell through to generic inference
    # -> int64_t. Confirmed via the emitted C signature itself:
    # `char * _lb_as_set_895aa2 (int64_t gen, char * t, char * v)` instead
    # of the expected `GimpleGen * gen`. Every subsequent `gen._new_val(...)`
    # /`gen._ensure_local(...)` call inside such a function then went
    # through dynamic dispatch, and the erased int64_t `gen` value (an
    # ASLR heap address, printed as decimal digits) leaked into a later
    # `_declare_var`/cast site as if it were a real C name/expression —
    # `MojoList * (37459640688);`, different every run.
    #
    # Broadened once (0116978) to "any entry point under this compiler's own
    # source dir" via `os.path.abspath(os.path.dirname(filename)) ==
    # _SELFHOST_DIR`, then (66e3475) broadened AGAIN to unconditional
    # (do_imports/link_mode only, no filename check at all) reasoning that
    # `_selfhost_register_gimplegen` is a "harmless no-op" when this project
    # isn't the compiler's own source — WRONG when this repo genuinely IS
    # the compiler's own source (every dev checkout): the unconditional
    # version registered GimpleGen as an `_imported_typedef_structs` entry
    # for EVERY compile in this repo, including trivial unrelated test
    # programs — confirmed as a real regression via test_module_cache.py's
    # test_stage1_extern_boundary, a two-line Mojo program that started
    # failing with "unknown type name 'DispatchSolver'" (a compiler-
    # INTERNAL type from gimple_solvers.py, leaking into the OUTPUT of an
    # unrelated user program's compile because GimpleGen's own registered
    # methods reference it).
    #
    # The directory-only check ALSO isn't safe by itself: a synthetic test
    # filename like 'client.mojo' (test_module_cache.py's own
    # compile_to_gimple_linked(client, filename='client.mojo') call, no
    # real path at all) has an empty os.path.dirname, so
    # os.path.abspath(os.path.dirname('client.mojo')) resolves to the
    # process's CWD — which IS `_SELFHOST_DIR` whenever a test is run from
    # the repo root, exactly where these tests are always run from. The
    # directory check alone therefore still matched this same regression.
    # Basename allowlisting is the one dimension that correctly separates
    # "genuinely one of the compiler's own named entry files" from "any
    # relative-looking filename that happens to share this process's CWD" —
    # restored it, just widened to also cover 'fire_compiler.py' (the
    # actual motivating case for broadening this at all).
    # `_SELFHOST_DIR` is `dirname(abspath(__file__))` — in the COMPILED
    # binary `__file__` is `<bootstrap>`, so `_SELFHOST_DIR` resolves to the
    # process CWD (e.g. `stage2/`), never the real source dir, and the
    # `== _SELFHOST_DIR` check always failed there. That is why
    # `MOJO_NO_SHIM=1 make bootstrap` never registered the synthetic
    # GimpleGen struct and stage2's fire.ci was missing ~1400 lines of
    # `GimpleGen__*` method externs + the full typedef vs stage1. Accept a
    # second, path-independent signal: the entry file is one of the
    # compiler's own named files AND `fire_compiler.py` sits right next to
    # it (only true for a genuine compiler-source checkout, never for a
    # user program that happens to be named `fire.py`).
    _sh_dir = os.path.dirname(filename)
    _sh_sibling = os.path.isfile(os.path.join(_sh_dir, 'fire_compiler.py')) if _sh_dir else \
        os.path.isfile('fire_compiler.py')
    if ((do_imports or link_mode) and filename
            and os.path.basename(filename) in ('fire.py', 'mojo_main.py', 'fire_compiler.py')
            and (os.path.abspath(_sh_dir) == _SELFHOST_DIR or _sh_sibling)):
        # Hand the resolved source dir to `_selfhost_load_gimplegen_class`:
        # in the compiled binary `_SELFHOST_DIR` (== CWD) is wrong, so its
        # `os.path.join(_SELFHOST_DIR, 'gimple_codegen.py')` did not exist
        # and it returned None -> NOTHING registered -> the frozen
        # GimpleGen signature table was empty and stage2's ~200
        # `GimpleGen__*` method signatures were re-inferred per temp_gen
        # (timing-dependent -> `CallExpr *` vs stage1's boxed `int64_t`).
        gen._selfhost_src_dir = _sh_dir if (_sh_dir and os.path.isfile(
            os.path.join(_sh_dir, 'gimple_codegen.py'))) else _SELFHOST_DIR
        _selfhost_register_gimplegen(gen)
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
    code = gen.gen_module(stmts)
    if do_imports or link_mode:
        code = _dedup_guarded_blocks(code)
        code = _relocate_module_instance_defs(code)
    _verify_desugared_genexps(code, gen, _desugared_names)
    return code, gen


def _verify_desugared_genexps(code: str, gen, names: list) -> None:
    """Every generator expression `desugar_genexps` rewrote must have
    REALLY become a generator.

    The synthesized function is handed to the same two lowering paths a
    hand-written generator uses — the A3 stack-switch path (whose per-
    generator symbols are `__mgco_<name>_*`) or the C++20 companion unit
    (`__mojogen_<name>_*`). If neither claims it, the call site kept a
    reference to a function nothing defined: the program built, linked and
    ran, and the generator expression silently produced nothing. Measured
    with a struct-typed capture (`(c.note(i) for i in range(...))`), which
    neither path accepts.

    Refuse instead, naming the expression's source line, so the failure is
    a compile error rather than a silently empty result. The expression's
    own lowering (the pre-desugar eager list) is the correct-but-slow
    answer, and `desugar_genexps` declines shapes it cannot model — this
    check is the backstop for the shapes that pass its static analysis but
    that the generator backends still reject."""
    if not names:
        return
    cpp = getattr(gen, 'generated_cpp', '') or ''
    missing = [n for n in names
               if f'__mgco_{n}_' not in code and f'__mojogen_{n}_' not in cpp]
    if missing:
        raise RuntimeError(
            f"generator expression could not be compiled into a generator: "
            f"{', '.join(missing)} — neither the stack-switch nor the C++20 "
            f"coroutine path supports this shape (a captured value the "
            f"synthesized generator cannot take, most often a struct or a "
            f"container). Run this module through the interpreter, or "
            f"rewrite the expression as an explicit generator function.")


def compile_to_c(mojo_src: str, auto_gpu: bool = True) -> str:
    """Parse Mojo source and return C code WITHOUT __GIMPLE annotations.

    Useful for execution tests where __GIMPLE restrictions don't apply.
    """
    c_code, _gen = _run_pipeline(mojo_src, auto_gpu=auto_gpu)

    # Strip __GIMPLE annotations for executability
    c_code = c_code.replace(' __GIMPLE ', ' ')
    return c_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_compile_cache: dict = {}  # key -> str  (in-process L1 for compile_to_gimple_cached)

_IMPORT_LINE_RE = re.compile(r'^\s*(?:from|import)\s+([.\w]+)', re.MULTILINE)


def _dep_sources_texts(mojo_src: str, filename: str) -> dict:
    """The transitive import closure of sibling modules resolved next to the
    entry file, as {abs_path: source_text} — both .mojo and .py (fire.py's
    own bootstrap dumps inline .py siblings like myinterpreter.py). Mirrors
    how codegen finds them (imports.resolve_source, then
    _resolve_test_relative_module's walk up the entry file's ancestors).
    Stdlib sources are skipped: cas.stdlib_fingerprint() already covers every
    stdlib file, and re-hashing the reachable stdlib per compile would turn a
    cheap scan into a closure walk. Best-effort by design: an import the scan
    can't resolve contributes nothing (codegen skips it too)."""
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
    return seen


def _dep_sources_digest(mojo_src: str, filename: str) -> str:
    """Digest of every non-stdlib source this compile can read (see
    _dep_sources_texts for what's in the set). Hashing a file codegen never
    opens only over-invalidates, never goes stale."""
    texts = _dep_sources_texts(mojo_src, filename)
    if not texts:
        return ''
    import cas
    return cas._hash(*(f'{p}\0{texts[p]}' for p in sorted(texts)))


def compile_to_gimple_cached(mojo_src: str, do_imports: bool = False, filename: str = "",
                            auto_gpu: bool = True) -> str:
    """Like compile_to_gimple but CAS-cached (plus an in-process L1).

    The full tokenize -> parse -> AST-rewrite -> gen_module pipeline is
    content-addressed: the key covers everything it reads — the entry source,
    mode, filename, the compiler + stdlib fingerprints, and the sibling-import
    closure digest — so every caller (--dump, build_executable, build_module,
    Makefile dump loops) shares one cache line per unique input
    set, and editing any transitively imported file invalidates it with no
    manual versioning.

    NOTE: the self-hosted compiler lowers calls to this function to the same
    C shim as compile_to_gimple (see the gimple_codegen method special-case in
    lower_method_call) — the compiled binary compiles uncached, which is
    correct, just slower."""
    import cas
    key = cas.compile_key(mojo_src, do_imports, filename,
                          deps_digest=_dep_sources_digest(mojo_src, filename),
                          auto_gpu=auto_gpu)
    return cas.get_or_build_text(
        key, '.ci',
        lambda: compile_to_gimple(mojo_src, do_imports, filename, auto_gpu),
        _compile_cache)


def compile_to_gimple(mojo_src: str, do_imports: bool = False, filename: str = "",
                      auto_gpu: bool = True) -> str:
    """Parse Mojo source and return a C string with __GIMPLE annotations.

    If do_imports=True, recursively compile imported modules and inline their code.
    If do_imports=False, imports are recorded as metadata only.
    If filename is provided, emit #line directives with the filename.

    (The first three parameters are the self-hosting ABI: the bootstrap emits a
    matching 3-arg forward declaration, and a 4th POSITIONAL argument would
    break that. `auto_gpu` is therefore keyword-with-default, so every existing
    3-arg call — including the one the compiled path emits — is unchanged.
    Link mode is a separate entry point, compile_to_gimple_linked, to avoid
    changing that ABI at all.)
    """
    # One call here = one independent output artifact (this project's own
    # transitive-closure dumps included - the whole multi-file closure is one
    # call). Reset cross-file dedup state so it can't leak stale "already
    # emitted" markers between unrelated compiles that happen to share this
    # process (e.g. compile_stdlib.py compiling many independent modules),
    # while still deduping correctly *within* one call across every nested
    # GimpleGen instance recursive import-inlining creates.
    result, _gen = _run_pipeline(mojo_src, do_imports=do_imports, filename=filename,
                                 auto_gpu=auto_gpu)
    _refuse_dropped_companion(result, _gen)
    return result


def _refuse_dropped_companion(code: str, gen) -> None:
    """Raise if `compile_to_gimple` is about to return a `.ci` that
    references `__mojogen_*` symbols whose ONLY definitions live in the
    companion `.cpp` this entry point has just discarded.

    The pipeline always builds the companion when it compiles a generator on
    the C++20 path (`_gen_cpp_generator_unit` runs inside `gen_module`); the
    difference between the entry points is purely whether the CALLER gets to
    see it. `compile_to_gimple_with_cpp` returns it and its build paths compile
    and link it; `compile_to_gimple` cannot — its 3-arg-in/1-str-out signature
    is the pinned self-host ABI and `compile_to_gimple_cached` stores exactly
    one `.ci` blob per key, so there is nowhere to put a second artifact.

    That made the discard SILENT, and the cost was a link error tens of
    thousands of lines away from the cause: gcc's own `fire1` build
    (`fire/fire/Make-lang.in`'s `fire.o` recipe, fed by
    `fire.py --dump-full`) and bootstrap's stage1 `gcc -O0` compile are both
    C-only single-`.ci` pipelines, so any generator in this compiler's own
    closure that the stack-switch path refuses and the C++ path accepts left
    `_mojogen_<mod>_<fn>_{start,resume,value,destroy}` referenced by the `.ci`
    and defined nowhere — `make fire` died with
    `__mojogen_build_stdlib_dylib__output_lock_{start,resume}` undefined,
    attributed to `_build_stdlib_dylib_build`, thousands of lines from the
    generator that caused it.

    Refusing HERE, at the one place that knows both halves, turns that into a
    message naming the actual problem, and it cannot rot: the check is on the
    generated text (`__mojogen_`), not on a hand-maintained list of which
    shapes take which backend. `_verify_desugared_genexps` already guards the
    sibling failure mode (a synthesized generator expression claimed by
    NEITHER path) for the same reason."""
    cpp = getattr(gen, 'generated_cpp', '') or ''
    if not cpp or '__mojogen_' not in code:
        return
    _syms = sorted(set(re.findall(
        r'__mojogen_[A-Za-z0-9_]+_(?:start|resume|value|destroy)\b', code)))
    raise RuntimeError(
        "cannot compile this module to a single .ci: it uses "
        f"{len(_syms)} C++20-coroutine generator symbol(s) "
        f"({', '.join(_syms[:6])}{'...' if len(_syms) > 6 else ''}) whose "
        "definitions are in a companion .cpp that compile_to_gimple cannot "
        "return. Use compile_to_gimple_with_cpp (which returns and links that "
        "companion), or make the generator stack-switch-eligible so it needs "
        "no companion at all — the compiled `with` lowering already implements "
        "@contextlib.contextmanager by driving the handle directly, so that "
        "decorator is the usual reason a generator lands here.")


def compile_to_gimple_with_cpp(mojo_src: str, do_imports: bool = False,
                                filename: str = "",
                                link_objects_out: list = None,
                                auto_gpu: bool = True) -> tuple[str, str]:
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
    the extra work only happens on the rare module that needs it.

    `link_objects_out`: optional list the caller owns; when given, it is
    extended with the CAS object paths `_compile_imported_module` built for
    TRANSITIVELY-IMPORTED sibling modules' own top-level coroutine units
    (the 4th coroutine-code source — see its call site in gimple_gen_
    resolve.py and “COMPILE_FAIL: Tools/cases_generator/parser.py”).
    `compile_linked` returns the same paths to driver.compile_program for
    the link-mode pipeline; this out-param gives the inline (do_imports=
    True) build_executable pipeline access to them too, so a root module
    whose OWN generated_cpp is empty but whose imported siblings define
    generators still gets those definitions onto the link line. Every path
    is a C++-compiled object, so a consumer must treat their presence like
    a non-empty companion .cpp for final-link-driver selection."""
    c_code, gen = _run_pipeline(mojo_src, do_imports=do_imports, filename=filename,
                                auto_gpu=auto_gpu)
    if link_objects_out is not None:
        link_objects_out.extend(dict.fromkeys(gen._link_objects))
    return c_code, gen.generated_cpp


def module_may_have_supported_generator(mojo_src: str, filename: str = "") -> bool:
    """Cheap, purely-textual pre-scan: does this compile even MENTION `yield`
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
    it has exactly one call site (fire.py's build_executable) and its
    return value's MEANING ("routing through compile_to_gimple_with_cpp is
    worth trying") hasn't changed, only the set of source shapes that can
    make that true.

    With a `filename`, the scan also covers the entry file's transitive
    LOCAL-sibling import closure (the same set _dep_sources_texts resolves,
    stdlib excluded) — the do_imports=True inline pipeline compiles those
    siblings' code too, so a root file with no `yield` of its own whose
    imported sibling defines a plain top-level generator (parser.py ->
    parsing.py -> lexer.py's tokenize()) must not be screened out of the
    coroutine-capable path: its .c side still references the sibling's
    __mojogen_<mod>_<fn>_* symbols, which only that path's capture ever
    links. Without a filename the behavior is exactly the old root-only
    scan (no closure to walk for a bare-source caller)."""
    if 'yield' in mojo_src or 'async def' in mojo_src:
        return True
    if not filename:
        return False
    for text in _dep_sources_texts(mojo_src, filename).values():
        if 'yield' in text or 'async def' in text:
            return True
    return False


def compile_to_gimple_linked(mojo_src: str, filename: str = "",
                             auto_gpu: bool = True) -> str:
    """Like compile_to_gimple, but in *link mode*: imported symbols become
    `extern` declarations (bodies come from a linked artifact / stdlib dylib;
    see MODULE_CACHE_DESIGN.md and ABI.md) rather than being inlined."""
    return compile_linked(mojo_src, filename, auto_gpu)[0]


def compile_linked(mojo_src: str, filename: str = "",
                   auto_gpu: bool = True) -> tuple:
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
    silently papered over in practice only because `fire.py build`/`run`
    fall back to a completely different, simpler inline pipeline
    (`fire.py`'s own `build_executable`, which already had this handling)
    whenever `driver.compile_program` fails, masking the gap."""
    code, gen = _run_pipeline(mojo_src, filename=filename, link_mode=True,
                              auto_gpu=auto_gpu)
    # `gen._link_needs_cxx_box[0]`: a coroutine unit discovered several
    # `_compile_imported_module` levels deep (a do_imports=True-only nested
    # temp_gen, not `gen` itself) sets this shared box rather than `gen`'s
    # own `_link_needs_cxx` attribute directly — see the box's own
    # declaration and `_compile_imported_module`'s matching write site for
    # the full reasoning (“COMPILE_FAIL: Tools/cases_generator/parser.py”).
    needs_cxx = gen._link_needs_cxx or gen._link_needs_cxx_box[0] or bool(gen.generated_cpp)
    return (code,
            list(dict.fromkeys(gen._link_dylibs)),
            list(dict.fromkeys(gen._link_objects)),
            gen.generated_cpp,
            needs_cxx)
