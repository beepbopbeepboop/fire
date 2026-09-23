"""Shared middle-end extracted from gimple_gen_infra.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, Parser, py_tokenize, _as_str, _as_set, _as_int, _pair_key, _ptr_slot_in_range, _as_ident_node, _as_member_node
import regex_compile
import mlir
import ownership_destruct
from ownership_check import _block_terminates
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

def _type_of(gen, name: str) -> str:
    boxed = getattr(gen, '_boxed_mut_locals', None)
    if boxed and name in boxed and name not in gen._captures:
        # See _seed_mut_captured_local_types: `var_types[name]` holds
        # the POINTER ctype (what the real C declaration needs), but
        # ordinary scalar type-inference (e.g. `count + 1`) must see
        # the pointee type instead, exactly like the async mutable-
        # capture mechanism's own `declared` dict does for the same
        # reason (see _gen_cpp_async_unit's docstring).
        return boxed[name]
    return gen.var_types.get(name, 'int64_t')

def _resolve_type(gen, ann: str | None) -> str:
    # Map a C-keyword struct name (`auto`) to its renamed form so a bare
    # `auto` annotation resolves to the struct registered under `_kw_auto`.
    if isinstance(ann, str):
        ann = gen._c_kw_struct_renames.get(ann, ann)
    if ann in gen.struct_field_types:
        return f"{ann} *"
    # A module-qualified annotation (`func: gimple_ctypes.FunctionDef` —
    # this compiler's OWN `gimple_gen_resolve.py` source annotates its
    # extracted-helper params this way) parses to the literal dotted text
    # "gimple_ctypes.FunctionDef" (see _walk_type_expr's MemberExpr
    # branch), which never matches `struct_field_types`'s BARE struct-name
    # keys ("FunctionDef") — so an explicitly annotated parameter fell
    # through to the plain int64_t default exactly as if it had no
    # annotation at all. Concrete failure: `_infer_local_var_types(gen,
    # func: gimple_ctypes.FunctionDef)` compiled with `func` as int64_t,
    # so its own `for node in nodes:` isinstance scan (see gimple_gen_
    # stmts.py's _ensure_bool_cond docstring for the sibling half of this
    # investigation) operated on opaque handles and mis-dispatched a real
    # VarDecl into the MultiAssignStmt branch — SIGSEGV in strcmp on a
    # garbage `.targets` field, on virtually any compiled program with at
    # least one local variable.
    if isinstance(ann, str) and '.' in ann:
        _bare = ann.rsplit('.', 1)[-1]
        if _bare in gen.struct_field_types:
            return f"{_bare} *"
    # _mojo_type is a stateless module-level function with no access to
    # struct_field_types, so a pointer-to-a-known-struct annotation like
    # `UnsafePointer[MoveOnly_Int, MutExternalOrigin]` would otherwise
    # fall through _mojo_type's UnsafePointer branch to its int64_t
    # default, even though the element type IS a real, known struct here.
    if isinstance(ann, str) and '[' in ann:
        base, rest = ann.split('[', 1)
        base = base.strip()
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            elem_ann = gimple_ctypes._split_top_level_commas(rest.rstrip(']').strip())[0].strip()
            elem_ann = gen._c_kw_struct_renames.get(elem_ann, elem_ann)
            # Scalar newtypes (Int, UInt8, Bool, ...) ARE real `struct
            # X(...)` definitions in the stdlib and so CAN end up
            # registered in struct_field_types, but the codegen
            # deliberately erases them to raw C scalars everywhere via
            # _TYPE_MAP — that convention must win here, or e.g.
            # alloc[UInt8]'s return type gets wrongly boxed as "UInt8 *"
            # instead of the correct "uint8_t *".
            if elem_ann in gen.struct_field_types and elem_ann not in gimple_ctypes._TYPE_MAP:
                return f"{elem_ann} *"
    # Same gap as above, for Mojo's OTHER raw-pointer spelling: `*T`
    # (`fn f(p: *SomeStruct)`), parsed by fire_compiler.py as the literal
    # text "*" + T. `_mojo_type` (module-level, no struct_field_types
    # access) now resolves `*Int8`/`*Int64`/... via its own exact-
    # _TYPE_MAP-key check, but a struct element type needs this
    # instance's struct_field_types the same way the UnsafePointer[...]
    # branch above does — otherwise `*SomeStruct` falls through
    # _mojo_type's fallback to the generic int64_t default, same class
    # of bug as the UnsafePointer[MoveOnly_Int, ...] case this docstring
    # already describes.
    if (isinstance(ann, str) and len(ann) > 1 and ann[0] == '*' and ann[1] != '*'):
        elem_ann = gen._c_kw_struct_renames.get(ann[1:].strip(), ann[1:].strip())
        if elem_ann in gen.struct_field_types and elem_ann not in gimple_ctypes._TYPE_MAP:
            return f"{elem_ann} *"
    return gimple_ctypes._mojo_type(ann)

def _infer_param_types(gen, func: gimple_ctypes.FunctionDef,
                       owner_struct: str | None = None) -> dict[str, str]:
    """Infer parameter types from member accesses and function calls in function body.

    First parameter MUST be named `gen` (it was `_g`): only an unannotated
    first param named exactly `gen`/`self` is typed `GimpleGen *` when this
    compiler compiles its own `gimple*.py` source (see `_selfhost_gen_self_
    param_type` in gimple_gen_funcs.py). Named anything else it is `int64_t`,
    so `gen.struct_field_types` became a boxed getattr, `sorted(...)` over it
    missed the `MojoDict *` branch (`mojo_dict_sorted_keys`, elem `char *`)
    and fell through to the generic `mojo_sorted`, which orders by POINTER.
    Heap addresses vary per run under ASLR, so the struct-evidence match
    below picked a different winner each time and this compiler emitted
    DIFFERENT output for the same input on two consecutive runs — observed
    as `_scan_yield_bearing`/`_as_ident_node`/`_as_funcdef_node`/
    `_detect_generator` flipping between `MojoList *` and `int64_t` params
    (and their mangled symbol suffixes with them).

    If a parameter is accessed with .field, infer it's a struct with that field.
    If a parameter is passed to a known function, infer type from that function.

    `owner_struct`: the StructDef whose method `func` is, when it is one —
    needed ONLY so the decision step below can resolve `self.<member>` AugAssign
    sinks against `gen.struct_field_types`; pure signal collection inside
    analyze_param_usage never touches it (see its Phase 3 memoization note).
    """
    inferred = {}

    # Map builtin/common functions to their first parameter type
    # `len` deliberately excluded: passing a param to `len()` means it's
    # a SIZED CONTAINER (str/list/dict/set/tuple — no single correct C
    # type to default to), not that the param's own type IS `int` —
    # that's len()'s RETURN type, not its argument's type. This entry
    # used to wrongly infer 'int' for any unannotated parameter whose
    # ONLY usage signal was `len(param)` (no subscript/iteration to
    # otherwise identify it as MojoList*/char*), producing a compiled
    # function whose parameter was declared `int` while every real
    # caller passed a genuine pointer (str/list) argument — "passing
    # argument 1 of '<fn>' makes integer from pointer without a cast".
    # Found via Doc/includes/ndiff.py's `def main(args): ... if
    # len(args) != 2: ...` (no subscript/for-loop over `args`
    # anywhere in the function, so `len(args)` was the only signal,
    # and this entry silently won).
    BUILTIN_PARAM_TYPES = {
        'open': 'char *',
        'mojo_open_file': 'char *',
        'print': 'char *',
        'str': 'int',
    }

    # Methods that exist ONLY on Python str (never on list/dict/set), so a
    # `param.method(...)` call using one of these unambiguously identifies
    # `param` as a string even when it's also subscripted/sliced elsewhere
    # in the same function (e.g. `src[i]`, `src[a:b]`) — which otherwise
    # looks identical to list/sequence indexing to this analysis. Without
    # this, any unannotated closure parameter that is both subscripted
    # AND string-only-method-called (a very common shape for hand-rolled
    # char-by-char scanners, e.g. fire_compiler.py's own
    # `replace_multiline_strings(src)`) was inferred as `MojoList *`
    # instead of `char *`. That produced a compiled function whose `src`
    # parameter was declared as a MojoList* while the caller actually
    # passed a raw `char *` — every `src[i]` then lowered to
    # `mojo_list_get_int(src, i)`, which dereferences the char* as if it
    # were a MojoList struct pointer and reads garbage/crashes
    # (EXC_BAD_ACCESS) on real input. Found via `stage2/mojo --dump`
    # segfaulting in `mojo_list_get_int` called from
    # `py_tokenize_replace_multiline_strings`, with the faulting address
    # literally spelling out the first bytes of the source file's text —
    # proof `src`'s raw string bytes were being read as a pointer.
    STRING_ONLY_METHODS = {
        'find', 'rfind', 'startswith', 'endswith', 'strip', 'lstrip',
        'rstrip', 'split', 'rsplit', 'splitlines', 'replace', 'lower',
        'upper', 'format', 'isalnum', 'isdigit', 'isspace', 'isupper',
        'islower', 'isalpha', 'zfill', 'capitalize', 'title', 'join',
        'partition', 'rpartition', 'swapcase', 'expandtabs', 'casefold',
    }

    # Methods that exist ONLY on Python dict (never on list/set), so a
    # `param.method(...)` call using one of these unambiguously identifies
    # the param as a dict — same reasoning as STRING_ONLY_METHODS above.
    # Found via Tools/unicode/gencodec.py's `marshalmap(name, map,
    # marshalfile)`: the param's ONLY use is `for e,(u,c) in map.items():`,
    # and the bare member-access struct inference below matched the single
    # registered struct that happens to have an `items` FIELD — WithStmt,
    # an unrelated internal AST node (`WithStmt.items: list`) — typing the
    # param `WithStmt *`. Every real dict argument then flowed through a
    # wrong-struct signature, `.items()` fell to opaque runtime dispatch,
    # and the pair loop ran zero times (mojo_unsupported_iter).
    # `get` belongs here for the same reason as the other four: among this
    # runtime's builtin containers only a dict has it (list/set/tuple/str
    # do not), so `param.get(...)` is unambiguous "param is a dict"
    # evidence. It is already in BUILTIN_CONTAINER_METHODS below, so a
    # struct that happens to define its own `get` method is already
    # excluded from the accessed-field struct match and cannot be
    # misidentified by adding it here.
    DICT_ONLY_METHODS = {'items', 'keys', 'values', 'setdefault', 'get'}

    # Methods that exist ONLY on Python `bytes` (never on str/list/dict/set):
    # `.decode()` turns bytes into str, `.hex()` renders bytes as an ASCII
    # hex string. Neither name is shared with any str/list method this
    # analysis already keys on, so `param.decode(...)` / `param.hex()` is
    # unambiguous "param is bytes" evidence — the only body-usage signal
    # conservative enough to act on (indexing / `in` / `+` / iteration all
    # look identical to str/list and must NOT flip a param to bytes). See
    # bugs/hard/CODEGEN_bytes_value_type.md Stage 2b.
    BYTES_ONLY_METHODS = {'decode', 'hex'}

    # Method names shared across the builtin containers. When one of these
    # is CALLED on the param, it is method-dispatch evidence, NOT evidence
    # of a struct whose FIELD happens to share the name — excluded from the
    # accessed-field struct match below for exactly the WithStmt.items
    # reason documented at DICT_ONLY_METHODS.
    BUILTIN_CONTAINER_METHODS = {
        'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'sort',
        'reverse', 'copy', 'index', 'count', 'keys', 'values', 'items',
        'get', 'update', 'setdefault', 'add', 'discard',
    }

    def analyze_param_usage(nodes: list, param_name: str):
        """Analyze how a parameter is used in a list of statements."""
        accessed_fields = set()
        # Members CALLED as methods on the param (`param.items(...)`) —
        # method dispatch, distinct from bare field reads. Consulted to
        # keep builtin-container method names out of the struct-field
        # match (see BUILTIN_CONTAINER_METHODS above).
        called_methods: set = set()
        # Each entry is `function_name + _FC_SEP + str(arg_index)` — a
        # composite STRING, deliberately NOT a `(name, idx)` 2-tuple: a
        # tuple round-trips its `str` slot through an int64_t box on the
        # self-hosted path, after which `name == 'isinstance'` compared a
        # pointer to a string (and SIGSEGV'd in `_str_hash` when the pointer
        # was a small erased value). `_FC_SEP` is U+001F, not `\x00`: NUL
        # would be swallowed by `mojo_str_cat`'s `strlen`, collapsing the
        # separator on the compiled path so `.split()` could not recover the
        # index.
        function_calls = []
        # The boolean usage signals live in ONE mutable dict rather than as
        # separate `nonlocal` scalars: the nested `scan_expr`/`scan_nodes`/
        # `_track_derivation` closures mutate them, and a container captured
        # by reference propagates cleanly at any nesting depth in the
        # self-hosted backend, where a `nonlocal` SCALAR mut-capture across
        # two closure levels does not (it silently lost every write, so
        # every unannotated container/string parameter mis-inferred as
        # int64_t — the root of self-hosted param-inference weakness).
        _F: dict = {}
        # `is_subscripted`  : parameter used with `[...]`
        # `is_string_method`: `param.<str-only-method>(...)` called
        # `is_dict_method`  : `param.<dict-only-method>(...)` called
        # `is_iterated`     : parameter used as a for-loop iterable
        # Track if a single-character subscript of the param (`param[i]`,
        # directly or via a local it was assigned to, e.g. `c = param[i]`)
        # is ever compared against a string literal (`c == '"'`) — a
        # single char of a real Python list would be some non-string
        # element, never legitimately `==`-compared to a quote-character
        # string literal, so this is as unambiguous a "param is a string"
        # signal as a str-only method call, just one indirection removed.
        # Found chasing gimple_codegen's `_lower_slice`/`_decode_str_
        # literal_text` quote-corruption bug back to its real source:
        # fire_compiler.py's own `_strip_string_prefix_and_quotes(raw)`
        # does `prefix, rest = raw[:n], raw[n:]` (rest is a SLICE of the
        # param, one step removed) then `first = rest[0]; ... if first ==
        # '"' or first == "'": ...` (first is a subscript of THAT, two
        # steps removed) — no str-only method call anywhere, so `raw`
        # (only ever subscripted/sliced, directly or transitively) got
        # inferred as MojoList*, and the caller's real char* argument got
        # force-cast to a MojoList* pointer, corrupting every
        # self-hosted string literal whose own content happens to
        # start/end with a quote. Needs to trace through that whole
        # subscript-of-a-slice-of-the-param chain, not just a single hop.
        # Every local known to hold a value sliced/subscripted (directly
        # or transitively) FROM the param — `derived_from_param` answers
        # "does this trace back to the param at all", `single_char_vars`
        # (a subset) answers "and is this specific derivation a single
        # CHARACTER (non-slice subscript), not another substring".
        derived_from_param: set = {param_name}
        single_char_vars: set = set()
        # Dict-vs-list disambiguation signals for the param's own
        # subscripts. This runtime has exactly two subscriptable
        # containers — MojoList (int64_t indices) and MojoDict (char*
        # keys) — so a subscript whose KEY is provably a string is
        # impossible for a real list and identifies the param as a dict
        # (Lib/test/support/__init__.py's
        # `set_sanitizer_env_var(env, option)`: `env[name] += f':{option}'`
        # with `name` iterating a tuple of string literals was inferred
        # MojoList*, and the store emitted mojo_list_set_int with a char*
        # key/value — hard -Wint-conversion errors). Any OTHER subscript
        # key (int literal, arithmetic, unknown identifier) or any slice
        # keeps the historical sequence interpretation.
        str_vars: set = set()
        # DESIGN.html R4: a THIRD state alongside "provably a string"
        # (str_vars/_expr_is_stringish) and "provably NOT a string"
        # (int_vars/_expr_is_definitely_not_stringish) — a key this
        # analysis simply cannot classify either way must stay UNKNOWN and
        # carry no signal, never get folded into "not a string" (which the
        # subscript-key veto below used to do, via a plain `else:` on
        # `_expr_is_stringish`). See _expr_is_definitely_not_stringish's
        # own docstring for why this matters.
        int_vars: set = set()
        # Hoisted alias, NOT `gen.func_return_types` read directly inside
        # `_expr_is_stringish` below: the nested scanners close over plain
        # LOCALS of this function fine (`str_vars` does), but a nested
        # function reaching for the enclosing `gen` PARAMETER does not
        # survive self-hosting -- the lifted closure body compiled to
        # "error: 'gen' undeclared (first use in this function)". Explicit
        # `: dict` for the same reason the other hoisted-closure captures
        # in this codebase carry one (an unannotated captured dict/set
        # comes back untyped in the lifted function's signature).
        _fn_ret_types: dict = gen.func_return_types
        # `self.<member> += <param-derived value>` sinks (root ident name,
        # member name). An augmented assignment whose RHS involves the param
        # is real Python string/list CONCATENATION-INTO evidence, but the
        # scan itself can't tell a str sink from a list sink — only the
        # decision step can, by resolving the member's declared ctypes
        # against struct_field_types (populated from the class's own
        # `self.<member> = <init>` assignments by gen_module's
        # _collect_self_assigns pass). Collected here as pure names; judged
        # there.
        aug_member_targets: set = set()

        def _is_param_ident(e) -> bool:
            """`e` is a bare read of this parameter. Routes the boxed AST
            handle through `_as_ident_node` so `.name` is a direct field
            load, not a `_mojo_dispatch_getattr` on an int64_t — an
            unguarded `e.name == param_name` here compared a pointer to a
            string and made the subscript / iteration / string-method
            signals for e.g. `py_tokenize.replace_multiline_strings`'s
            `src` register on some runs and not others, flipping the
            param's ctype run to run."""
            return (isinstance(e, gimple_ctypes.IdentExpr)
                    and _as_ident_node(e).name == param_name)

        def _expr_mentions_param(e):
            """Does expression `e` involve `param_name` directly (a bare
            identifier read, or a subscript/slice OF one)? Deliberately
            shallower than a full walk: concatenation sinks take simple
            values (`self._val += data`, `... += data[0:n]`), and every
            extra shape widened here would widen what counts as "param
            flows into this sink" without adding real certainty."""
            if isinstance(e, gimple_ctypes.IdentExpr):
                return _as_ident_node(e).name == param_name
            if isinstance(e, gimple_ctypes.SliceExpr):
                return (_expr_mentions_param(e.obj)
                        or (e.start is not None and _expr_mentions_param(e.start))
                        or (e.stop is not None and _expr_mentions_param(e.stop)))
            if isinstance(e, gimple_ctypes.SubscriptExpr):
                return (_expr_mentions_param(e.obj)
                        or _expr_mentions_param(e.index))
            if isinstance(e, gimple_ctypes.BinaryOp):
                return (_expr_mentions_param(e.left)
                        or _expr_mentions_param(e.right))
            if isinstance(e, gimple_ctypes.UnaryOp):
                return _expr_mentions_param(e.operand)
            return False

        def _expr_is_stringish(e):
            if isinstance(e, gimple_ctypes.StringLiteral):
                return True
            if isinstance(e, gimple_ctypes.TstringLiteral):
                return True
            if isinstance(e, gimple_ctypes.IdentExpr) and e.name in str_vars:
                return True
            # A call to a function whose RESOLVED return type is already
            # known to be `char *` is just as provably a string as a
            # literal — `gen.func_return_types` is populated from real
            # `-> str` annotations/inference, so this is genuine type
            # resolution, not a name whitelist. Without it, the ONLY
            # string-key evidence this analysis accepted was a literal
            # (or a local bound directly to one), so `d[_as_str(x)]` and
            # `k = _as_str(x); d[k]` both read as "key is not provably a
            # string" -> is_nondict_key_subscripted -> the param fell to
            # the `MojoList *` default below.
            #
            # That is exactly how ast_rewriter.py's `match_pattern
            # (pat, term, bindings)` got `MojoList * bindings`: its four
            # subscripts are `bindings[_vn]` (x2, `_vn = _as_str
            # (pat.name)`) and `bindings[_as_str(pat.tail...)]` (x2).
            # Callers pass a real `{}`, so codegen emitted
            # `(MojoList *)mojo_dict_new ()` and lowered every
            # `bindings[k]` to `mojo_list_get_int`/`mojo_list_set_int`.
            # Those index `((MojoList *)dict)->data[key_ptr]`, i.e.
            # `dict->slots + 8 * (int64_t)"key"` — ~34GB past the slot
            # array — so `MOJO_NO_SHIM=1 ./mojoc fire.py --dump-full`
            # took SIGBUS on fire.py's own line 27 (`os.environ['PATH']
            # = ...`, the one statement that reaches
            # `_rewrite_assign_stmt`) 200/200 runs, before writing any
            # output at all. Same class as the `src[i]` ->
            # `mojo_list_get_int(src, i)` char*-as-list bug already
            # described in this function's STRING_ONLY_METHODS note.
            if (isinstance(e, gimple_ctypes.CallExpr)
                    and isinstance(e.func, gimple_ctypes.IdentExpr)
                    and _fn_ret_types.get(
                        _as_ident_node(e.func).name) == 'char *'):
                return True
            return False

        def _expr_is_definitely_not_stringish(e):
            """DESIGN.html R4's third state: PROVABLY not a string (a real
            int literal, arithmetic on one, or a local bound to one) — as
            opposed to merely "not proven to be a string" (which also
            covers keys this analysis just cannot see through, e.g. a
            function parameter or an opaque call result). Only THIS
            predicate may veto the dict-key conclusion below; a genuinely
            unknown key must contribute no signal either way, or an
            unrelated unprovable key on one dict access wrongly overrides
            real string evidence from every other access to the same
            param (the exact bug class already fixed once for the
            evidence side in `_expr_is_stringish`; this is its mirror on
            the veto side)."""
            if isinstance(e, gimple_ctypes.IntLiteral):
                return True
            if (isinstance(e, gimple_ctypes.UnaryOp)
                    and isinstance(e.operand, gimple_ctypes.IntLiteral)):
                return True
            if (isinstance(e, gimple_ctypes.BinaryOp)
                    and e.op in ('+', '-', '*', '//', '%', '<<', '>>', '&', '|', '^')
                    and (_expr_is_definitely_not_stringish(e.left)
                         or _expr_is_definitely_not_stringish(e.right))):
                return True
            if isinstance(e, gimple_ctypes.IdentExpr) and e.name in int_vars:
                return True
            return False

        def _is_single_char_literal(e):
            return isinstance(e, gimple_ctypes.StringLiteral) and len(e.value) <= 3  # quotes + <=1 char

        def scan_expr(expr):
            """Recursively scan an expression."""
            if isinstance(expr, gimple_ctypes.Comprehension):
                # A list/set/dict/generator comprehension embedded inside
                # an expression (`sum(x**2 for x in values)`,
                # `[f(v) for v in values]` used as a call argument, ...)
                # has a structurally different shape (`.generators[i].
                # iterable`/`.element`/`.conditions`, not simple nested
                # expression fields) that this dispatch never recursed
                # into at all -- `values` being the comprehension's own
                # iterable was silently invisible to this whole
                # analysis, so a parameter used ONLY this way (no plain
                # `for x in values:` statement, no direct subscript)
                # got no type signal and defaulted to int64_t while
                # every real caller passed a genuine MojoList* — found
                # via Tools/lockbench/lockbench.py's `jains_fairness
                # (values)`, whose only two uses of `values` are
                # `sum(values)`/`len(values)` (no signal either, same
                # class of gap `len()` was already excluded from) and
                # `sum(x**2 for x in values)` (this exact shape).
                for gen in expr.generators:
                    if _is_param_ident(gen.iterable):
                        _F['is_iterated'] = True
                    scan_expr(gen.iterable)
                    for cond in (gen.conditions or []):
                        scan_expr(cond)
                if expr.key is not None:
                    scan_expr(expr.key)
                scan_expr(expr.element)
            elif isinstance(expr, gimple_ctypes.SubscriptExpr):
                # Check if the base (after unwrapping nested subscripts) is the parameter
                base = expr.obj
                while isinstance(base, gimple_ctypes.SubscriptExpr):
                    base = base.obj
                if _is_param_ident(base):
                    _F['is_subscripted'] = True
                    if _expr_is_stringish(expr.index):
                        _F['is_str_key_subscripted'] = True
                    elif _expr_is_definitely_not_stringish(expr.index):
                        _F['is_nondict_key_subscripted'] = True
                    # else: key is genuinely unprovable either way — no
                    # signal (DESIGN.html R4; previously this `else`
                    # branch folded "unknown" into "not a string", which
                    # could veto real string evidence from every OTHER
                    # subscript on the same param).
                scan_expr(expr.obj)
                scan_expr(expr.index)
            elif isinstance(expr, gimple_ctypes.SliceExpr):
                # Slicing a param means it is an indexable sequence, same as subscript.
                if _is_param_ident(expr.obj):
                    _F['is_subscripted'] = True
                    _F['is_nondict_key_subscripted'] = True
                scan_expr(expr.obj)
                if expr.start is not None: scan_expr(expr.start)
                if expr.stop is not None: scan_expr(expr.stop)
            elif isinstance(expr, gimple_ctypes.MemberExpr):
                if _is_param_ident(expr.obj):
                    accessed_fields.add(_as_str(_as_member_node(expr).member))
                scan_expr(expr.obj)
            elif isinstance(expr, gimple_ctypes.BinaryOp):
                if expr.op == '==':
                    # Indexed, NOT `for a, b in (...)` — a multi-target
                    # unpack over a tuple of AST-node pairs boxes both
                    # slots to int64_t on the self-hosted path (the same
                    # trap already fixed for the dispatch-cdecl reconcile
                    # loop and the module-global scan; see those commits),
                    # after which `isinstance(a, ...)` is always False and
                    # `is_char_compared` never gets set. Confirmed via
                    # unescape_c.py's `next_char == '\\'`-style char
                    # compares flipping the enclosing param's inferred type
                    # between `char *` (shim) and `MojoList *` (self-host).
                    _eq_pairs = ((expr.left, expr.right), (expr.right, expr.left))
                    for _pi in range(2):
                        a = _eq_pairs[_pi][0]
                        b = _eq_pairs[_pi][1]
                        is_direct = (isinstance(a, gimple_ctypes.SubscriptExpr)
                                     and not isinstance(a.index, gimple_ctypes.SliceExpr)
                                     and isinstance(a.obj, gimple_ctypes.IdentExpr)
                                     and a.obj.name in derived_from_param)
                        is_indirect = isinstance(a, gimple_ctypes.IdentExpr) and a.name in single_char_vars
                        if (is_direct or is_indirect) and _is_single_char_literal(b):
                            _F['is_char_compared'] = True
                if expr.op == '+':
                    # `param + <string literal>` / `<string literal> +
                    # param` (directly, or through a local already known
                    # to hold a string) — real Python str concatenation,
                    # which only type-checks when BOTH operands are
                    # strings, so the param is one. Unambiguous even when
                    # the param is ALSO subscripted elsewhere (a list
                    # element + str would be a TypeError in real Python).
                    # Found via Lib/ctypes/macholib/dyld.py's `_inject`
                    # generator: `yield path[:-len('.dylib')] + suffix +
                    # '.dylib'` — `suffix` had no other string signal (no
                    # str-only method call, no subscript) and defaulted
                    # to int64_t, so the coroutine body's co_yield hit
                    # "invalid conversion from 'int64_t' to 'char*'".
                    # Indexed, NOT `for _a, _b in (...)` — same self-hosted
                    # boxed-2-tuple-unpack trap as the `==` case just above.
                    _add_pairs = ((expr.left, expr.right), (expr.right, expr.left))
                    for _pi in range(2):
                        _a = _add_pairs[_pi][0]
                        _b = _add_pairs[_pi][1]
                        if not _is_param_ident(_a):
                            continue
                        if _expr_is_stringish(_b):
                            _F['is_string_method'] = True
                        elif (isinstance(_b, gimple_ctypes.IdentExpr)
                                and _as_ident_node(_b).name != param_name
                                and _as_ident_node(_b).name in str_vars):
                            _F['is_string_method'] = True
                scan_expr(expr.left)
                scan_expr(expr.right)
            elif isinstance(expr, gimple_ctypes.CompareChain):
                for o in expr.operands: scan_expr(o)
            elif isinstance(expr, gimple_ctypes.UnaryOp):
                scan_expr(expr.operand)
            elif isinstance(expr, gimple_ctypes.CallExpr):
                # Track which functions this parameter is passed to
                if isinstance(expr.func, gimple_ctypes.IdentExpr):
                    func_name = _as_ident_node(expr.func).name
                    for i, arg in enumerate(expr.args):
                        if (isinstance(arg, gimple_ctypes.IdentExpr)
                                and _as_ident_node(arg).name == param_name):
                            function_calls.append(_as_str(func_name) + _FC_SEP + str(i))
                elif isinstance(expr.func, gimple_ctypes.MemberExpr):
                    # `_as_member_node`: `expr.func` is a chained expr, which
                    # the self-hosted backend does not narrow through
                    # `isinstance`, so every `.obj`/`.member` read below would
                    # otherwise lower to `_mojo_dispatch_getattr` on an
                    # int64_t and compare a pointer to a string — the
                    # `src.find(...)` string-method evidence for
                    # `py_tokenize.replace_multiline_strings`'s `src` then
                    # registered on some runs and not others, flipping the
                    # param's ctype (char * <-> int64_t) run to run.
                    _efunc = _as_member_node(expr.func)
                    _efunc_obj = _efunc.obj
                    _efunc_obj_name = (_as_ident_node(_efunc_obj).name
                                       if isinstance(_efunc_obj, gimple_ctypes.IdentExpr)
                                       else None)
                    # Method-call evidence is recognized through a SLICE or
                    # SUBSCRIPT of the param too (`s[:-1].split(",")`,
                    # ftplib.py's mlsd): Python str methods return strs, so
                    # calling one on any slice/subscript chain rooted at the
                    # param proves the root is a string exactly as strongly
                    # as a direct call — previously only the DIRECT
                    # `param.method(...)` shape was recognized, so a param
                    # whose only string evidence was indirect fell through
                    # to the subscript/slice default below and got inferred
                    # MojoList*.
                    _meth_recv = _efunc_obj
                    while isinstance(_meth_recv, (gimple_ctypes.SubscriptExpr,
                                                  gimple_ctypes.SliceExpr)):
                        _meth_recv = _meth_recv.obj
                    # param.<str-only-method>(...) — see STRING_ONLY_METHODS
                    # comment above: unambiguous evidence param is a string,
                    # even if it's also subscripted elsewhere.
                    if (_efunc_obj_name == param_name
                            and _efunc.member in STRING_ONLY_METHODS):
                        _F['is_string_method'] = True
                    # param.<bytes-only-method>(...) — unambiguous "param is
                    # bytes" (see BYTES_ONLY_METHODS).
                    if ((_efunc_obj_name == param_name
                            or (_meth_recv is not _efunc_obj
                                and isinstance(_meth_recv, gimple_ctypes.IdentExpr)
                                and _as_ident_node(_meth_recv).name == param_name))
                            and _efunc.member in BYTES_ONLY_METHODS):
                        _F['is_bytes_method'] = True
                    # <slice/subscript-of-param>.<str-only-method>(...) —
                    # the indirect twin just above.
                    if (_meth_recv is not _efunc_obj
                            and isinstance(_meth_recv, gimple_ctypes.IdentExpr)
                            and _as_ident_node(_meth_recv).name == param_name
                            and _efunc.member in STRING_ONLY_METHODS):
                        _F['is_string_method'] = True
                    # param.<dict-only-method>(...) — same unambiguous
                    # "param is a dict" evidence (see DICT_ONLY_METHODS).
                    if _efunc_obj_name == param_name:
                        if _efunc.member in DICT_ONLY_METHODS:
                            _F['is_dict_method'] = True
                        if _efunc.member in BUILTIN_CONTAINER_METHODS:
                            called_methods.add(_efunc.member)
                    # Handle re.sub(pattern, fn, src) → src (index 2) is char*
                    if (_efunc_obj_name == 're'
                            and _efunc.member == 'sub'
                            and len(expr.args) >= 3):
                        _a2 = expr.args[2]
                        if (isinstance(_a2, gimple_ctypes.IdentExpr)
                                and _as_ident_node(_a2).name == param_name):
                            function_calls.append('__re_sub_src' + _FC_SEP + '2')
                    # os.path.*(param, ...) — basename/splitext/expanduser/
                    # abspath/dirname/exists/join all take char* path
                    # arguments (see the os.path.* block in lower_expr).
                    # Not tracked before: a MemberExpr call func (anything
                    # but the re.sub special case above) was silently
                    # ignored here, so a parameter *only* ever used as
                    # os.path.basename(param) got no type hint at all and
                    # defaulted to int64_t. Real bug found via
                    # build_executable(input_file, ...) in fire.py, where
                    # input_file is used via
                    # os.path.basename(os.path.splitext(input_file)) —
                    # the parameter held a real char* pointer throughout,
                    # just declared with the wrong C type, so print(x)
                    # showed a raw address instead of the string.
                    elif (isinstance(_efunc_obj, gimple_ctypes.MemberExpr)
                            and isinstance(_as_member_node(_efunc_obj).obj, gimple_ctypes.IdentExpr)
                            and _as_ident_node(_as_member_node(_efunc_obj).obj).name == 'os'
                            and _as_member_node(_efunc_obj).member == 'path'
                            and _efunc.member in (
                                'basename', 'splitext', 'split', 'splitdrive',
                                'splitroot', 'expanduser',
                                'abspath', 'dirname', 'exists', 'join')):
                        for i, arg in enumerate(expr.args):
                            if (isinstance(arg, gimple_ctypes.IdentExpr)
                                    and _as_ident_node(arg).name == param_name):
                                function_calls.append('__os_path_arg' + _FC_SEP + str(i))
                scan_expr(expr.func)
                for arg in expr.args:
                    scan_expr(arg)

        def scan_nodes(node_list):
            """Recursively scan a list of statements."""
            def _track_derivation(target, value):
                """`x = <subscript/slice of something already known to
                derive from param>` — propagate that knowledge to `x` too,
                so a chain like `rest = raw[n:]` then `first = rest[0]`
                (two hops from the param) is still recognized. Single-index
                subscripts additionally join single_char_vars (a single
                CHARACTER, eligible for the `== '"'`-style check);  slices
                only join derived_from_param (still a string/substring,
                not a lone char)."""
                if not isinstance(target, gimple_ctypes.IdentExpr):
                    return
                _tname = _as_ident_node(target).name
                if (isinstance(value, gimple_ctypes.SubscriptExpr)
                        and not isinstance(value.index, gimple_ctypes.SliceExpr)
                        and isinstance(value.obj, gimple_ctypes.IdentExpr)
                        and _as_ident_node(value.obj).name in derived_from_param):
                    single_char_vars.add(_tname)
                    derived_from_param.add(_tname)
                elif (isinstance(value, gimple_ctypes.SliceExpr)
                        and isinstance(value.obj, gimple_ctypes.IdentExpr)
                        and _as_ident_node(value.obj).name in derived_from_param):
                    derived_from_param.add(_tname)
            for node in node_list:
                if isinstance(node, gimple_ctypes.AssignStmt):
                    if isinstance(node.target, gimple_ctypes.TupleExpr) and isinstance(node.value, gimple_ctypes.TupleExpr):
                        # `prefix, rest = raw[:n], raw[n:]` — pair up each
                        # target/value slot, same as fire_compiler.py's own
                        # `_strip_string_prefix_and_quotes`.
                        for t_el, v_el in zip(node.target.elements, node.value.elements):
                            _track_derivation(t_el, v_el)
                    else:
                        _track_derivation(node.target, node.value)
                    if (isinstance(node.target, gimple_ctypes.IdentExpr)
                            and _expr_is_stringish(node.value)):
                        # `_expr_is_stringish`, not just StringLiteral: a
                        # local bound to a `-> str` call (`_vn = _as_str
                        # (pat.name)`) is every bit as provably a string
                        # as one bound to a literal, and is the shape the
                        # `_as_str`/`_as_list` static-view cast idiom used
                        # all over this codebase actually produces. The
                        # literal-only form meant `k = _as_str(x); d[k]`
                        # left `k` untracked, so `d`'s key looked
                        # unprovable and `d` was typed `MojoList *` — see
                        # _expr_is_stringish's own note for the SIGBUS
                        # this produced in ast_rewriter.py.
                        str_vars.add(_as_ident_node(node.target).name)
                    elif (isinstance(node.target, gimple_ctypes.IdentExpr)
                            and _expr_is_definitely_not_stringish(node.value)):
                        # Mirror of the str_vars tracking just above, for
                        # the OTHER provable state (DESIGN.html R4): `k =
                        # some_int_expr; d[k]` is real evidence the key is
                        # NOT a string, same strength as a literal int key
                        # inline.
                        int_vars.add(_as_ident_node(node.target).name)
                    scan_expr(node.target)
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.ExprStmt):
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.ReturnStmt):
                    if node.value:
                        scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.IfStmt):
                    scan_expr(node.condition)
                    scan_nodes(node.then_body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                    for _, elif_body in node.elifs:
                        scan_nodes(elif_body)
                elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
                    if isinstance(node, gimple_ctypes.WhileStmt):
                        scan_expr(node.condition)
                    if isinstance(node, gimple_ctypes.ForStmt):
                        # Detect `for x in <param>:` — evidence param is a list
                        it = node.iterable
                        if _is_param_ident(it):
                            _F['is_iterated'] = True
                        # `for name in ('A', 'B', ...):` — every element of
                        # an all-string-literal tuple/list/set literal is a
                        # string, so the loop target is a string variable (a
                        # dict-key source for `param[name]` subscripts).
                        if (isinstance(it, (gimple_ctypes.TupleExpr,
                                            gimple_ctypes.ListExpr,
                                            gimple_ctypes.SetExpr))
                                and it.elements
                                and all(isinstance(el, gimple_ctypes.StringLiteral)
                                        for el in it.elements)):
                            tgt = node.target
                            if isinstance(tgt, gimple_ctypes.IdentExpr):
                                str_vars.add(tgt.name)
                            elif isinstance(tgt, str):
                                str_vars.add(tgt)
                        scan_expr(node.iterable)
                    scan_nodes(node.body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                elif isinstance(node, gimple_ctypes.AugAssignStmt):
                    scan_expr(node.target)
                    scan_expr(node.value)
                    # `self.<member> += <param-derived>` — record the sink
                    # member for the decision step (see aug_member_targets'
                    # declaration above). Found via Tools/gdb/libpython.py's
                    # TruncatedStringIO.write(self, data): both of data's
                    # non-len uses are `self._val += data` /
                    # `self._val += data[0:n]`, and __init__ declares
                    # `self._val = ''` — so struct_field_types knows the sink
                    # is char* and real Python semantics (str += <list> is a
                    # TypeError) make the param one too. Without this signal,
                    # the slice alone typed data MojoList*, the body lowered
                    # len()/slice as list ops against a char* self->_val, and
                    # the += emitted raw `char * + MojoList *` pointer
                    # addition — gcc -fgimple "internal compiler error: in
                    # build2, at tree.cc" (bugs/
                    # COMPILE_FAIL_Tools_gdb_libpython.md).
                    if isinstance(node.target, gimple_ctypes.MemberExpr) \
                            and _expr_mentions_param(node.value):
                        _aug_root = node.target.obj
                        while isinstance(_aug_root, gimple_ctypes.MemberExpr):
                            _aug_root = _aug_root.obj
                        if isinstance(_aug_root, gimple_ctypes.IdentExpr):
                            aug_member_targets.add((_aug_root.name,
                                                    node.target.member))
                elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                    for t in node.targets:
                        scan_expr(t)
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.VarDecl):
                    if node.value:
                        scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.WithStmt):
                    # Scan the context expressions (e.g., open(input_file))
                    for item in node.items:
                        scan_expr(item.expr)
                    scan_nodes(node.body)
                elif isinstance(node, gimple_ctypes.TryStmt):
                    scan_nodes(node.body)
                    for handler in node.handlers:
                        if handler.exc_type:
                            scan_expr(handler.exc_type)
                        scan_nodes(handler.body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                    if node.finally_body:
                        scan_nodes(node.finally_body)

        scan_nodes(nodes)
        is_subscripted = bool(_F.get('is_subscripted'))
        is_string_method = bool(_F.get('is_string_method'))
        is_dict_method = bool(_F.get('is_dict_method'))
        is_iterated = bool(_F.get('is_iterated'))
        is_char_compared = bool(_F.get('is_char_compared'))
        is_str_key_subscripted = bool(_F.get('is_str_key_subscripted'))
        is_nondict_key_subscripted = bool(_F.get('is_nondict_key_subscripted'))
        is_bytes_method = bool(_F.get('is_bytes_method'))
        return (accessed_fields, function_calls, is_subscripted, is_string_method,
                is_iterated, is_char_compared, is_str_key_subscripted,
                is_nondict_key_subscripted, called_methods, is_dict_method,
                aug_member_targets, is_bytes_method)

    # For each parameter without a type annotation, infer from usage
    for pname, ptype in func.params:
        if ptype is None:
            # Phase 3 (bugs/hard/PERF_nested_module_compile_walk_ast_
            # quadratic_rescan.md): `analyze_param_usage` is an
            # expensive recursive body scan and a PURE function of
            # (func.body, pname) — no `self.*` state read anywhere in
            # scan_nodes/scan_expr (confirmed by inspection) — so its
            # raw usage-signal result is memoized here, keyed by
            # id(func)+pname, shared tree-wide via
            # `self._param_usage_scan_cache` exactly like
            # `_field_scan_var_cache` (Phase 2). Only the SIGNALS are
            # cached, not the final inferred type below, which also
            # depends on `self.struct_field_types` (grows monotonically
            # during compilation — the same time-dependent-filter trap
            # Phase 2 already had to work around) and must therefore
            # still be recomputed fresh on every call.
            # `_pair_key(str(id(func)), pname)`, NOT `(id(func), pname)`. The
            # 2-tuple form is keyed by the TUPLE's own heap address once
            # self-hosted — a fresh allocation per `.get()` — so a lookup
            # spuriously misses (or hits a stale unrelated entry, which fed
            # fire_compiler.py's `_emit_pair`'s `v` a `_value` field access
            # it never makes -> inferred `_MojoPointerBase *`). `id(func)` is
            # still address-based, but it is a within-run-stable per-object
            # int used ONLY as a memo key here (never emitted), exactly like
            # gimple_module_gen.py's own `_generator_fns[id(n)]` etc.;
            # stringifying it makes the dict key on CONTENT, not tuple-address.
            _pu_key = _pair_key(str(id(func)), pname)
            _pu_cached = gen._param_usage_scan_cache.get(_pu_key)
            if _pu_cached is not None:
                (fields_accessed, function_calls, is_subscripted, is_string_method,
                 is_iterated, is_char_compared, is_str_key_subscripted,
                 is_nondict_key_subscripted, called_methods, is_dict_method,
                 aug_member_targets, is_bytes_method) = _pu_cached
            else:
                (fields_accessed, function_calls, is_subscripted, is_string_method,
                 is_iterated, is_char_compared, is_str_key_subscripted,
                 is_nondict_key_subscripted, called_methods, is_dict_method,
                 aug_member_targets, is_bytes_method
                 ) = analyze_param_usage(func.body, pname)
                gen._param_usage_scan_cache[_pu_key] = (
                    fields_accessed, function_calls, is_subscripted, is_string_method,
                    is_iterated, is_char_compared, is_str_key_subscripted,
                    is_nondict_key_subscripted, called_methods, is_dict_method,
                    aug_member_targets, is_bytes_method)
            # The SET slots round-trip through the return tuple as int64_t on
            # the self-hosted path (packed/unpacked with the int accessor) —
            # re-view them as `MojoSet *` so the struct-evidence set
            # arithmetic below works (`format_token(tok)` -> `Token *`).
            fields_accessed = _as_set(fields_accessed)
            called_methods = _as_set(called_methods)

            # If passed to isinstance() as first arg, it's polymorphic → keep as int64_t
            # Explicit indexed loop, NOT `any(fn == 'isinstance' and ai == 0
            # for fn, ai in function_calls)`. That one line stacked BOTH of
            # this backend's documented self-hosting traps:
            #   * `any(<generator expression>)` — a bare genexpr's body has
            #     appended nothing on the compiled path (see _gen_compr_
            #     append's own note), so `any(...)` answered False; and
            #   * `for fn, ai in <list of 2-tuples>` — a tuple unpack over
            #     list elements boxes BOTH slots to int64_t, after which
            #     `fn == 'isinstance'` compares a boxed pointer against a
            #     string. Same shape gimple_module_gen.py's module-globals
            #     loop had to index rather than unpack.
            # Indexing the tuple and recovering each slot's real type is the
            # established fix for both.
            #
            # This flag is load-bearing for DETERMINISM, not just accuracy:
            # it is what keeps a genuinely polymorphic parameter at int64_t.
            # `fire_compiler.py`'s own `_scan_yield_bearing(node, out_ids)`
            # is exactly that — `node` is a list, a dataclass, or None — and
            # when this came out False the `is_subscripted or is_iterated`
            # rule below typed `node` as `MojoList *` on the strength of the
            # `for item in node:` that sits INSIDE `if isinstance(node,
            # list):`. It did so on some runs and not others, which flipped
            # the function's mangled symbol, which reordered the string-
            # literal pool, which renumbered every `_slit_N` in the file:
            # the same binary emitted a different .ci for the same input on
            # consecutive runs.
            is_polymorphic = False
            for _fc in function_calls:
                _fcp = _as_str(_fc).split(_FC_SEP)
                if _fcp[0] == 'isinstance' and int(_fcp[1]) == 0:
                    is_polymorphic = True
                    break
            if is_polymorphic:
                continue  # leave as int64_t (default for unannotated)

            # `param.decode(...)` / `param.hex()` anywhere in the body is
            # unambiguous "param is bytes" — no str/list/dict method shares
            # those names. Wins over every other signal (subscript / `in` /
            # `+` / iteration all look list-or-str-shaped and must not, on
            # their own, reach here). See BYTES_ONLY_METHODS.
            if is_bytes_method:
                inferred[pname] = 'MojoBytes *'
                continue

            # If parameter is subscripted OR iterated (for x in param:), it's
            # indexable (list/dict/etc.) — UNLESS it's also called with a
            # str-only method (STRING_ONLY_METHODS above), in which case
            # indexing is char-by-char string scanning and the real type is
            # char*, not MojoList*. Check subscript/iteration FIRST to
            # override generic function-call inference like len() either way.
            if is_subscripted or is_iterated:
                if is_str_key_subscripted and not is_nondict_key_subscripted:
                    # Every provable subscript key is a string (a string
                    # literal, f-string, or a local bound to one) and there
                    # is no int-keyed subscript/slice anywhere — impossible
                    # for a real list under this runtime's int64_t-index
                    # lists, so the param is a dict. See the signals'
                    # declaration above for the motivating repro.
                    inferred[pname] = 'MojoDict *'
                else:
                    # `self.<member> += <param>` evidence: every such sink
                    # member whose declared ctype is resolvable must be char*
                    # (and at least one sink must exist) — a genuine list
                    # operand on a str sink would be a TypeError in real
                    # Python. Requires owner_struct to resolve `self`;
                    # unresolvable sinks make this signal silent (no flip),
                    # never wrong. Motivating repro in aug_member_targets's
                    # declaration above.
                    _aug_into_str = (
                        bool(aug_member_targets) and owner_struct is not None
                        and all(
                            _root == 'self'
                            and gen.struct_field_types.get(owner_struct, {}).get(_member) == 'char *'
                            for _root, _member in aug_member_targets))
                    if is_string_method or is_char_compared or _aug_into_str:
                        inferred[pname] = 'char *'
                    elif is_dict_method:
                        # A dict-only method call (see DICT_ONLY_METHODS) is
                        # POSITIVE evidence that the param is a dict, whereas
                        # reaching this branch only means "some subscript key
                        # could not be PROVEN to be a string" — the absence of
                        # evidence, not evidence of a list. The unambiguous
                        # signal has to win, or a dict subscripted with a key
                        # whose stringness this analysis cannot see through
                        # (e.g. `d[f(x)]`, where `f` is a local helper
                        # returning str) is silently typed `MojoList *`.
                        #
                        # Real repro: gen_module_impl's own nested
                        # `_collect_self_assigns(body, param_types, found)`
                        # does `found.get(fn)` / `fn not in found` /
                        # `found[fn] = ft` with `fn = _self_member(...)`. The
                        # `found[fn]` subscript alone made this branch pick
                        # `MojoList *`, so every `self.X = ...` field the pass
                        # discovered was written into a dict-shaped value
                        # through list accessors and lost. Every class whose
                        # fields come only from `__init__` assignments then
                        # emitted as an empty `typedef struct X { int _dummy; }`
                        # stub on the self-hosted path, and each of its
                        # `_mojo_getattr_X`/`_mojo_repr_X` reflection helpers
                        # was referenced but never defined.
                        inferred[pname] = 'MojoDict *'
                    else:
                        inferred[pname] = 'MojoList *'

            # If not subscripted, try to infer from function calls
            elif function_calls:
                # `function_calls` holds `name<_FC_SEP>idx` composite STRINGS,
                # not `(name, idx)` tuples — a tuple round-trips its `str`
                # slot through an int64_t box on the self-hosted path, after
                # which `func_name == '__re_sub_src'` compared a pointer to a
                # string and `gen._KNOWN_SIGS.get(func_name)` keyed a dict on
                # a pointer decimal (and, when that pointer was a small erased
                # value, SIGSEGV'd in `_str_hash`). The inferred ctype of e.g.
                # `py_tokenize.replace_multiline_strings`'s `src` then flipped
                # `char *` ↔ `int64_t` from run to run.
                for _fc in function_calls:
                    _fcp = _as_str(_fc).split(_FC_SEP)
                    func_name = _fcp[0]
                    arg_index = int(_fcp[1])
                    # re.sub src argument (index 2) is always char*
                    if func_name == '__re_sub_src':
                        inferred[pname] = 'char *'
                        break
                    # os.path.*(param) — see the MemberExpr scan above
                    if func_name == '__os_path_arg':
                        inferred[pname] = 'char *'
                        break
                    # Infer from known function signatures
                    sig = gen._KNOWN_SIGS.get(func_name)
                    if sig is not None and arg_index < len(sig[1]):
                        inferred[pname] = sig[1][arg_index]
                        break
                    # For first argument (index 0) of known functions, use known types
                    if arg_index == 0 and func_name in BUILTIN_PARAM_TYPES:
                        inferred[pname] = BUILTIN_PARAM_TYPES[func_name]
                        break
                    # map(fn, iterable) — the iterable is arg index 1 (not 0,
                    # unlike list()/sorted()/len() above), and it must come out
                    # pointer-shaped (MojoList *) so it round-trips through
                    # mojo_map's `void *` iterable parameter/return instead of
                    # defaulting to int64_t, which produces a real GCC
                    # -Wint-conversion error at the mojo_map call site (passing
                    # an int64_t where mojo_map expects void*) — see
                    # bugs/CODEGEN_map_over_untyped_param_arg.md.
                    if func_name == 'map' and arg_index == 1:
                        inferred[pname] = 'MojoList *'
                        break

            # If no type inferred from functions, try from struct member accesses
            # Only infer struct type if exactly one struct matches (avoid ambiguity)
            if pname not in inferred and len(fields_accessed) > 0:
                # A member CALLED as a builtin-container method on the param
                # (`map.items()`) is method dispatch, not field evidence —
                # without this exclusion the single registered struct with a
                # same-named FIELD won (WithStmt.items → `WithStmt *` for
                # gencodec.py's marshalmap/python_mapdef_code `map` params).
                # Build the evidence list from `sorted(<plain set>)` +
                # explicit membership, NOT `fields_accessed - (called_methods
                # & BUILTIN_CONTAINER_METHODS)` (a set DIFFERENCE of a set
                # INTERSECTION) — those compound set ops lose str-slot
                # tracking on the self-hosted path, so `sorted(...)` then
                # `_as_str(elem)` viewed GARBAGE bytes and the
                # `elem not in sfields` check came out non-deterministic
                # (a struct-type collapse that differs run to run — the
                # `AssertStmt_parse_module` / spurious `_funcptr_<S>_<f>`
                # stage2-vs-stage3 diffs).
                _struct_evidence_list = []
                for _fe in sorted(fields_accessed):
                    _fes = _as_str(_fe)
                    if _fes in called_methods and _fes in BUILTIN_CONTAINER_METHODS:
                        continue
                    _struct_evidence_list.append(_fes)
                # Explicit nested loops, NOT `[sname for sname, sfields in
                # .items() if all(f in sfields for f in ...)]`: the
                # comprehension form (2-tuple `.items()` target + an
                # `all(genexpr)` whose inner `f in sfields` reads the dict
                # value slot) miscompiled on the self-hosted path — every
                # unannotated struct-typed parameter (e.g. fire.py's own
                # `format_token(tok)` -> `Token *`) stayed int64_t.
                # `sorted(struct_evidence)`, not a bare `for f in
                # struct_evidence`: iterating a str-SET lowers to
                # mojo_set_iter_val_int (0 for every string slot) on the
                # self-hosted path; `sorted()` goes through mojo_set_sorted
                # which handles string slots.
                # `_as_str` per element: `sorted()` of a str-set returns a
                # MojoList whose element type the backend doesn't track, so
                # `for f in _evidence_fields` reads each string via the int
                # accessor and `f in sfields` then stringifies the pointer.
                _evidence_fields = _struct_evidence_list
                matches: list = []
                if len(_evidence_fields) > 0:
                    for sname in sorted(gen.struct_field_types):
                        sfields = gen.struct_field_types[_as_str(sname)]
                        _all_present = True
                        for _f0 in _evidence_fields:
                            if _f0 not in sfields:
                                _all_present = False
                                break
                        if _all_present:
                            matches.append(_as_str(sname))
                if len(matches) == 1:
                    inferred[pname] = f"{matches[0]} *"
            # A dict-only method call with no better signal: the param is a
            # dict (see DICT_ONLY_METHODS above).
            if pname not in inferred and is_dict_method:
                inferred[pname] = 'MojoDict *'

            # Last resort: string-only evidence (a str-only method call or
            # string concatenation, with no field access suggesting a
            # struct) — see the BinaryOp '+' scan above for the motivating
            # dyld.py `suffix` shape.
            if pname not in inferred and is_string_method and len(fields_accessed) == 0:
                inferred[pname] = 'char *'

    return inferred

def _seed_addressed_locals(gen, body: list):
    """Pre-scan `body` (BEFORE any statement in it compiles) for every
    plain-call `UnsafePointer(to=x)` / `Pointer(to=x)` / `OwnedPointer(
    to=x)` / `ArcPointer(to=x)` (the keyword-argument constructor shape
    with no `[T]` subscript -- see `_lower_call`'s own handling of it in
    gimple_gen_calls.py) whose `to=` target is a bare identifier, and
    record that name in `self._addressed_locals` up front.

    Must run as a genuine whole-body PRE-pass, not a mark-as-you-go step
    at the address-of call site itself: `-fgimple`'s addressability
    restriction is WHOLE-FUNCTION, not flow-sensitive, so a read of the
    same name occurring TEXTUALLY BEFORE its own `UnsafePointer(to=...)`
    call needs the exact same `_lower_IdentExpr` materialization
    treatment as one occurring after (confirmed via std/collections/
    list.mojo's SIMD `extend` overload, whose `assert count <= value.
    size` reads `value` several lines before its own `UnsafePointer(to=
    value)` -- marking only at the call site left that earlier read
    unprotected, a real regression this pre-pass fixes). No type lookup
    is needed here (unlike `_seed_mut_captured_local_types`'s heap-
    boxing, which must declare a concrete pointee ctype up front):
    `_lower_IdentExpr` already computes each name's ctype itself, at
    the point it materializes a read of it."""
    for node in gimple_exprtypes._walk_ast(body):
        if not (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
                and node.func.name in _POINTER_CTOR_NAMES and not node.args):
            continue
        for k, v in (getattr(node, 'kwargs', None) or []):
            if k == 'to' and isinstance(v, IdentExpr):
                gen._addressed_locals.add(v.name)

def _closure_info_for_ident(gen, name: str):
    """Resolve a bare identifier reference to the ClosureInfo of the
    nested function it names, or None if `name` is not a closure in
    scope. Checks the current function's own registered closures (a
    closure referenced from its own enclosing body — e.g. `return add`
    inside `make_adder`) and, while compiling a lifted closure or
    lambda body, the ENCLOSING function's closures too (a sibling
    nested function referenced as a value — the same scoping
    `_lower_call`'s `_lower_outer_closure_call` already gets via
    `_lambda_outer_closures`)."""
    _cur = getattr(gen, '_all_closures', {}).get(gen.current_func_name, {})
    ci = _cur.get(name)
    if ci is not None:
        return ci
    return getattr(gen, '_lambda_outer_closures', {}).get(name)

def _collect_return_types(gen, stmts: list, acc: list):
    """Collect return-expression C types from all ReturnStmt nodes."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.ReturnStmt):
            acc.append('void' if node.value is None else gen._quick_type(node.value))
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_return_types(node.then_body, acc)
            for _, eb in node.elifs:
                gen._collect_return_types(eb, acc)
            if node.else_body:
                gen._collect_return_types(node.else_body, acc)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_return_types(node.body, acc)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_return_types(node.body, acc)
            for h in node.handlers:
                gen._collect_return_types(h.body, acc)
            if node.else_body:
                gen._collect_return_types(node.else_body, acc)
            if node.finally_body:
                gen._collect_return_types(node.finally_body, acc)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_return_types(node.body, acc)

def _infer_return_type(gen, body: list) -> str:
    """Infer return type by scanning body for ReturnStmt nodes."""
    acc: list[str] = []
    gen._collect_return_types(body, acc)
    return gimple_ctypes.TypeLattice.join_all(acc) if acc else 'void'

def _prepass_list_elem(gen, elements) -> str:
    """Element type of a container literal for the pre-pass. Mirrors
    _infer_list_elem_type but resolves identifier elements through the
    local container-element map instead of var_types (empty during Pass
    2c) — e.g. `return ctype, cval` where cval was unpacked from an
    earlier char*-tuple call."""
    if not elements:
        return 'int64_t'
    types = []
    for e in elements:
        le = gen._quick_container_elem(e)
        types.append(le if le is not None else gen._quick_type(e))
    return gimple_ctypes.TypeLattice.join_all(types) if types else 'int64_t'

def _scan_container_elems(gen, body: list) -> tuple[dict, dict, dict]:
    """Best-effort static element-type map for local containers in a body.

    Returns (elem, nested, dict_val): var name -> element C type, (when the
    element is itself a list) var name -> the inner list's element C type,
    and var name -> dict value C type. Derived by replaying list-literal
    assignments, `.append(...)` calls, and `d[k] = v` subscript assignments.
    Used to build the cross-call element-type contract: a caller knows
    `bodies` is a list of double-lists; the callee param must inherit that
    so `bodies[i][j]` reads with the right getter instead of silently
    defaulting to int.

    Recurses into every nested compound statement, INCLUDING a nested
    `FunctionDef` (a closure) — it has its own `.body` list attribute, so
    the generic `for attr in (...)` walk below descends into it same as
    an `if`/`for`/`try` block. This matters: this whole pre-pass exists
    to run BEFORE any codegen for this function OR its closures, so a
    dict/list only ever written inside a nested closure (e.g.
    replace_multiline_strings's `repl()` doing `string_cache[ph] = ...`)
    still gets its value type recorded under the STABLE outer variable
    name, visible to a read anywhere else in the same function (inside
    or outside the closure) regardless of codegen ordering — unlike the
    reactive, codegen-time AssignStmt-lowering bookkeeping alone would
    be: that only records a dict/list's value type at its own
    assignment site, keyed by whatever C variable/temp is in scope
    *there* — for a variable captured into a nested closure, a read of
    it anywhere outside that closure uses a completely different C
    temp (see _lower_IdentExpr's captures branch), so a write recorded
    only reactively, from inside the closure, would never be visible to
    that outside read regardless of which one gets codegen'd first.
    Scanning for the write ahead of time and keying the result on the
    stable *Python* variable name sidesteps the whole ordering problem.
    """
    elem: dict[str, str] = {}
    nested: dict[str, str] = {}
    dict_val: dict[str, str] = {}

    def note_list_literal(v: str, lit: gimple_ctypes.ListExpr):
        _e = gen._infer_list_elem_type(lit.elements)
        # See _literal_elements_include_none's docstring (_lower_list_
        # literal's identical guard, which THIS pre-pass duplicates the
        # underlying inference of): don't seed an int64_t-joined list's
        # element type here either when the literal spells out a
        # `None` among its elements, or _list_repr_fn would still route
        # print(name)/repr(name) through mojo_repr_list_ints (no None-
        # sentinel check) via this pre-pass's seeded entry, even though
        # _lower_list_literal's own (later) codegen-time assignment
        # correctly left it unset.
        if not (_e == 'int64_t' and gen._literal_elements_include_none(lit.elements)):
            elem[v] = _e
        if lit.elements and isinstance(lit.elements[0], gimple_ctypes.ListExpr):
            elem[v] = 'MojoList *'
            nested[v] = gen._infer_list_elem_type(lit.elements[0].elements)

    def walk(stmts):
        for n in stmts:
            if isinstance(n, gimple_ctypes.AssignStmt) and isinstance(n.target, gimple_ctypes.IdentExpr):
                v, val = n.target.name, n.value
                if isinstance(val, gimple_ctypes.ListExpr):
                    note_list_literal(v, val)
                elif isinstance(val, gimple_ctypes.IdentExpr) and val.name in elem:
                    elem[v] = elem[val.name]
                    if val.name in nested:
                        nested[v] = nested[val.name]
            elif (isinstance(n, gimple_ctypes.AssignStmt) and isinstance(n.target, gimple_ctypes.SubscriptExpr)
                    and isinstance(n.target.obj, gimple_ctypes.IdentExpr)):
                v = n.target.obj.name
                vt = gen._quick_type(n.value)
                if vt and (vt in ('char *', 'double', 'MojoDict *', 'MojoList *', 'MojoSet *')
                           or vt.endswith(' *')):
                    dict_val.setdefault(v, vt)
            elif isinstance(n, gimple_ctypes.ExprStmt) and isinstance(n.value, gimple_ctypes.CallExpr):
                c = n.value
                if (isinstance(c.func, gimple_ctypes.MemberExpr) and c.func.member == 'append'
                        and isinstance(c.func.obj, gimple_ctypes.IdentExpr) and c.args):
                    v, a = c.func.obj.name, c.args[0]
                    if isinstance(a, gimple_ctypes.ListExpr):
                        elem[v] = 'MojoList *'
                        nested[v] = gen._infer_list_elem_type(a.elements)
                    elif isinstance(a, gimple_ctypes.IdentExpr) and elem.get(a.name) == 'MojoList *':
                        elem[v] = 'MojoList *'
                        if a.name in nested:
                            nested[v] = nested[a.name]
            # recurse into compound statements (explicit branches so the
            # self-hosted backend, which can't lower getattr(n, <loop var>)
            # + isinstance(sub, list), still descends into control flow)
            if isinstance(n, gimple_ctypes.IfStmt):
                walk(n.then_body)
                if isinstance(n.else_body, list):
                    walk(n.else_body)
                for _cond, _eb in (n.elifs or []):
                    walk(_eb)
            elif isinstance(n, gimple_ctypes.TryStmt):
                walk(n.body)
                for _h in (n.handlers or []):
                    _hb = getattr(_h, 'body', None)
                    if isinstance(_hb, list):
                        walk(_hb)
                if isinstance(n.else_body, list):
                    walk(n.else_body)
                if isinstance(n.finally_body, list):
                    walk(n.finally_body)
            elif isinstance(n, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt,
                                gimple_ctypes.WithStmt, gimple_ctypes.FunctionDef)):
                _b = getattr(n, 'body', None)
                if isinstance(_b, list):
                    walk(_b)
                _eb2 = getattr(n, 'else_body', None)
                if isinstance(_eb2, list):
                    walk(_eb2)

    walk(body)
    return elem, nested, dict_val

def _is_known_field(gen, member: str) -> bool:
    """True if `member` is a field of at least one struct in
    struct_field_types — i.e. a boxed handle carrying it is (very likely)
    a real struct instance whose `.member` is a genuine field, not an
    identity/type-value access. Used by _lower_MemberExpr to decide
    whether a boxed scalar receiver should go through the runtime
    tag-dispatch field read (A5 part 2) instead of the `.value`/opaque
    identity shortcuts."""
    for _fm in gen.struct_field_types.values():
        if member in _fm:
            return True
    return False

def _known_field_type(gen, member: str) -> str | None:
    """The static C type of `member` when it is a field of structs in
    struct_field_types and ALL of them agree on that type; None if the
    member is unknown or its type varies across structs (e.g. `value`:
    int64_t in ReturnStmt/ExprStmt but char* in Token, double in
    FloatLiteral, _Bool in BoolLiteral). A boxed handle's field read can
    only be returned with a single static C type, so only fields with an
    unambiguous type are typed here; the rest keep the int64_t default."""
    # Iterate keys + index (with an ANNOTATED `_fm: dict` local), NOT
    # `for _fm in ...values()`: the self-hosted compiler could not infer
    # the value-element type of `struct_field_types` (a dict-of-dicts), so
    # `_fm` was typed int64_t, `member in _fm` lowered to a `/* TODO: 'in'
    # for int64_t */ = 0` no-op, and this function ALWAYS returned None in
    # compiled mojoc — every boxed AST `.name`/`.member`/`.value` read
    # stayed int64_t. A list (not a set + `.pop()`, also unlowered) keeps
    # the compiled control flow simple.
    # `_as_str` on both the struct-name key and the field-type value: on
    # the self-hosted path `struct_field_types` (a dict-of-dicts) erases
    # its inner value type to int64_t, so `_v` came back a boxed pointer
    # and the `f'({_boxed_ft}){raw}'` cast at the call site emitted a raw
    # ASLR pointer decimal as the cast type (`_t16 = (47634928176)_t15;`)
    # — a stage2-vs-stage3 idempotency failure. Dedup by string VALUE
    # (`in` over a list of real `char *` does strcmp) so a genuinely
    # type-varying member still returns None regardless of key order.
    _types: list = []
    for _sn0 in gen.struct_field_types:
        _fm: dict = gen.struct_field_types[_as_str(_sn0)]
        if member in _fm:
            _v = _as_str(_fm[member])
            if _v not in _types:
                _types.append(_v)
    if len(_types) == 1:
        return _as_str(_types[0])
    return None

def _resolve_member_expr_type(gen, node) -> str | None:
    """Resolve the actual C type of a nested member expression like self.parent.
    Returns the C type (e.g. 'Scope*') or None if it can't be resolved."""
    if isinstance(node, gimple_ctypes.IdentExpr):
        # Base case: resolve identifier to its type
        if node.name in gen.var_types:
            return gen.var_types[node.name]
        # Check struct field types (class names)
        if node.name in gen.struct_field_types:
            return node.name + '*'
        return None
    elif isinstance(node, gimple_ctypes.MemberExpr):
        # Recursive case: resolve obj.member
        obj_type = gen._resolve_member_expr_type(node.obj)
        if obj_type:
            # Strip pointer if present
            base_type: str
            base_type = gimple_exprtypes._struct_name_of(obj_type)
            if base_type in gen.struct_field_types:
                field_map = gen.struct_field_types[base_type]
                if node.member in field_map:
                    return field_map[node.member]
        return None
    return None

def _function_has_reachable_fallthrough(fn) -> bool:
    """True if `fn`'s body can fall off its own end (not every path ends
    in an explicit return/raise/break/continue) — reuses
    ownership_check.py's own `_terminates` logic so "does this function
    have a genuine fallthrough exit" is answered identically to how that
    module already decides it for its OWN diagnostics, rather than a
    second, possibly-diverging notion of the same question."""
    return not _block_terminates(fn.body)

def _is_free_eligible_function(fn) -> bool:
    """True if `fn` (a fire_compiler.FunctionDef) contains no nested `def`/
    `async def` and no `lambda` ANYWHERE in its body — see the section
    banner above for why each disqualifies. A `try`/`except` in `fn`'s own
    body no longer disqualifies it (doc/OWNERSHIP_MODEL.md's TODO item 3,
    landed 2026-09-15): the cleanup-thunk registry (`maybe_push_owned_
    local`/`mojo_cleanup_checkpoint_save`/`mojo_raise`'s unwind, see
    runtime/fire_runtime.c) now makes a candidate's constructing
    assignment and its return/fallthrough free safe to straddle a `try`
    in the SAME function, exactly the same way it already made them safe
    to straddle a callee's own exception. A nested `def`/`lambda` still
    disqualifies because a closure's capture could extend a binding's
    real lifetime past this function's own return — an unrelated,
    still-open problem (the async/coroutine cross-cutting section).

    Also excludes `fn` itself being `async`/a generator (`fn.is_async` /
    `fn.is_generator`) — NOT just nested ones. A coroutine/generator body's
    `return e` is rewritten by gimple_gen_coro.py into `__mojo_coro_set_
    return(...)` + falling off, a genuinely different lowering than the
    plain `return` this wiring was written and validated against (see
    doc/OWNERSHIP_MODEL.md's async/coroutine cross-cutting section) — this
    was a real gap found DURING that section's own investigation (the
    original check only ever walked for a NESTED FunctionDef, never
    checked whether `fn` itself carried these flags), fixed before it
    could matter rather than after."""
    if getattr(fn, 'is_async', False) or getattr(fn, 'is_generator', False):
        return False
    for n in gimple_exprtypes._walk_ast(fn.body):
        if isinstance(n, (FunctionDef, LambdaExpr)):
            return False  # any nested FunctionDef disqualifies regardless
                           # of its own is_async/is_generator flags
    return True

def _compute_owned_free_candidates(fn) -> set:
    """Returns the set of local names in `fn` safe to `mojo_*_free` at
    every return/fallthrough point, or an empty set if `fn` isn't eligible
    at all (see `_is_free_eligible_function`) or the analysis found none.
    `{}, {}` for ownership_destruct's callee-resolution tables: this
    codegen layer has no ready-made whole-module function/method lookup
    to hand it yet, so calls-to-`read`-parameters don't get the analysis'
    full precision here (a real widening for later) — passing empty
    tables only ever makes this MORE conservative (fewer candidates
    found), never unsound, since an unresolved call is already the
    analysis' safe default."""
    if not _is_free_eligible_function(fn):
        return set()
    try:
        return ownership_destruct.analyze_function(fn, {}, {})
    except Exception:
        # This is an OPTIONAL memory-usage improvement, not a correctness
        # requirement of compiling the program at all — a bug in the
        # (still-new) analysis must never fail a build. Silently skip
        # freeing anything for this function instead (today's pre-existing
        # leak, unchanged) rather than raise through gen_func.
        return set()

def _empty_ctor_ctype(node) -> str | None:
    """`node` (an AssignStmt/VarDecl's `.value`) is an EMPTY container
    constructor -> its ctype ('MojoDict *'/'MojoList *'/'MojoSet *'), else
    None. Covers the same four shapes `ownership_destruct._is_constructor_
    expr` recognizes, narrowed to the empty case (see banner above)."""
    if isinstance(node, DictExpr):
        return 'MojoDict *' if not node.pairs else None
    if isinstance(node, ListExpr):
        return 'MojoList *' if not node.elements else None
    if isinstance(node, SetExpr):
        return 'MojoSet *' if not node.elements else None
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and not node.args and len(node.kwargs or []) == 0):
        return {'dict': 'MojoDict *', 'list': 'MojoList *', 'set': 'MojoSet *'}.get(node.func.name)
    return None


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_infra.py)
# ---------------------------------------------------------------------------

# --- dependency _FC_SEP (from gimple_gen_infra.py) ---
_FC_SEP = '\x1f'

# --- dependency _POINTER_CTOR_NAMES (from gimple_gen_infra.py) ---
_POINTER_CTOR_NAMES = frozenset({'UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'})


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_infra.py)
# ---------------------------------------------------------------------------

# --- dependency _FC_SEP (from gimple_gen_infra.py) ---
_FC_SEP = '\x1f'

# --- dependency _POINTER_CTOR_NAMES (from gimple_gen_infra.py) ---
_POINTER_CTOR_NAMES = frozenset({'UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'})

