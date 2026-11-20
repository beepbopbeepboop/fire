"""The compiler-internal dispatch-table global ctypes, and the one accessor
that reads them.

A LEAF module on purpose: it imports nothing. `mojo/middle/types.py` imports
`module_loader`, and `module_loader` must read this same table to type the
set/dict globals it exports to importers. Keeping the table here breaks that
cycle, so the owner (types.py / the globals struct) and the importer (the
extern in module_loader) answer from one source.
"""

# The dispatch-table and type-table MODULE GLOBALS, with the C DECLARATION
# TYPE each one really has. ONE mapping, because four sites need this same fact
# and each used to carry its own hand-written copy -- and the copies drifted the
# moment the globals moved from `gimple_codegen.py` into `mojo/middle/types.py`
# under the module split, which is how "struct _mojo_middle_types_toplev has no
# member named '_TYPE_MAP'" happened.
#
# THE TYPE IS PART OF THE KEY'S ANSWER, and a bare "a dispatch table is a
# `MojoDict *`" is wrong for eleven of the twenty-four: ten are sets
# (`_CMP_OPS` is declared `_CMP_OPS: set` in `generated_dispatch.py`; the rest
# are `frozenset`s or `{...}` set literals) and two are plain strings and two
# are not containers at all. That mis-typing is not cosmetic. Each answer is
# written into the SHARED, bare-name-keyed `_global_c_decl_types`, and
# `_own_overlay_global_ctype`'s rule 1 ("a container cdecl beats a scalar
# own-conclusion") then lets it beat the OWNING module's own correct
# conclusion -- so module_loader's `_C_KEYWORDS = frozenset({...})` found
# `_global_c_decl_types['_C_KEYWORDS'] == 'MojoDict *'` and refused to coerce:
#
#     # ERROR: compiling imported module 'module_loader': cannot coerce
#     #   MojoSet * to MojoDict * (incompatible container kinds)
#
# for four modules of the self-host closure, `selfhost`/`mojoc` red.
#
# Read the global's own DEFINITION before adding a name -- a `{...}` literal
# with no `key: value` pairs is a SET, not a dict. `'int64_t'` is the BOX: the
# value is right and there is no typed accessor, which is the convention
# `_gscan_declare_global`'s own non-dispatch arms use for exactly that case
# (`_FIXED_ARRAY_ANN_RE` is a compiled regex; its pattern source lives in
# `_regex_patterns` and `.finditer()` is lowered from that string, so the
# object itself is never read at run time).
#
# `dispatch_table_global_ctype` below is the ONLY way out of this table, so
# membership ("is this one of ours?") and the type ("what C type is it?")
# cannot come apart the way a name-list-plus-a-parallel-type-list pair does.
_DISPATCH_TABLE_GLOBAL_CTYPES = {
    # ── dicts ──
    '_STMT_DISPATCH': 'MojoDict *',
    '_EXPR_DISPATCH': 'MojoDict *',
    '_BIN_OPS': 'MojoDict *',
    '_TYPE_MAP': 'MojoDict *',
    '_SIGNED': 'MojoDict *',
    '_UNSIGNED': 'MojoDict *',
    '_FLOAT': 'MojoDict *',
    '_LIBM_FN_RETVALS': 'MojoDict *',
    '_SELFHOST_EXTRA_FIELD_CACHE': 'MojoDict *',
    # ── `frozenset`s and `{...}` set literals ──
    '_CMP_OPS': 'MojoSet *',
    '_C_KEYWORDS': 'MojoSet *',
    '_C_RESERVED_FUNCS': 'MojoSet *',
    '_FORCE_RENAME_RESERVED': 'MojoSet *',
    '_CPP_KEYWORD_FIELDS': 'MojoSet *',
    '_C_PARAM_EXTRA_KEYWORDS': 'MojoSet *',
    '_PSEUDO_DUNDER_ATTRS': 'MojoSet *',
    '_LIST_RETURNING_METHODS': 'MojoSet *',
    '_STR_RETURNING_METHODS': 'MojoSet *',
    '_SCALAR_INT_TYPES': 'MojoSet *',
    '_SCALAR_FLOAT_TYPES': 'MojoSet *',
    # fire_compiler.py / unknown_decl_check.py: frozensets whose initializer is
    # not a bare set literal (`_COMPILE_TIME_INTRINSICS` is `frozenset({...}) |
    # N._COMPTIME_TYPE_FUNCS`), so the C-type inference has no answer for them
    # and the generated module struct declared them `int64_t`. Storing a
    # `MojoSet *` into that is "cast to pointer from integer of different size"
    # in gcc, a hard error. `_COMPTIME_TYPE_FUNCS` / `_PURE_ITER_CALLS` are
    # `frozenset({...})` at module scope, the same bug, and are read cross-module
    # through `N.<name>` / `ownership_check`.
    '_COMPTIME_TYPE_FUNCS': 'MojoSet *',
    '_PURE_ITER_CALLS': 'MojoSet *',
    '_COMPILE_TIME_INTRINSICS': 'MojoSet *',
    # ── plain strings ──
    '_CPP_CALLABLE_CTYPE': 'char *',
    '_CPP_CALLABLE_CTYPE_1ARG': 'char *',
    '_UNKNOWN_FIELD_CTYPE': 'char *',
    # ── no typed accessor: the box ──
    '_FIXED_ARRAY_ANN_RE': 'int64_t',
}


def dispatch_table_global_ctype(name) -> str | None:
    """The C declaration type for the compiler-internal table global `name`,
    or None when it is not one of ours.

    ONE accessor for the whole table, rather than the table plus a names list:
    a `name -> ctype` mapping and a parallel `names` list can disagree, and
    that disagreement has been a build break twice (see
    `_DISPATCH_TABLE_GLOBAL_CTYPES`'s own comment) -- `selfhost` red with
    "cannot coerce MojoSet * to MojoDict *". `... is not None` is therefore
    also the ONE membership test, which is the other half of what a name list
    was for.

    A FUNCTION, and not a bare read of the dict at each call site: these sites
    are in other modules (`mojo/backend_gimple/module_gen.py`,
    `mojo/middle/module_shared.py`, `gimple_codegen.py`), and a cross-module
    call is the one shape that does not depend on how the self-hosted compiled
    path represents another module's globals. A module-level `dict.get` and a
    module-level `in` over a dict literal both happen to work there today; a
    cross-module ATTRIBUTE read of one does not, and a `tuple(<dict>)` /
    `set(<tuple>)` derived view of the table does not either, so neither this
    function nor its callers may be "simplified" into either."""
    return _DISPATCH_TABLE_GLOBAL_CTYPES.get(name)
