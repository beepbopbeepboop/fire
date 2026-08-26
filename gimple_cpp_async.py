"""C++20 coroutine generator/async unit generation.

Function-extraction architecture: former GimpleGen methods as
module-level functions taking `gen` first; delegates remain on
the class; cross-module references are qualified.
"""
from __future__ import annotations

import os
import re

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
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
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc
import gimple_gen_exprs as gex
import gimple_cpp_core as gcc_

def _cpp_declared_type(gen, node) -> str | None:
    """C++ type of a node for `in`/`not in` dispatch, when it is a plain
    local/param the coroutine-body `declared` map tracks (set on
    self._cpp_declared by _cpp_stmt before emitting body statements).
    Returns None for anything the body model can't statically type."""
    if isinstance(node, gimple_ctypes.IdentExpr):
        if gen._cpp_declared is not None:
            return gen._cpp_declared.get(node.name)
    # A subscript of a known-typed container keeps the element type
    # (e.g. a str/bytes element indexed off a char* stays char *).
    if isinstance(node, gimple_ctypes.SubscriptExpr) and isinstance(node.obj, gimple_ctypes.IdentExpr):
        bt = gen._cpp_declared_type(node.obj)
        if bt == 'char *':
            return 'char'
    return None


def _cpp_known_ptr_struct(gen, g_mtype: str) -> bool:
    """True iff `g_mtype` like `_DeprecatedGenericAlias *` references a real
    opaque struct this translation unit declares — i.e. a runtime opaque
    type in _CPP_OPAQUE_PTR_STRUCTS, or a user-defined mojo `struct` whose
    typedef this compiler emitted (tracked in self.struct_field_types). A
    `X *` whose basename is neither is an opaque Python CLASS used only as
    a type annotation (typing._DeprecatedGenericAlias, etc.); emitting `X
    field;` in the globals struct would be an undeclared-type compile error,
    so callers force such fields to `void *` instead. Used during the
    globals-struct assembly in gen_module."""
    base = g_mtype
    if base.endswith(' *'):
        base = base[:-2]
    base = base.strip().lstrip('*').strip()
    if base in gimple_ctypes._CPP_OPAQUE_PTR_STRUCTS:
        return True
    return base in gen.struct_field_types


def _cpp_struct_ptr_local(gen, name: str) -> str | None:
    """If `name` is a declared local/param in the coroutine body
    currently being emitted whose C++ type is a known struct pointer
    (e.g. 'ArgResolver *'), return the bare struct name; else None.
    Used to pick `->` vs `.` for a non-self member access/method call,
    and to find the struct a method call on `name` belongs to — see
    bugs/hard/CODEGEN_generator_struct_typed_param_refused.md."""
    if gen._cpp_declared is None:
        return None
    ct = gen._cpp_declared.get(name)
    if ct and ct.endswith(' *'):
        sn = ct[:-2]
        if sn in gen.struct_field_types:
            return sn
    return None


def _cpp_is_callable_value_expr(gen, node) -> bool:
    """True for a coroutine-body expression this codegen's one
    callable-value declared-type category (`_CPP_CALLABLE_CTYPE`) can
    represent: a zero-argument `lambda` literal, or a bound-method-as-
    VALUE read (`self.<method>` / `<struct-pointer local>.<method>`,
    NOT immediately called) off a struct whose methods this compile
    already knows how to dispatch through. Used by `_cpp_stmt`'s
    AssignStmt case to give a first-assigned local the right declared
    type — mirrors (and must stay in sync with) `_cpp_expr`'s own
    LambdaExpr/MemberExpr cases, the single source of truth for the
    actual VALUE emission this type just needs to agree with. See
    bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md."""
    if isinstance(node, gimple_ctypes.LambdaExpr):
        return not node.params
    if isinstance(node, gimple_ctypes.MemberExpr):
        # `_struct_method_names` (real method names straight off the
        # struct's own AST) is the sole authoritative signal — NOT
        # "absent from struct_field_types" (see `_cpp_expr`'s matching
        # `self.<method>` case for why that alone isn't proof: this
        # file's dynamic-attribute pre-pass synthesizes phantom field
        # entries for unrecognized member reads too, including a real
        # method read as a value like this one). A struct field can't
        # legitimately share a name with one of its own methods, so
        # this check alone — with no field-absence requirement — is
        # both necessary and sufficient, matching `_cpp_expr`'s own
        # method-name-checked-first ordering.
        # A @property getter is EXCLUDED here (mirroring `_cpp_expr`'s
        # own property carve-out): real Python auto-invokes a property
        # on every bare read, so `x = self.<prop>` binds the getter's
        # RESULT, not a callable — the local must get that value's
        # ordinary inferred ctype, not `_CPP_CALLABLE_CTYPE`.
        struct_name = getattr(gen, '_cpp_gen_self_struct', None)
        if struct_name and isinstance(node.obj, gimple_ctypes.IdentExpr) and node.obj.name == 'self':
            return (node.member in gen._struct_method_names.get(struct_name, ())
                    and node.member not in gen._struct_property_names.get(struct_name, ()))
        if isinstance(node.obj, gimple_ctypes.IdentExpr):
            ptr_struct = gen._cpp_struct_ptr_local(node.obj.name)
            if ptr_struct:
                return (node.member in gen._struct_method_names.get(ptr_struct, ())
                        and node.member not in gen._struct_property_names.get(ptr_struct, ()))
    return False


def _cpp_dict_key_expr(gen, idx_node, idx_cpp: str) -> str:
    """Coerce a coroutine-body subscript INDEX expression to a real
    MojoDict* key (always char *), for the SubscriptExpr read/write
    branches of _cpp_expr/_cpp_stmt. Mirrors the plain (non-generator)
    GIMPLE path's own _char_to_cstr convention -- a string index is
    used directly, an int index is stringified via mojo_str_from_int
    (a real Int dict key, e.g. `Dict[Int, V]`'s `d[k]`) -- but is a
    fresh, self-contained implementation rather than calling
    _char_to_cstr itself: that method is stateful (emits GIMPLE lines
    via self._new_val/self._emit into the PLAIN path's own emission
    buffer/temp-numbering), incompatible with this coroutine emitter's
    separate text-line-list-based .cpp translation (_cpp_expr/_cpp_stmt
    return plain strings, no shared emission state) -- reusing it here
    would silently interleave two different emitters' internal state.
    `mojo_str_from_int` itself is a pure runtime call, safe to use
    inline in a C++ expression position unlike _char_to_cstr's
    SSA-temp-based emission style.
    """
    self_fields = getattr(gen, '_cpp_gen_self_fields', None)
    ictype = gimple_exprtypes._infer_simple_expr_ctype(
        idx_node, gen._cpp_declared, self_fields, gen._async_api)
    if ictype == 'char *':
        # An explicit (char *) cast: a range-for over a string-literal
        # tuple (`for k in ("a", "b"):`) binds its target to
        # `const char *` (C++ braced-init-list element type), and the
        # runtime dict helpers take plain `char *` keys.
        return f"(char *)({idx_cpp})"
    return f"mojo_str_from_int((int64_t)({idx_cpp}))"

def _cpp_fresh_name(gen, prefix: str = "_mg_t") -> str:
    """Generate a unique C++ variable name for the generator body."""
    gen._cpp_fresh_name_counter += 1
    return f"{prefix}_{gen._cpp_fresh_name_counter}"


def _cpp_stmt_with_break_flag(gen, s, declared: dict, indent: str,
                               brk_var: str) -> list[str]:
    """Like _cpp_stmt but intercepts BreakStmt to set brk_var = true before
    breaking, so while/else can detect whether the loop exited via break."""
    if isinstance(s, gimple_ctypes.BreakStmt):
        return [f"{indent}{brk_var} = true;", f"{indent}break;"]
    return gen._cpp_stmt(s, declared, indent)


def _cpp_with_guard_type_name(gen, expr) -> str | None:
    """The recognized-no-op-guard type name `with EXPR(...):`'s `EXPR`
    resolves to, or None if `expr` isn't a call to a plain name (`Type
    (...)`) or a bracket-parametrized name (`Type[args](...)`,
    `Trace[level](...)`'s own shape) at all."""
    if not isinstance(expr, gimple_ctypes.CallExpr):
        return None
    if isinstance(expr.func, gimple_ctypes.IdentExpr):
        return expr.func.name
    if (isinstance(expr.func, gimple_ctypes.SubscriptExpr)
            and isinstance(expr.func.obj, gimple_ctypes.IdentExpr)):
        return expr.func.obj.name
    return None


def _cpp_iterable_is_delegatable_generator_call(gen, iterable) -> bool:
    """True when `iterable` is a call this compile can potentially
    delegate to via `_cpp_for_generator_delegate` — either a bare
    `name(...)` naming a free-function generator, or `self.method(...)`
    naming a generator METHOD on the SAME struct this body belongs to
    (`self._cpp_gen_self_struct`, set by `_gen_cpp_generator_unit`
    while compiling a generator method's body — None for a free
    function, so the method-call branch below naturally never matches
    there). Uses `self._all_generator_names` (every generator name
    anywhere in the module, computed once up front — see that
    attribute's own docstring) rather than `self._generator_api`/
    `self._generator_method_api` directly, so a callee that's a real
    generator but hasn't been COMPILED yet in this pass still counts as
    "delegatable" here — `_cpp_for_generator_delegate` itself raises
    `_UnsupportedGeneratorShape` for that case, which is exactly what
    gets the caller retried in gen_module's later passes instead of
    silently falling through to the generic (non-generator-aware)
    iterable lowering."""
    if not isinstance(iterable, gimple_ctypes.CallExpr):
        return False
    if isinstance(iterable.func, gimple_ctypes.IdentExpr):
        return iterable.func.name in gen._all_generator_names
    if isinstance(iterable.func, gimple_ctypes.MemberExpr):
        _self_struct = getattr(gen, '_cpp_gen_self_struct', None)
        return bool(_self_struct
                    and isinstance(iterable.func.obj, gimple_ctypes.IdentExpr)
                    and iterable.func.obj.name == 'self'
                    and iterable.func.member in gen._all_generator_names)
    return False


def _cpp_match_stmt(gen, s, declared: dict, indent: str) -> list[str]:
    """`match subject: case p: ... case _: ...` inside a generator body.
    Lowers to a chain of if/else comparisons (switch-style equality),
    mirroring _gen_stmt_MatchStmt's dispatch: each case's patterns are
    OR-ed equality checks against the subject; an empty-pattern or `_`
    case is a wildcard else-branch. A class-pattern `case str(x):`
    (parsed as CallExpr) is approximated as a truthy-subject check with
    `x` bound to the subject — good enough for dataclasses._get_slots's
    `case None:` / `case str(slot):` idiom."""
    subj = gen._cpp_expr(s.subject)
    lines = []
    for i, match_case in enumerate(s.cases):
        is_wildcard = not match_case.patterns or any(
            isinstance(p, gimple_ctypes.IdentExpr) and p.name == '_' for p in match_case.patterns)
        if is_wildcard:
            lines.append(f"{indent}else {{")
        else:
            conds = []
            for p in match_case.patterns:
                if isinstance(p, gimple_ctypes.IdentExpr) and p.name == 'None':
                    conds.append(f"({subj} == 0)")
                elif isinstance(p, gimple_ctypes.CallExpr) and isinstance(p.func, gimple_ctypes.IdentExpr):
                    # class pattern `case str(x)`: bind the capture, match if truthy
                    if p.args and isinstance(p.args[0], gimple_ctypes.IdentExpr):
                        declared[p.args[0].name] = 'int64_t'
                        lines.append(f"{indent}{p.args[0].name} = {subj};")
                    conds.append(f"({subj} != 0)")
                else:
                    conds.append(f"({subj} == {gen._cpp_expr(p)})")
            cond = ' || '.join(conds)
            lines.append(f"{indent}if ({cond}) {{")
        for st in match_case.body:
            lines.extend(gen._cpp_stmt(st, declared, indent + '    '))
        lines.append(f"{indent}}}")
    return lines


def _cpp_except_handler_body(gen, handler, caught_var: str, declared: dict,
                              indent: str) -> list[str]:
    """Emit one `except ...:` handler's binding + body as C++ lines,
    nested inside the dispatch `if`/`else if` this handler's caller
    (_cpp_try_stmt) already built OUTSIDE the actual `catch` clause (see
    that method's docstring for why). `caught_var` names the local
    `_MojoCppExc` variable — a plain copy taken inside the catch clause
    — holding the exception this handler is running for; `except X as
    e:` binds `e` by reading straight out of it. `declared` is shared
    (not copied) with the enclosing generator body, matching this
    emitter's existing if/while convention (see _cpp_stmt's IfStmt/
    WhileStmt cases) — a name first assigned inside this handler is
    registered globally for the rest of the translation, for better or
    worse consistently with every other nested block here, not a new
    scoping rule invented just for except-handlers."""
    lines = []
    if handler.name:
        # Mirrors _emit_except_handler's own binding convention for the
        # ordinary GIMPLE path: the object slot is a bare message string
        # for every exception this narrow model can raise (see
        # _cpp_raise_stmt), so bind as char * — there is no struct-typed
        # exception payload in this scalar-only generator-body model.
        declared[handler.name] = 'char *'
        lines.append(f"{indent}char *{handler.name} = {caught_var}.msg;")
    gen._cpp_reraise_stack.append(caught_var)
    try:
        for st in handler.body:
            lines.extend(gen._cpp_stmt(st, declared, indent))
    finally:
        gen._cpp_reraise_stack.pop()
    return lines


def _gen_cpp_generator_unit(gen, fn: gimple_ctypes.FunctionDef,
                             struct_name: str | None = None) -> tuple[str, str, str, list]:
    """Translate ONE supported generator FunctionDef into a
    self-contained C++20 coroutine fragment. Returns (cpp_text,
    value_ctype, base_name, param_ctypes). Raises
    _UnsupportedGeneratorShape for anything gen_module's pre-pass didn't
    already rule out via _generator_quick_eligible — this method (not a
    second hand-written checklist) is the actual authority on "is this
    shape compilable", so gen_module's pre-pass calls it directly and
    catches that one exception type to decide supported-vs-refused.

    `struct_name`, when given, means `fn` is a generator METHOD (not a
    free function) on that struct: `fn.params[0]` must be `self`, typed
    as `{struct_name} *` in the emitted C++ — the SAME pointer type an
    ordinary (non-generator) compiled method's `self` already uses (see
    _gen_struct_method's `self.var_types['self'] = f"{struct_name} *"`),
    not a new convention. The struct's C layout (typedef) is already
    emitted once, verbatim, into the main .c/.ci output by gen_module's
    existing struct-typedef emission (from self.struct_field_types) —
    rather than inventing a second representation for the .cpp side,
    gen_module's preamble for self.generated_cpp textually re-emits that
    SAME typedef (see the `_generator_cpp_units`-consuming code near the
    end of gen_module) so both the gcc-compiled .c/.ci and the g++-
    compiled .cpp see byte-identical field layout/order — a plain C
    struct with only scalar/pointer fields is valid, ABI-identical C and
    C++, so no `extern "C"` wrapping or separate mirror definition is
    needed, just the one shared piece of text. Field access is limited
    to `self.<field>` reads of a SCALAR (int64_t/double/_Bool) field —
    see _cpp_expr's MemberExpr case and _infer_simple_expr_ctype's
    self_fields parameter — method calls on self, nested attribute
    chains, and mutating a self field are all out of this step's scope
    and refuse naturally (see _cpp_expr/_cpp_stmt's existing refusal
    paths, unchanged): a call on self.method() is a CallExpr, which
    _cpp_expr has no case for; an assignment to self.field has a
    MemberExpr (not IdentExpr) target, which _cpp_stmt's AssignStmt case
    already refuses.

    Calling convention (opaque handle + 4 extern "C" functions): a
    std::coroutine_handle<Promise> IS already just a wrapped pointer to
    the compiler-allocated coroutine frame (.address()/from_address()
    round-trip it losslessly), so the opaque `MojoGenerator *` the C side
    sees is literally that address reinterpret_cast through an
    incomplete `struct MojoGenerator` — no separate heap-allocated
    wrapper object is needed.
      <base>_start(params...)     -> MojoGenerator*  (constructs, does
                                      NOT run any body code yet --
                                      initial_suspend() is suspend_always.
                                      Parameters (as of the parameter-
                                      support step) are ordinary by-value
                                      C++ function parameters on the
                                      `impl` coroutine function --
                                      std::coroutine_handle's frame
                                      allocation copies them into the
                                      frame itself, the same as any other
                                      C++20 coroutine, so no manual
                                      threading into the promise is
                                      needed: they're simply in scope for
                                      the whole coroutine body, exactly
                                      like a local variable.)
      <base>_resume(MojoGenerator*) -> _Bool  (advances to the next
                                      co_yield or co_return; mirrors this
                                      codegen's existing __has_next__
                                      convention for user __iter__
                                      structs — see _gen_for_struct_iter
                                      — reused rather than inventing a
                                      new "returns 2 things" scheme)
      <base>_value(MojoGenerator*)  -> value_ctype  (the value most
                                      recently produced by _resume;
                                      mirrors __next__'s role in that
                                      same existing convention)
      <base>_destroy(MojoGenerator*) -> void  (coroutine_handle::destroy())
    """
    # Reset the tuple-yield side channel up front (see its own
    # docstring at __init__) so an early exception/refusal in THIS
    # compile attempt can never leave a PRIOR generator's leftover
    # slot-types list around for some later, unrelated read to pick up.
    gen._cpp_last_tuple_slot_ctypes = None
    # Same reset convention for the value-carrying-return side channel
    # (see the eligibility computation below).
    gen._cpp_last_has_return_value = False
    # Parameters: only plain scalar (int64_t/double/_Bool) positional
    # params are supported this step. *args/**kwargs and any param whose
    # resolved C type isn't one of those three are refused — string/
    # struct/pointer parameters cross the C++/C boundary with lifetime
    # and ownership questions this narrow step deliberately defers (see
    # the parameter-support step's writeup: "small natural extension of
    # what's already being built" vs. "opens new complexity"). Computed
    # BEFORE value_ctype below so `yield <param>` can resolve the
    # param's real type via _generator_yield_ctype's `known` map instead
    # of always guessing int64_t (see _infer_simple_expr_ctype's
    # docstring) — a double/_Bool param that's yielded (directly, or via
    # a local assigned straight from it, e.g. `v = start`) needs this to
    # actually round-trip correctly, not just type-check.
    param_ctypes: list[tuple[str, str]] = []
    fn_params = list(fn.params or [])
    if struct_name is not None:
        if not fn_params or fn_params[0][0] not in ('self', 'cls'):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"{fn.name}: a generator method must take `self` or "
                "`cls` as its first parameter")
        if fn_params[0][0] == 'cls':
            # @classmethod generator (conventionally-named `cls` first
            # param, same name-convention basis the ordinary compiled
            # path already uses for `cls.method(...)` resolution — see
            # this file's CallExpr lowering, "`cls.method(...)` inside a
            # @classmethod"). Unlike `self`, `cls` names the CLASS
            # object, not an instance — there is no real object behind
            # it in this codegen (see `param_ctypes.append(('cls', ...))`
            # below), so a classmethod generator body that touches `cls`
            # must be checked shape-by-shape: `_cls_refs_supported`
            # allows the two shapes `_cpp_expr`'s MemberExpr/CallExpr
            # `cls.<...>` handling actually supports (a class-level-
            # attribute read via the `self._class_attrs` global
            # redirect; a call to a real compiled classmethod/static
            # method of the enclosing struct) and refuses anything else
            # — a bare `cls` used as a plain value, or a `cls.<attr>`/
            # `cls.<method>(...)` shape neither of those cover — exactly
            # as conservatively as the original blanket "any cls
            # reference -> refuse" check did for every unsupported
            # shape, so nothing can reach _cpp_expr's MemberExpr
            # "non-self member access" fallback (invalid C++ on a
            # scalar) or silently read the placeholder as a real value.
            # See bugs/CODEGEN_generator_function_Lib_enum.md's
            # 2026-08-21 update for the motivating Lib/enum.py
            # `Flag._iter_member_by_value_` shape (previously refused
            # unconditionally here — see the
            # CODEGEN_generator_classmethod_first_param_must_be_self.md
            # hard-bug doc for that original, narrower carve-out).
            if not gen._cls_refs_supported(fn.body, struct_name):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    f"{fn.name}: a @classmethod generator that "
                    "references `cls` in its body in an unsupported "
                    "way is not supported (only a class-level-"
                    "attribute read, or a call to a real compiled "
                    "classmethod/static method of the enclosing "
                    "class, are supported for `cls.<...>` access in a "
                    "compiled generator)")
            # `cls` itself is only ever an opaque, never-dereferenced
            # int64_t placeholder -- every supported access above is
            # resolved purely by NAME (via `struct_name`), never by
            # reading `cls`'s own runtime value -- so this placeholder
            # keeps the emitted C++ signature's parameter COUNT/
            # POSITION correct (call sites already pass the receiver
            # positionally — see the method-call CallExpr lowering's
            # `all_args = [(ot, ov)] + arg_pairs`, which doesn't care
            # what this parameter's name or real value is) without
            # inventing any new class-object representation.
            param_ctypes.append(('cls', 'int64_t'))
        else:
            # Mirrors _gen_struct_method's own convention exactly (see that
            # method's `self.var_types['self'] = f"{struct_name} *"`) — the
            # SAME pointer type an ordinary compiled method's `self` already
            # uses, not a new one.
            param_ctypes.append(('self', f"{struct_name} *"))
        fn_params = fn_params[1:]
    for pn, pt in fn_params:
        if pn.startswith('**'):
            # **kwargs: represent as a MojoDict* of keyword args
            param_ctypes.append((pn[2:], 'MojoDict *'))
            continue
        if pn.startswith('*'):
            # *args: represent as a MojoList* of positional args
            param_ctypes.append((pn[1:], 'MojoList *'))
            continue
        ctype = gen._param_ctype(pn, pt, fn)
        # A struct pointer is an ordinary trivially-copyable C type —
        # the compiler-generated coroutine frame copies it into itself
        # by value exactly like any scalar/container parameter, zero
        # additional plumbing needed for ACCEPTANCE. What used to be
        # missing was BODY-side support for calling a method on such a
        # parameter (`->` vs `.`, and the mangled-symbol-call
        # machinery) — now handled by _cpp_struct_ptr_local/
        # _cpp_struct_method_refs. See bugs/hard/CODEGEN_generator_
        # struct_typed_param_refused.md.
        _is_struct_ptr = (ctype.endswith(' *')
                          and ctype[:-2] in gen.struct_field_types)
        if _is_struct_ptr:
            gen._cpp_param_struct_names.add(ctype[:-2])
        if ctype not in ('int64_t', 'double', '_Bool', 'char *', 'MojoList *',
                         'MojoDict *', 'MojoSet *') and not _is_struct_ptr:
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"{fn.name}: generator parameter '{pn}' has unsupported "
                f"type {ctype!r} (only int64_t/double/_Bool/char*/"
                "MojoList*/MojoDict*/MojoSet*/<known struct>* parameters "
                "are supported for compiled generators)")
        param_ctypes.append((pn, ctype))
    if struct_name is not None:
        base = f"_mojogen_{gimple_ctypes._safe_name(struct_name)}_{gimple_ctypes._safe_name(fn.name)}"
    else:
        # Module-qualify a free-function generator's C symbol exactly
        # like an ordinary free function's (`_func_csym`/SB-1's
        # `bf96f55`/`13e6a5c`) — before this, TWO UNRELATED generator
        # functions in different modules sharing a bare name (`walk`
        # is common: os.py's own 4-param `walk` vs. an unrelated
        # 1-param `walk` reachable via threading.py) both mangled to
        # the identical bare `_mojogen_walk_start`, producing a hard
        # "conflicting types" GCC error across the whole-program
        # compile the moment both were transitively reachable (real:
        # `python3 mojo.py build .../Lib/os.py`) — see
        # CODEGEN_generator_function_symbol_not_module_qualified.md.
        # `_func_qualifier` is called here EXACTLY as `_func_csym` calls
        # it for an ordinary function's definition: `fn.name` is always
        # one of THIS gen_module() call's own top-level FunctionDefs at
        # this call site (both callers below iterate `stmts`/
        # `_generator_fns`, itself built from `_walk_ast(stmts)` scoped
        # to the currently-compiling module), so tier 1
        # (`_local_top_level_func_names`, this module's OWN top-level
        # names) always fires here — the same purely-per-instance,
        # never-shared-dict-dependent info `_func_qualifier`'s
        # docstring documents as "always authoritative for itself, full
        # stop". Every reader of the registered `base` (self.
        # _generator_api[name]['base']) does a single dict read reused
        # for both the extern "C" forward-declaration/param-types
        # registration and the actual call, so whatever this returns is
        # automatically self-consistent at every call site — no
        # separate cross-module CALL-resolution fix is needed to close
        # THIS bug (unlike SB-1's ordinary-function fix, which also had
        # to fix call-site resolution): the confirmed real-world
        # collision is between two functions that never call each
        # other, purely a shared-symbol-name definition clash. A
        # from-scratch `self._generator_api` cross-module CALL
        # collision (module A calling module B's same-bare-name
        # generator while a DIFFERENT module C's own same-name
        # generator is also in scope) remains the same class of
        # documented, accepted "first-registered-module-wins" residual
        # limitation `_imported_func_home`'s own docstring already
        # carries for ordinary functions (tier 3) -- not fixed here,
        # not exercised by any confirmed repro, and not attempted per
        # this bug's own documented preference for a narrowly-verified
        # fix over a speculative, higher-risk rework of the
        # shared-dict call-resolution machinery.
        _gen_qualifier = gen._func_qualifier(fn.name)
        base = (f"_mojogen_{_gen_qualifier}_{gimple_ctypes._safe_name(fn.name)}"
                if _gen_qualifier else f"_mojogen_{gimple_ctypes._safe_name(fn.name)}")
        # Several DISTINCT nested `def`s can share one bare name inside
        # different enclosing functions (test_sys_setprofile.py defines
        # `def f(): yield i` in three separate test methods) — every one
        # compiled to the SAME `_mojogen_f_*` symbol set, a hard
        # "redefinition of 'struct _mojogen_f_Task'" C++ error. Append a
        # deterministic ordinal (compilation order is source order, which
        # is stable for identical input, preserving CAS-cache identity)
        # to the second and later same-named units. Call-site resolution
        # remains name-keyed (`_generator_api[name]`, last registration
        # wins) — the same accepted "first/last-writer-wins" residual
        # limitation the ordinary-function home machinery already
        # documents for cross-module same-bare-name functions.
        _seen_bases = getattr(gen, '_seen_generator_base_names', None)
        if _seen_bases is None:
            _seen_bases = gen._seen_generator_base_names = {}
        _occurrence = _seen_bases.get(base, 0) + 1
        _seen_bases[base] = _occurrence
        if _occurrence > 1:
            base = f"{base}_{_occurrence}"
    # Params are already "declared" locals as far as the body emitter is
    # concerned — a param can be read (`i = start`) or directly
    # reassigned/augmented (`start = start + 1`) without a fresh `Type
    # name = ...` declaration, exactly like any other C++ function
    # parameter used as a mutable local. Body emission runs BEFORE
    # value_ctype is computed below (reordered from this method's
    # original param-less shape) precisely so `declared` ends up holding
    # every local's REAL inferred type (not just the params') by the
    # time _generator_yield_ctype looks a `yield <name>`'s name up in
    # it — e.g. `v = start` (start: Float64 param) correctly types `v`
    # as double via the AssignStmt case just below, and a later `yield
    # v` then resolves to double too, instead of the int64_t default.
    # `self` is deliberately EXCLUDED from `declared`/`known` — it's a
    # struct pointer, not a scalar, so a bare (non-`.field`) reference to
    # it must refuse (see _cpp_expr's IdentExpr case), not silently fall
    # through to the int64_t default every other unknown name gets.
    # Reset + seed self._cpp_kw_param_renames for THIS unit's params
    # before the body is lowered below (_cpp_stmt/_cpp_expr consult
    # it while lowering `fn.body` a few lines down, so registration
    # must happen before that, not alongside cpp_sig's later
    # construction) — see that attribute's own docstring. Reset
    # first so a PRIOR generator/async unit's own renames (e.g. some
    # earlier function's unrelated keyword-named parameter) can
    # never leak into this one.
    gen._cpp_kw_param_renames = {}
    for _pn, _ in param_ctypes:
        if _pn in gimple_ctypes._C_KEYWORDS or _pn in gimple_ctypes._CPP_KEYWORD_FIELDS or _pn in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS:
            gen._cpp_kw_param_renames[_pn] = f"_kw_{_pn}"
    declared: dict[str, str] = {pn: ct for pn, ct in param_ctypes if pn != 'self'}
    self_fields = gen.struct_field_types.get(struct_name, {}) if struct_name else None
    # Instance-scoped context for _cpp_expr/_cpp_stmt (mirrors this
    # file's existing self._current_struct_name convention for ordinary
    # struct methods) — set for the duration of this one generator's
    # translation and always cleared afterward (even on refusal), so a
    # LATER free-function generator (struct_name=None) in the same
    # module never sees stale self-method context.
    gen._cpp_gen_self_struct = struct_name
    gen._cpp_gen_self_fields = self_fields
    gen._cpp_declared = declared
    # Self-recursion context for `yield from <this-same-function>(...)`
    # (_cpp_yield_from) and this function's own value-type inference
    # (_generator_yield_ctype/_yield_from_delegate_ctype, called just
    # below): a generator's registration into self._generator_api only
    # happens AFTER this whole method returns successfully (gen_module's
    # calling loop), so a genuinely self-recursive `yield from
    # <fn.name>(...)` inside fn's OWN body can never find itself there
    # — a chicken-and-egg gap that silently mis-lowered the call as
    # "yield from over a plain (non-generator) collection" instead
    # (WRONG on two counts at once: the kwarg-forwarding skip that
    # fallback shares with nothing, and defaulting the WHOLE function's
    # yield-value type to char* — see
    # CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md).
    # Set here (this function's own `base`/`param_ctypes` are already
    # fully computed above) and cleared in `finally`, mirroring
    # `_cpp_gen_self_struct`'s exact same scoped-context convention.
    gen._cpp_gen_self_name = fn.name
    gen._cpp_gen_self_base = base
    gen._cpp_gen_self_params = param_ctypes
    # Set True by _cpp_yield_from the moment it actually emits a
    # self-recursive delegation call — read back (into a local,
    # BEFORE `finally` below) to decide whether `{base}_start`/
    # `_resume`/`_value`/`_destroy` need FORWARD declarations ahead of
    # `{impl}`'s own definition: `impl`'s body (built in the try block
    # just below) can reference its own not-yet-defined extern "C"
    # wrapper functions, which are only emitted textually AFTER
    # `impl` further down in this same method's returned `lines` —
    # `_cpp_gen_self_recursed` is that signal.
    gen._cpp_gen_self_recursed = False
    func_decls: list[str] = []
    gen._cpp_func_scope_decls = []
    # Pre-body-emission tuple-slot arity pass: `_cpp_yield_tuple` runs
    # DURING the emission loop just below, but the unified per-slot list
    # it must pad every site out to can only be computed from a
    # whole-body walk — so run that walk here, BEFORE emission, on this
    # unit's own initial `declared` (params only at this point) and the
    # same `generator_api` view the post-emission companion call below
    # will see (neither changes during one unit's compile: registration
    # happens only after all units finish, so both passes observe an
    # identical set of yield/delegate sites — arity unification is purely
    # structural; only per-slot TYPES differ between the two passes, and
    # only the post-emission result is trusted for consumer-side
    # accessor selection). Stashed via _cpp_pending_tuple_slots for
    # `_cpp_yield_tuple` to consult; cleared in `finally` below.
    _pre_ok, _pre_slots = gimple_exprtypes._generator_tuple_yield_slot_ctypes(
        fn, declared, self_fields, gen._async_api,
        generator_api=gen._generator_api)
    gen._cpp_pending_tuple_slots = list(_pre_slots) if (_pre_ok and _pre_slots) else None
    # Value-carrying `return <expr>` support (real CPython 3.14
    # asyncio/futures.py's `Future.__await__`: `yield self` ... `return
    # self.result()`). Python delivers a generator's return value via
    # StopIteration(value); this codegen now materializes that channel
    # as a per-unit extern "C" global `{base}_return_slot` typed by the
    # return expression(s)'s own inference: an ELIGIBLE generator
    # stores its final value into the slot immediately before
    # co_return, so anything reading the slot after the generator
    # reports done gets exactly the Python return value. Deliberately
    # NOT a promise field/method: the C++20 rule makes return_void XOR
    # return_value mandatory (this promise needs return_void for every
    # ordinary generator), and this project's GCC 15 has a DOCUMENTED
    # coroutine-frame-layout bug with extra promise FIELDS (see the
    # unhandled_exception comment below) — a plain translation-unit
    # global touches neither. Eligibility is deliberately conservative
    # — ALL of:
    #   - at least one value-carrying `return`,
    #   - NO bare `return` anywhere in the body, and
    #   - the body's LAST top-level statement is a valued return (so
    #     no control path completes without storing).
    # Anything else keeps the honest refusal.
    _ret_stmts = [n for n in gimple_exprtypes._walk_own_body(fn.body)
                  if isinstance(n, gimple_ctypes.ReturnStmt)]
    _valued_rets = [n for n in _ret_stmts if n.value is not None]
    _bare_rets = [n for n in _ret_stmts if n.value is None]
    _ends_with_valued_ret = (bool(fn.body)
                             and isinstance(fn.body[-1], gimple_ctypes.ReturnStmt)
                             and fn.body[-1].value is not None)
    _has_return_value = bool(_valued_rets) and not _bare_rets and _ends_with_valued_ret
    gen._cpp_pending_return_store = None
    if _has_return_value:
        _ret_ct = None
        for _r in _valued_rets:
            _t = gimple_exprtypes._infer_simple_expr_ctype(
                _r.value, declared, self_fields, gen._async_api,
                None, frozenset(gen.struct_field_types.keys()),
                method_return_types=gen.func_return_types)
            if _t is not None and _t.endswith(' *') is False and _t in (
                    'int', 'int64_t', 'double', '_Bool', 'char *'):
                _ret_ct = _t if _ret_ct is None else (_t if _t == _ret_ct else 'int64_t')
        _ret_ct = _ret_ct or 'int64_t'
        _ret_base = (f"{base}_return_slot")
        gen._cpp_pending_return_store = (_ret_base, _ret_ct)
    gen._cpp_last_has_return_value = _has_return_value
    gen._cpp_list_local_elem_types = {}
    gcc_._cpp_reset_unit_state(gen)
    # Seed param list-ELEMENT types into the coroutine-body emitter's local
    # elem registry BEFORE body emission: a MojoList*-typed param whose
    # element type is known from a caller's collection-literal contract
    # (_xmod_gen_elem_hints, merged into _param_list_elem_types by
    # gen_module) makes `for line in <param>:` declare the loop variable
    # with the REAL element type (char *) and read through the matching
    # accessor — which in turn types every `yield <loop-var>` (and so this
    # unit's whole promise/value ctype) correctly, instead of the boxed
    # int64_t default that made foreign string generators unusable via
    # next()/for consumption. Same registry the AssignStmt/list-literal
    # tracking below already populates for LOCAL lists; params just had no
    # seeding site before.
    _pl_elem_hints = getattr(gen, '_param_list_elem_types', None) or {}
    _fn_elem_hints = _pl_elem_hints.get(fn.name) or {}
    if _fn_elem_hints:
        for _spn, _sct in param_ctypes:
            if _sct == 'MojoList *' and _fn_elem_hints.get(_spn):
                gen._cpp_list_local_elem_types[_spn] = _fn_elem_hints[_spn]
    try:
        body_lines: list[str] = []
        for s in fn.body:
            body_lines.extend(gen._cpp_stmt(s, declared, '    '))
        # Struct-pointer-yield support: `known_structs` (every struct
        # this compile has a real layout for) validates a "T *" ctype
        # actually names one; `_dict_val_types` maps `self.<field>` (for
        # a generator METHOD only — struct_name is None for a free
        # function, so this stays empty there, exactly like
        # `self_fields` itself does) to that field's dict VALUE ctype,
        # reusing `self._field_dict_val_types` (already populated
        # whole-program by ordinary struct-assignment analysis, not
        # freshly computed here) rather than inventing new tracking;
        # `self.func_return_types` (already the single source of truth
        # every ordinary compiled struct-method CALL site resolves a
        # method's return type through) doubles as `method_return_types`
        # for a struct-returning method-call chain. See
        # _infer_simple_expr_ctype's docstring for the full picture.
        _known_structs = frozenset(gen.struct_field_types.keys())
        _dict_val_types = ({f"self.{_fld}": _vt for _fld, _vt in
                             gen._field_dict_val_types.get(struct_name, {}).items()}
                            if struct_name is not None else {})
        # `cls.<class-attr>` sibling of the `self.<field>` seeding just
        # above — same "receiver key -> dict VALUE ctype" shape
        # `_receiver_key`'s `cls.` branch expects, sourced from
        # `self._class_attrs`/`self._global_dict_val_types` (the class-
        # level-global analogue of `_field_dict_val_types`) instead of
        # a per-instance field. Real: Lib/enum.py's `Flag.
        # _iter_member_by_value_`: `cls._value2member_map_.get(val)`.
        if struct_name is not None:
            for _aname, _gname in gen._class_attrs.get(struct_name, {}).items():
                _vt = gen._global_dict_val_types.get(_gname)
                if _vt is not None:
                    _dict_val_types[f"cls.{_aname}"] = _vt
        _field_elem_types = (gen._field_elem_types.get(struct_name, {})
                             if struct_name is not None else {})
        value_ctype = gimple_exprtypes._generator_yield_ctype(
            fn, declared, gen._generator_api, self_fields,
            known_structs=_known_structs, dict_val_types=_dict_val_types,
            method_return_types=gen.func_return_types,
            fn_return_types=gcc_._cpp_trusted_fn_return_types(gen),
            field_elem_types=_field_elem_types,
            local_elem_types=getattr(gen, '_cpp_list_local_elem_types', None),
            include_returns=False,
            self_struct_ctype=(f"{struct_name} *" if struct_name else None))
        # Tuple-valued yield (`yield a, b, ...`): _generator_yield_ctype
        # (just above) only decided the OVERALL promise value type
        # ('MojoList *' for a tuple yield, same as any plain list-
        # valued yield) — this companion call resolves the per-SLOT
        # element types a consumer for-loop needs to unbox that
        # pointer correctly (see _generator_tuple_yield_slot_ctypes's
        # own docstring). `has_tuple_yield=True, slots=None` means fn
        # DOES tuple-yield but the sites disagree on arity/slot type —
        # a real unsupported shape, so force the same graceful refusal
        # every other unsupported shape gets here, even though
        # _generator_yield_ctype itself came back non-None.
        has_tuple_yield, tuple_slot_ctypes = gimple_exprtypes._generator_tuple_yield_slot_ctypes(
            fn, declared, self_fields, gen._async_api,
            generator_api=gen._generator_api)
        if has_tuple_yield and tuple_slot_ctypes is None:
            value_ctype = None
        gen._cpp_last_tuple_slot_ctypes = tuple_slot_ctypes if has_tuple_yield else None
        func_decls = list(gen._cpp_func_scope_decls)
        self_recursed = gen._cpp_gen_self_recursed
    finally:
        gen._cpp_pending_tuple_slots = None
        gen._cpp_pending_return_store = None
        gen._cpp_emit_kind = 'generator'
        gen._cpp_gen_self_struct = None
        gen._cpp_gen_self_fields = None
        gen._cpp_declared = None
        gen._cpp_func_scope_decls = None
        gen._cpp_list_local_elem_types = {}
        gen._cpp_gen_self_name = None
        gen._cpp_gen_self_base = None
        gen._cpp_gen_self_params = None
        gen._cpp_gen_self_recursed = None
    if value_ctype is None:
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"{fn.name}: every `yield` must carry a value, and all "
            "values must agree on one scalar type (int64_t/double/_Bool)")
    if (value_ctype.endswith(' *') and value_ctype not in ('MojoList *', 'MojoDict *', 'MojoSet *')
            and value_ctype[:-2] in gen.struct_field_types):
        gen._cpp_value_struct_names.add(value_ctype[:-2])

    promise, handle_t, task, impl = (
        f"{base}_promise", f"{base}_handle", f"{base}_Task", f"{base}_impl")
    cpp_bool = 'bool'
    # value_ctype (returned below) is the C-side spelling — kept as-is
    # ('_Bool' included) since that's what the .c/.ci extern declaration
    # for `<base>_value` needs. Every occurrence INSIDE this .cpp text
    # must use cpp_value_ctype instead — '_Bool' isn't a valid C++ type
    # name (see _c_to_cpp_scalar_type's docstring); int64_t/double are
    # spelled identically in both languages so this is a no-op for them.
    cpp_value_ctype = gimple_exprtypes._c_to_cpp_scalar_type(value_ctype)
    # Parameter signature text, shared verbatim between the `impl`
    # coroutine function and the extern "C" `_start` wrapper that calls
    # it — the C++20 coroutine mechanics need no separate promise-side
    # plumbing: parameters to a coroutine function are copied into the
    # compiler-allocated coroutine frame exactly like any other C++20
    # coroutine's parameters (verified empirically: a plain `co_yield`-
    # based generator function can take ordinary by-value parameters and
    # they remain valid/in-scope across suspend/resume, same as a local
    # variable declared in the body).
    # Keyword-escaped parameter names were already registered into
    # self._cpp_kw_param_renames earlier, before the body was lowered
    # (see that attribute's own docstring for why it must happen
    # there and not here) — just consult it for this signature text.
    _sig_pn = lambda pn: gen._cpp_kw_param_renames.get(pn, pn)
    cpp_sig = (', '.join(f"{gimple_exprtypes._c_to_cpp_scalar_type(ct)} {_sig_pn(pn)}"
                          for pn, ct in param_ctypes)) or 'void'
    call_args = ', '.join(_sig_pn(pn) for pn, _ in param_ctypes)
    lines = [
        f"struct {promise};",
        f"using {handle_t} = std::coroutine_handle<{promise}>;",
        f"struct {task} {{",
        f"    using promise_type = {promise};",
        f"    {handle_t} h;",
        f"}};",
        f"struct {promise} {{",
        f"    {cpp_value_ctype} current_value{{}};",
        f"    {task} get_return_object() {{ return {task}{{ {handle_t}::from_promise(*this) }}; }}",
        f"    std::suspend_always initial_suspend() noexcept {{ return {{}}; }}",
        f"    std::suspend_always final_suspend() noexcept {{ return {{}}; }}",
        # Milestone D: an exception that escapes this coroutine's own
        # body uncaught is caught HERE, by the compiler-generated
        # wrapper around the whole coroutine body (invokes
        # unhandled_exception() from within its own catch-all).
        # Written STRAIGHT to the shared mojo_exc_*/mojo_exc_pending
        # globals rather than staged on the promise object first (the
        # obvious first-draft design) — found the hard way, via this
        # milestone's own required real compile+link+RUN verification
        # (not just the -fsyntax-only compile check test_gimple.py
        # does): adding even ONE extra field to a promise type breaks a
        # genuinely unrelated thing, a coroutine function taking 2+
        # parameters, on this project's GCC 15 -- confirmed via a
        # minimal, Mojo-independent repro (a plain promise with one
        # extra bool field plus a 2-parameter coroutine; the SECOND
        # parameter's value was read back out of the UNRELATED extra
        # promise field after resume — a real GCC-15 coroutine-frame-
        # layout miscalculation, not anything about exceptions
        # specifically). The promise here is therefore kept at its
        # ORIGINAL Milestone B/C shape (current_value only) —
        # unhandled_exception() has no reason to touch the promise at
        # all, so this sidesteps the compiler bug entirely rather than
        # working around it.
        f"    void unhandled_exception() {{",
        f"        try {{ std::rethrow_exception(std::current_exception()); }}",
        f"        catch (_MojoCppExc &__e) {{",
        f"            mojo_exc_type_set(__e.type_id);",
        f"            mojo_exc_msg_set(__e.msg);",
        f"            mojo_exc_obj_set(__e.obj);",
        f"            mojo_exc_pending_set(1);",
        f"        }}",
        f"        catch (...) {{",
        f"            /* Some other, non-Mojo C++ exception (e.g. a",
        f"               std::bad_alloc) escaped -- tag 0 (untyped) so",
        f"               it's still reported/catchable as SOME pending",
        f"               exception rather than silently discarded. */",
        f"            mojo_exc_type_set(0);",
        f"            mojo_exc_msg_set(nullptr);",
        f"            mojo_exc_obj_set(nullptr);",
        f"            mojo_exc_pending_set(1);",
        f"        }}",
        f"    }}",
        f"    std::suspend_always yield_value({cpp_value_ctype} v) {{ current_value = v; return {{}}; }}",
        f"    void return_void() {{}}",
        f"}};",
        # Self-recursion (see `self_recursed`/_cpp_yield_from's own
        # `is_self_recursive` branch): `{impl}`'s OWN body, built just
        # below, can call `{base}_start`/`_resume`/`_value`/`_destroy`
        # on itself (a delegating `yield from <this-same-function>
        # (...)`) — those extern "C" wrapper functions are only
        # DEFINED further down, after `{impl}`, so without a forward
        # declaration here first, g++ sees an undeclared-identifier
        # error at the self-call site (confirmed: this exact "was not
        # declared in this scope" error, for all four wrapper names,
        # reproduced before this forward-declaration block was added).
        # Harmless/unused when `self_recursed` is False (the ordinary,
        # non-recursive case) — nothing else in this file's own
        # generated .cpp text depends on absence of a forward decl.
        *([f"extern \"C\" MojoGenerator *{base}_start ({cpp_sig});",
           f"extern \"C\" {cpp_bool} {base}_resume (MojoGenerator *g);",
           f"extern \"C\" {cpp_value_ctype} {base}_value (MojoGenerator *g);",
           f"extern \"C\" void {base}_destroy (MojoGenerator *g);"]
          if self_recursed else []),
        # Value-carrying `return` channel (see the eligibility
        # computation above): one extern "C" global per unit, written by
        # the body's valued `return` right before co_return and read by
        # consumers after the generator reports done. C-linkage spelling
        # so cross-unit consumers can declare it by name. (The
        # initializer makes this a definition, not just a declaration.)
        *( [f"extern \"C\" {gimple_exprtypes._c_to_cpp_scalar_type(_ret_ct)} {_ret_base} = 0;"]
           if _has_return_value else [] ),
        f"static {task} {impl} ({cpp_sig}) {{",
        *(f"    {d}" for d in func_decls),
        *body_lines,
        f"    co_return;",
        f"}}",
        f'extern "C" MojoGenerator *{base}_start ({cpp_sig}) {{',
        f"    {task} t = {impl} ({call_args});",
        f"    return reinterpret_cast<MojoGenerator *>(t.h.address());",
        f"}}",
        f'extern "C" {cpp_bool} {base}_resume (MojoGenerator *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    if (h.done()) return false;",
        # Cleared right before resuming (not after — see
        # mojo_exc_pending_get's docstring in mojo_runtime.h): this
        # resume call is the only thing that could set it again before
        # anyone looks, so this is just belt-and-suspenders against a
        # flag some earlier, unrelated call left set without a
        # consumer ever clearing it.
        f"    mojo_exc_pending_set(0);",
        f"    h.resume();",
        # See mojo_runtime.h's long comment on _mojo_exc_pending: this
        # is the ONE place a compiled generator's own escaped exception
        # is translated into the shared, pre-existing mojo_exc_type/
        # msg/obj slots -- every ordinary (never-suspended) consumer of
        # this generator's `_resume` (a `for` loop, next(), or a
        # `yield from` delegation loop one level up) checks
        # mojo_exc_pending_get() immediately after seeing `_resume`
        # return false to tell real exhaustion apart from this.
        f"    if (mojo_exc_pending_get()) return false;",
        f"    return !h.done();",
        f"}}",
        f'extern "C" {cpp_value_ctype} {base}_value (MojoGenerator *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    return h.promise().current_value;",
        f"}}",
        f'extern "C" void {base}_destroy (MojoGenerator *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    if (h) h.destroy();",
        f"}}",
    ]
    return '\n'.join(lines), value_ctype, base, [ct for _, ct in param_ctypes]


def _compute_nested_closure_captures(gen, inner: gimple_ctypes.FunctionDef, outer_scope: dict) -> list:
    """[(name, ctype)] for free variables `inner` (a nested async
    closure — device_context.mojo's `async def wrapper(...) capturing
    -> None:` shape) references that resolve to a name in the enclosing
    method's own scope (self/params/threaded comptime params — see
    gen_module's nested-async-closure discovery pass, the only caller).
    Mirrors gen_module's own `_scan_for_closures` inner free-variable
    computation (used - declared - globals) for the ordinary (non-
    async) closure-lifting path, but deliberately NOT shared code with
    it — that closure is deeply embedded inside gen_module's own local
    scope and not easily factored out without broader risk to the
    already-working ordinary path; kept as its own small, self-
    contained duplicate instead, matching this project's already-
    accepted generator/async promise-type duplication precedent (see
    _gen_cpp_async_unit's own docstring for why that trade was made
    deliberately, not by oversight)."""
    used = gimple_exprtypes._used_idents_deep(inner.body)
    inner_params = {pn.lstrip('*') for pn, _ in (inner.params or [])}
    declared_vars = gimple_codegen._declared_vars_body(inner.body)
    free = used - inner_params - declared_vars
    return [(v, outer_scope[v]) for v in sorted(free) if v in outer_scope]


def _enclosing_scope_with_locals(gen, outer_fn: gimple_ctypes.FunctionDef) -> dict:
    """Widens `_compute_nested_closure_captures`'s `outer_scope` argument
    beyond just `outer_fn`'s own PARAMETERS (all every existing caller
    supplied before this method existed) to ALSO include `outer_fn`'s
    own top-level LOCAL variables (`var lock = ...`, `var counter =
    ...`) declared directly in its body -- real Mojo's own mutable-
    capture idiom (test_locks.mojo's `async def inc() {mut}: ...`
    closing over `lock`/`rawCounter`/`counter`, all locals of the
    enclosing `test_basic_lock`, not parameters) needs exactly this:
    without it, `_compute_nested_closure_captures`'s final `if v in
    outer_scope` filter silently DROPS every captured local (they were
    simply never in the dict at all), which is what made a captured
    local look like a plain undeclared name to the body emitter (the
    "augmented assignment to an undeclared/non-simple target" refusal)
    rather than being recognized as a capture in the first place.

    Deliberately SHALLOW (only `outer_fn.body`'s own top-level
    statements, via a single sequential pass -- does not descend into
    `if`/`for`/`with`/`try` blocks, mirroring `_declared_vars_body`'s
    own scope, and does NOT walk into nested function bodies, which
    are a separate scope entirely): real Mojo requires a local be
    declared (`var x = ...`) before any closure defined later in the
    same body can reference it, so a single top-to-bottom scan in
    source order, seeded with `outer_fn`'s own scalar parameters,
    correctly sees every local declared before the nested closure's
    own `async def` statement. A local declared AFTER the closure (or
    only inside a conditional/loop) is not resolvable this way and is
    simply left out of the returned scope -- exactly like an
    unresolvable parameter type already is -- so `_compute_nested_
    closure_captures` correctly treats it as "not capturable" rather
    than guessing.

    A captured local's ctype must match whatever `outer_fn`'s own
    ORDINARY (non-async) body compile will actually declare it as in
    real C -- getting this wrong doesn't just mis-infer a type, it
    makes a mutable capture's pointer parameter (`{ctype} *`) disagree
    with the real variable's own address (`&counter`), a hard `gcc`
    "incompatible pointer type" error (confirmed via a real hand-
    written repro). Two sources, tried in order, mirroring exactly how
    `_gen_stmt_VarDecl` itself decides a variable's declared type:
      1. `self._inferred_var_types[outer_fn.name]` -- populated by
         `_infer_local_var_types` in an earlier gen_module pass (always
         runs before this one). This is `_gen_stmt_VarDecl`'s own
         `self.var_types.get(name, ctype)` pre-seed: the WIDENED type
         a variable settles on when it's REASSIGNED (a plain `x = ...`,
         not `var x = ...`) one or more times with a value of a
         different type than its initial `var` declaration. Only
         covers names with at least one such reassignment (`_infer_
         local_var_types` scans `AssignStmt` only, never `VarDecl`).
      2. For a name with NO entry there (test_locks.mojo's/this
         method's own target shape: `var counter = 0`, declared once,
         never reassigned by a plain `counter = ...` anywhere) --
         `_gen_stmt_VarDecl` falls through to `vtype` from `self.
         lower_expr(node.value)`, i.e. the INITIALIZER's own real
         lowered type. `_quick_type`/`_infer_simple_expr_ctype` (this
         file's two other "guess a scalar type" helpers) both guess
         `int64_t` for a bare integer literal -- but `_lower_IntLiteral`
         (the REAL lowering `_gen_stmt_VarDecl` actually calls) returns
         plain C `int` instead (confirmed the hard way: an earlier
         draft of this method used `_infer_simple_expr_ctype` here,
         disagreeing with the real declared type). `_local_literal_
         ctype` (right below) mirrors `_lower_IntLiteral`/`_lower_
         FloatLiteral`/`_lower_BoolLiteral`'s exact literal-only rules
         instead of guessing via either of those broader estimators --
         deliberately narrow (bare literal initializers only): a local
         initialized from anything else (a call, another variable, an
         arithmetic expression, ...) is simply left OUT of the
         returned scope rather than risking a second independent guess
         disagreeing with the real one again."""
    scope: dict = {}
    for pname, ptype in (outer_fn.params or []):
        pname = pname.lstrip('*')
        ctype = gen._resolve_type(ptype) if ptype is not None else None
        if ctype in ('int64_t', 'int', 'double', '_Bool'):
            scope[pname] = ctype
    widened = gen._inferred_var_types.get(outer_fn.name, {})
    for name, ctype in widened.items():
        if ctype in ('int64_t', 'int', 'double', '_Bool') and name not in scope:
            scope[name] = ctype
    for stmt in outer_fn.body:
        if (isinstance(stmt, gimple_ctypes.VarDecl) and isinstance(stmt.name, str)
                and ',' not in stmt.name and stmt.name not in scope
                and stmt.name not in widened and stmt.type_ann is None
                and stmt.value is not None):
            ctype = gimple_exprtypes._local_literal_ctype(stmt.value)
            if ctype is not None:
                scope[stmt.name] = ctype
    return scope


def _mutated_free_names(gen, inner: gimple_ctypes.FunctionDef, candidate_names) -> frozenset:
    """Of `candidate_names` (a captured-free-variable name set --
    `_compute_nested_closure_captures`'s own return value, name-only),
    which ones `inner`'s own body ever REASSIGNS (a plain `name = ...`
    or `name += ...`/etc. with `name` as the direct target, anywhere in
    the body, any nesting depth via `_walk_ast` -- `if`/`while`/`with`/
    `try` bodies included) rather than only ever READING. Those need a
    genuine by-REFERENCE capture (threaded through the coroutine frame
    as a pointer parameter, dereferenced on every read/write inside the
    body -- see `_gen_cpp_async_unit`'s `mut_capture_names` parameter
    and `_cpp_expr`/`_cpp_stmt`'s own dereferencing) instead of the
    existing by-VALUE capture (a plain scalar parameter copy) every
    OTHER captured free variable still uses unchanged: real Mojo's own
    `test_locks.mojo` idiom (`async def inc() {mut}: rawCounter += 1`)
    needs the mutation to be visible to the CALLER across every one of
    thousands of separate task invocations, which a by-value copy
    cannot do. A name that's merely READ (e.g. `return x + 1`) is left
    out of this set and keeps the existing, already-verified by-value
    path -- unchanged, zero regression risk for every capture shape
    this project already supports (device_context.mojo's closures,
    `test_asyncrt_add`'s threaded comptime params, ...), none of which
    ever reassign a captured name."""
    # A plain `name = ...` assignment lexically INSIDE a deeper nested
    # `def` is that def's OWN fresh local binding (Python — and this
    # codegen's closure lifting — both scope it to the innermost def),
    # NOT a write to the captured free variable, even when the two share
    # a spelling: Lib/test/support/__init__.py's bigmemtest decorator
    # family does `size = wrapper.size` / `memuse = wrapper.memuse`
    # inside `wrapper` purely to read back function attributes that
    # shadow the outer names, and counting those as mutations made the
    # OUTER function's capture-store emit `{vtype} *` temps assigned
    # from plain int64_t locals ("assignment to 'int64_t *' from
    # 'int64_t' makes pointer from integer"). So plain assignments are
    # only collected for statements in THIS def's own body (control-flow
    # nesting included, nested defs excluded), while augmented
    # assignments (`name += 1`, real Mojo's `{mut}` idiom) still count
    # at every depth, preserving every previously-supported mutation
    # shape unchanged.
    mutated: set = set()
    _stack = list(inner.body)
    while _stack:
        n = _stack.pop(0)
        if isinstance(n, gimple_ctypes.FunctionDef):
            continue
        if isinstance(n, gimple_ctypes.AssignStmt) and isinstance(n.target, gimple_ctypes.IdentExpr):
            if n.target.name in candidate_names:
                mutated.add(n.target.name)
        elif isinstance(n, gimple_ctypes.AugAssignStmt) and isinstance(n.target, gimple_ctypes.IdentExpr):
            if n.target.name in candidate_names:
                mutated.add(n.target.name)
        elif isinstance(n, gimple_ctypes.IfStmt):
            _stack.extend(n.then_body)
            for _, _eb in n.elifs:
                _stack.extend(_eb)
            if n.else_body:
                _stack.extend(n.else_body)
        elif isinstance(n, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            _stack.extend(n.body)
            if getattr(n, 'else_body', None):
                _stack.extend(n.else_body)
        elif isinstance(n, gimple_ctypes.WithStmt):
            _stack.extend(n.body)
        elif isinstance(n, gimple_ctypes.TryStmt):
            _stack.extend(n.body)
            for _h in (n.handlers or []):
                _stack.extend(_h.body)
            if n.else_body:
                _stack.extend(n.else_body)
            if n.finally_body:
                _stack.extend(n.finally_body)
    return frozenset(mutated)


def _gen_cpp_async_unit(gen, fn: gimple_ctypes.FunctionDef, extra_captures: list | None = None,
                        base_name_override: str | None = None,
                        scope_prefix: str | None = None,
                        enclosing_scope: str | None = None,
                        mut_capture_names: frozenset = frozenset()) -> tuple[str, str, str, list]:
    """Step B of the compiled-path async/await codegen project (the
    async-function sibling of _gen_cpp_generator_unit, which Step B's
    planning deliberately decided should be a SEPARATE method/promise
    type rather than a parameter/extension of the generator one — see
    this project's plan doc: adding even ONE extra field to the
    generator's existing, already-fragile `_promise` shape corrupted a
    2+-parameter coroutine's frame on this project's GCC 15, confirmed
    via a minimal Mojo-independent repro (see the long comment on
    _gen_cpp_generator_unit's `unhandled_exception()`). A fresh,
    purpose-built promise type for async avoids ever touching that
    shape, at the one-time cost of some structural duplication between
    the two `_gen_cpp_*_unit` methods — an explicitly accepted,
    deliberate exception to this file's usual "consolidate, don't
    duplicate" convention (see CLAUDE.md), not an oversight.

    Returns (cpp_text, value_ctype, base, param_ctypes), mirroring
    _gen_cpp_generator_unit's return shape exactly (param_ctypes is
    always `[]` this step — see _async_quick_eligible's "no parameters
    yet" narrowing — but returned as a list anyway so gen_module's
    pre-pass loop and the extern-declaration emission further down can
    treat both dicts (_generator_api / _async_api) identically instead
    of needing a special case for "generators have params, async
    doesn't, yet").

    Calling convention (opaque handle + 4 extern "C" functions,
    deliberately shaped to match the generator convention's spirit
    without inventing a fifth, redundant driving mechanism):
      <base>_start()        -> MojoAsync*  (constructs, does NOT run any
                                 body code yet -- initial_suspend() is
                                 suspend_always, exactly like the
                                 generator promise, so calling the Mojo-
                                 level async function truly does not run
                                 its body immediately, matching real
                                 Python's "calling an async function
                                 returns a coroutine object" semantics
                                 and this project's own interpreter
                                 MojoCoroutine precedent -- see
                                 myinterpreter.py.)
      <base>_is_done(h)     -> _Bool  (poll: has this coroutine reached
                                 its final suspension point yet? Not
                                 actually consulted by THIS step's own
                                 call-site lowering, which drives
                                 unconditionally to completion in one
                                 shot since there are no suspension
                                 points to poll around yet -- provided
                                 now so a LATER step (real awaits, where
                                 a caller genuinely needs to check
                                 "did this complete or suspend again")
                                 doesn't need a wire-format change.)
      <base>_value(h)       -> value_ctype  (the completed co_return
                                 value; only valid to call once actually
                                 driven to completion.)
      <base>_destroy(h)     -> void  (coroutine_handle::destroy(),
                                 exactly like the generator convention.)
    Deliberately NO `<base>_resume` here (unlike the generator
    convention): this step's shape has no suspension points at all, so
    "resume" would be a redundant synonym for "run it once" -- the
    actual driving mechanism this step uses is Step A's OWN scheduler
    API directly (mojo_async_schedule_ready() +
    mojo_async_run_until_complete()), called straight from the .c call-
    site lowering (see _lower_call's `fname_raw in self._async_api`
    branch) -- reusing Step A's scheduler exactly as built, rather than
    wrapping it in a same-shaped-but-redundant `_resume`.
    """
    # Step H (create_task/Task/TaskGroup/RaisingTask project): scalar
    # parameter support, mirroring _gen_cpp_generator_unit's own
    # identical parameter-support step exactly (see that method's
    # docstring/comments for the full rationale) — a C++20 coroutine's
    # formal parameters are copied into the compiler-allocated
    # coroutine frame automatically, exactly like a generator's, so no
    # promise-side plumbing is needed here either. *args/**kwargs and
    # any non-scalar parameter type are still refused (same as
    # generators). Real Mojo's `create_task`/`RaisingTask` machinery
    # this project rewrites onto this unit (see ast_rewriter.py) always
    # wraps a plain `def`/`async def` with ordinary scalar params (Int/
    # Bool) — no struct/string parameters are needed for either target
    # test file, so this mirrors the generator project's own narrow
    # "small natural extension" scope rather than opening new
    # complexity.
    param_ctypes: list[tuple[str, str]] = []
    for pn, pt in (fn.params or []):
        if pn.startswith('*'):
            raise gimple_exprtypes._UnsupportedAsyncShape(
                f"{fn.name}: *args/**kwargs parameters not supported "
                "for compiled async functions")
        ctype = gen._param_ctype(pn, pt, fn)
        # See the identical struct-pointer-acceptance note in
        # _gen_cpp_generator_unit — same allow-list, same reasoning,
        # same shared _cpp_expr body-side machinery.
        _is_struct_ptr = (ctype.endswith(' *')
                          and ctype[:-2] in gen.struct_field_types)
        if _is_struct_ptr:
            gen._cpp_param_struct_names.add(ctype[:-2])
        if ctype not in ('int64_t', 'double', '_Bool', 'char *', 'MojoList *',
                         'MojoDict *', 'MojoSet *') and not _is_struct_ptr:
            raise gimple_exprtypes._UnsupportedAsyncShape(
                f"{fn.name}: async function parameter '{pn}' has "
                f"unsupported type {ctype!r} (only int64_t/"
                "double/_Bool/char*/<known struct>* parameters are "
                "supported for compiled async functions)")
        param_ctypes.append((pn, ctype))
    # A NESTED async closure's captured free variable(s) (device_
    # context.mojo's `async def wrapper(...) capturing -> None:`,
    # closing over its enclosing method's `func`/`FuncType` bracket
    # parameter) are threaded through as ordinary trailing parameters,
    # exactly like the general (non-async) closure-capture path's
    # _method_threaded_comptime_params mechanism does for the SAME
    # captured value in the ordinary GIMPLE codegen — a C++20
    # coroutine's formal parameters are copied into the compiler-
    # allocated frame automatically, so this needs no extra promise-
    # side plumbing beyond appending them here; the call site (see the
    # nested-async-closure discovery pass in gen_module) supplies the
    # captured value(s) automatically, exactly as if they were ordinary
    # call arguments, since the Mojo source itself never spells them
    # out at the `wrapper()` call site.
    # `extra_captures` always stores each entry's PLAIN ctype (e.g.
    # "int64_t") -- a comptime bracket parameter (never reassignable)
    # always keeps that plain ctype in the compiled SIGNATURE too, but
    # an entry whose name is in `mut_capture_names` (see this method's
    # own docstring on that parameter) is widened to a POINTER ctype
    # HERE, in the one place that actually builds the C++ function
    # signature -- the caller (gen_module's discovery passes) never
    # bakes " *" into the stored dict itself, so every OTHER consumer
    # of that same captures list (the call-site argument-forwarding in
    # `_lower_call`'s create_task branch) can derive the same pointer
    # type from the identical plain-ctype + mut_capture_names pair,
    # rather than two places independently deciding this.
    for cap_name, cap_ctype in (extra_captures or []):
        if cap_name in mut_capture_names:
            param_ctypes.append((cap_name, f"{cap_ctype} *"))
        else:
            param_ctypes.append((cap_name, cap_ctype))
    # Bare `fn.name` is only unique for a genuinely top-level compiled
    # async function. Two DISTINCT nested shapes need a qualified name
    # instead, mutually exclusive (a caller only ever supplies one):
    #   - A NESTED ASYNC CLOSURE (device_context.mojo's `wrapper` —
    #     struct-method-nested, see gen_module's dedicated discovery
    #     pass) is defined separately inside EACH of several methods
    #     (this exact file has FOUR distinct `wrapper` closures, one per
    #     enqueue_cpu_function/enqueue_cpu_range overload) — a bare-name
    #     `base` collided across all four (`_mojoasync_wrapper_start`
    #     redeclared with different signatures each time — a real,
    #     hand-verified "conflicting types" gcc error, the exact same
    #     class of bug _method_threaded_comptime_params' own struct/
    #     overload-blind keying hit earlier), so the caller supplies a
    #     fully-qualified override name instead (mirroring the ordinary
    #     closure-lifting convention's own `f"{outer}_{inner.name}"`
    #     mangling exactly).
    #   - A NESTED ASYNC FUNCTION (Step I's `@parameter async def
    #     wrapper(): ...` — nested inside an ordinary top-level
    #     function's body, see _compile_nested_async_functions) passes
    #     its own enclosing function's name as `scope_prefix`, mirroring
    #     _gen_cpp_generator_unit's identical `{struct_name}_
    #     {method_name}` qualification for generator METHODS -- needed
    #     for the identical reason: two DIFFERENT enclosing functions
    #     each defining their own same-named nested async def (e.g. two
    #     different tests each with their own local `wrapper()`) would
    #     otherwise collide on identical C++ symbol names.
    # A genuinely top-level async function (neither override supplied)
    # keeps its original, unqualified base exactly as before.
    if base_name_override:
        base = f"_mojoasync_{gimple_ctypes._safe_name(base_name_override)}"
    elif scope_prefix:
        base = f"_mojoasync_{gimple_ctypes._safe_name(scope_prefix)}_{gimple_ctypes._safe_name(fn.name)}"
    else:
        base = f"_mojoasync_{gimple_ctypes._safe_name(fn.name)}"
    # Params are already "declared" locals as far as the body emitter is
    # concerned -- exactly mirrors _gen_cpp_generator_unit's identical
    # `declared` seeding (see that method's docstring for why this
    # ordering, body-emission-before-value_ctype-is-computed, matters
    # for an unannotated return/local that reads a param).
    #
    # A MUTATED capture (`mut_capture_names` -- see `_mutated_free_
    # names`) is threaded through as a POINTER parameter (its entry in
    # `param_ctypes`/`extra_captures` is already e.g. "int64_t *", built
    # by the caller), but `declared` here must record its DEREFERENCED
    # (pointee) type instead -- `declared`/`known` feeds `_infer_
    # simple_expr_ctype` for ordinary scalar type-inference (e.g. `x =
    # counter + 1`), which must see `counter` as `int64_t`, not `int64_t
    # *`, or arithmetic involving it would infer a bogus pointer type.
    # The C++ SIGNATURE itself (built from `param_ctypes`, above,
    # unchanged) still correctly declares the real pointer parameter --
    # only this type-inference-facing dict differs.
    # Reset + seed self._cpp_kw_param_renames for THIS unit's params
    # before the body is lowered below (see _gen_cpp_generator_unit's
    # identical reset for the full rationale — must happen before
    # _cpp_stmt/_cpp_expr are ever called for this function's body,
    # not alongside cpp_sig's later construction).
    gen._cpp_kw_param_renames = {}
    for _pn, _ in param_ctypes:
        if _pn in gimple_ctypes._C_KEYWORDS or _pn in gimple_ctypes._CPP_KEYWORD_FIELDS or _pn in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS:
            gen._cpp_kw_param_renames[_pn] = f"_kw_{_pn}"
    declared: dict[str, str] = {}
    for _pn, _pct in param_ctypes:
        if _pn in mut_capture_names and _pct.endswith(' *'):
            declared[_pn] = _pct[:-2]
        else:
            declared[_pn] = _pct
    gen._cpp_gen_self_struct = None
    gen._cpp_gen_self_fields = None
    gen._cpp_emit_kind = 'async'
    # See _cpp_expr's IdentExpr case / _cpp_stmt's AssignStmt/
    # AugAssignStmt cases: every read/write of a name in this set is
    # auto-dereferenced (`(*name)` / `*name = ...`) instead of a bare
    # `name` -- the ONE piece of state those methods need to tell a
    # mutated-by-reference capture apart from an ordinary scalar local/
    # parameter, mirroring `_cpp_gen_self_fields`'s identical side-
    # channel technique (this coroutine-body emitter has no `self`-
    # scoped AST annotation to consult instead).
    gen._cpp_mut_capture_names = mut_capture_names
    # `enclosing_scope` (when supplied -- only by gen_module's "Async
    # closures/functions NESTED INSIDE A TOP-LEVEL FUNCTION" pass, the
    # SAME enclosing top-level function name it uses to key
    # self._async_closure_api) is threaded through this side channel
    # (mirroring self._cpp_gen_self_fields' identical technique) so
    # `_cpp_expr`'s AwaitExpr composition case can resolve a SIBLING
    # bracket-parametrized nested async def (`await create_task(
    # test_asyncrt_add[1](a))`, test_asyncrt.mojo's own shape) without
    # relying on self.current_func_name, which this coroutine-body
    # emitter path never sets (unlike ordinary gen_func/gen_stmt
    # compiles) -- see that AwaitExpr case's own comment.
    gen._cpp_async_enclosing_scope = enclosing_scope
    gen._cpp_declared = declared
    func_decls: list[str] = []
    gen._cpp_func_scope_decls = []
    try:
        body_lines: list[str] = []
        for s in fn.body:
            body_lines.extend(gen._cpp_stmt(s, declared, '    '))
        # The single scalar type every `return <expr>` in fn's own body
        # must agree on -- reuses _generator_yield_ctype's exact same
        # walk-and-unify logic (it only ever looks at ReturnStmt/
        # YieldExpr/YieldFromExpr nodes generically via ITS OWN
        # `_walk_ast`-based scan; see that function's body) even though
        # its name says "yield", not duplicated as a second
        # "_async_return_ctype" that would just re-implement the same
        # unify-across-every-site logic. `_generator_yield_ctype` scans
        # for a `return <value>` case too (Milestone B never populated
        # one — no compiled generator returns a value -- so its
        # ReturnStmt branch until this step was pure dead code; Step B
        # is genuinely the first thing to exercise it).
        # Step I: scope self._async_closure_api (keyed by (enclosing top-
        # level function name, callee name)) down to a plain name -> api
        # dict for JUST this unit's own enclosing function, mirroring
        # `async_api`'s bare-name-keyed shape -- see `enclosing_scope`'s
        # own docstring on why this coroutine-body compile can't just
        # use self.current_func_name for the lookup key.
        # Plain loop, not a dict-comprehension-with-tuple-key-unpacking
        # -- this project's OWN self-hosting compiler (`make check-
        # selfhost`) has no translation for that specific comprehension
        # shape (confirmed via a real self-host build failure: "expected
        # expression before '(' token"), mirroring the sibling "Plain
        # for-loops (not comprehensions)" note a few thousand lines down
        # in gen_module for the identical reason.
        _closure_api_scoped = None
        if enclosing_scope:
            _closure_api_scoped = {}
            for _cak, _cav in gen._async_closure_api.items():
                if _cak[0] == enclosing_scope:
                    _closure_api_scoped[_cak[1]] = _cav
        # Struct-pointer-return support (mirrors _gen_cpp_generator_
        # unit's identical widening — see that call site's own comment
        # and _infer_simple_expr_ctype's docstring): an async function
        # has no `self_fields` (never struct-scoped here), so only the
        # struct-typed-PARAMETER + struct-method-call-chain shape
        # applies (`known_structs`/`method_return_types`); no
        # `dict_val_types` (nothing to key it from with self_fields=
        # None).
        value_ctype = gimple_exprtypes._generator_yield_ctype(
            fn, declared, generator_api=None, self_fields=None,
            async_api=gen._async_api, closure_api=_closure_api_scoped,
            known_structs=frozenset(gen.struct_field_types.keys()),
            method_return_types=gen.func_return_types)
        # Step I: an async function whose body NEVER reaches an
        # ordinary `return <expr>` at all (real Mojo's own idiom for an
        # always-raising helper, e.g. `async def failing_async() raises
        # -> Int: raise Error(...)` — see test_raising_asyncrt.mojo) has
        # no ReturnStmt for `_generator_yield_ctype`'s walk to unify a
        # type from at all, so it always came back None here even
        # though the function DOES have a real, resolvable scalar
        # declared return-type annotation (`-> Int`) — fall back to
        # that annotation, but ONLY when there is genuinely no
        # value-carrying return anywhere (if there IS one and it
        # resolved to None, that's a real "can't infer a scalar type"
        # refusal, not this case, so must not be papered over here).
        if value_ctype is None and not any(
                isinstance(n, gimple_ctypes.ReturnStmt) and n.value is not None
                for n in gimple_exprtypes._walk_ast(fn.body)):
            annotated = gen._resolve_type(fn.return_type) if fn.return_type else None
            if annotated in ('int64_t', 'double', '_Bool'):
                value_ctype = annotated
        func_decls = list(gen._cpp_func_scope_decls)
    finally:
        gen._cpp_emit_kind = 'generator'
        gen._cpp_gen_self_struct = None
        gen._cpp_gen_self_fields = None
        gen._cpp_async_enclosing_scope = None
        gen._cpp_declared = None
        gen._cpp_func_scope_decls = None
        gen._cpp_list_local_elem_types = {}
        gen._cpp_mut_capture_names = frozenset()
    if value_ctype is None:
        # A genuinely void-returning async function (declared `-> None`
        # or unannotated, with no value-carrying `return` anywhere) —
        # see bugs/CODEGEN_device_context_captured_function_parameter_
        # closures_broken.md's device_context.mojo follow-on: its
        # `async def wrapper(...) capturing -> None:` closures never
        # return a value at all (their entire body is a single call to
        # the captured function). Distinct from the "return present but
        # types disagree / unsupported" case above (still an honest
        # refusal): only promoted to 'void' when there is NO value-
        # carrying `return` anywhere in the body at all.
        _has_value_return = any(
            isinstance(n, gimple_ctypes.ReturnStmt) and n.value is not None
            for n in gimple_exprtypes._walk_ast(fn.body))
        if not _has_value_return and fn.return_type in (None, 'None'):
            value_ctype = 'void'
            # A C++20 function is only actually TREATED as a coroutine
            # if its body syntactically contains at least one
            # co_return/co_await/co_yield -- merely defining
            # return_void() on the promise is not enough. Mojo source
            # with no `return`/`await` anywhere at all (e.g. `pass`, or
            # a bare call statement — device_context.mojo's `wrapper()`
            # closures) would otherwise compile as an ordinary (non-
            # coroutine) function falling off the end without ever
            # returning its by-value `_Task` result -- real undefined
            # behavior, which this project's GCC/Clang helpfully
            # compiles to a hard trap instruction rather than silently
            # garbage (confirmed via a hand-written repro: EXC_BREAKPOINT
            # at the very first instruction of the "impl" function).
            # An explicit trailing `co_return;` guarantees the marker
            # exists syntactically, regardless of what's already in
            # body_lines.
            body_lines.append("    co_return;")
        else:
            raise gimple_exprtypes._UnsupportedAsyncShape(
                f"{fn.name}: every `return` must carry a scalar value "
                "(int64_t/double/_Bool), and all of them must agree on "
                "one consistent type")
    if (value_ctype.endswith(' *') and value_ctype not in ('MojoList *', 'MojoDict *', 'MojoSet *')
            and value_ctype[:-2] in gen.struct_field_types):
        gen._cpp_value_struct_names.add(value_ctype[:-2])

    promise, handle_t, task, impl = (
        f"{base}_promise", f"{base}_handle", f"{base}_Task", f"{base}_impl")
    final_awaiter, awaiter = f"{base}_FinalAwaiter", f"{base}_Awaiter"
    cpp_value_ctype = gimple_exprtypes._c_to_cpp_scalar_type(value_ctype)
    # Step H: parameter signature text, shared verbatim between the
    # `impl` coroutine function and the extern "C" `_start` wrapper --
    # mirrors _gen_cpp_generator_unit's identical `cpp_sig`/`call_args`
    # exactly (see that method's comment for why no promise-side
    # plumbing is needed: C++20 coroutine frame allocation copies
    # parameters into the frame itself automatically).
    # Keyword-escaped parameter names were already registered into
    # self._cpp_kw_param_renames earlier, before the body was lowered
    # (see that attribute's own docstring for why it must happen
    # there and not here) — just consult it for this signature text.
    _sig_pn = lambda pn: gen._cpp_kw_param_renames.get(pn, pn)
    cpp_sig = (', '.join(f"{gimple_exprtypes._c_to_cpp_scalar_type(ct)} {_sig_pn(pn)}"
                          for pn, ct in param_ctypes)) or 'void'
    call_args = ', '.join(_sig_pn(pn) for pn, _ in param_ctypes)
    lines = [
        f"struct {promise};",
        f"using {handle_t} = std::coroutine_handle<{promise}>;",
        f"struct {task} {{",
        f"    using promise_type = {promise};",
        f"    {handle_t} h;",
        f"}};",
        # Step D (async-awaits-async composition): a dedicated
        # final-suspend awaiter type PER async function, instead of the
        # bare `std::suspend_always` Step B/C used -- needed because
        # final_suspend must now do one extra thing beyond "stay
        # suspended so <base>_value()/<base>_destroy() can still reach
        # the completed frame" (unchanged from Step B/C, still true
        # below): if ANOTHER coroutine is awaiting THIS one (recorded
        # in the promise's own `continuation` field, set by that
        # OTHER coroutine's own `{base}_Awaiter::await_suspend`, a few
        # lines down), resume it -- specifically by pushing it onto
        # Step A's ready queue (mojo_async_schedule_ready), NOT by
        # resuming it directly/via symmetric transfer here. Routing
        # through the ready queue (rather than a direct
        # `return promise.continuation;`, the more common textbook
        # "symmetric transfer" idiom) keeps every resume in this
        # project driven through ONE place (Step A's
        # mojo_async_run_until_complete loop), exactly matching how
        # Step C's own SleepAwaiter already hands control back to the
        # scheduler rather than ever resuming another coroutine
        # in-line -- one consistent "who drives whom" story across
        # every awaiter this codegen emits, not two different ones.
        # Declared here (forward-declared members only) and DEFINED
        # out-of-line below {promise} itself, since await_suspend's
        # body needs `h.promise().continuation`, and a member function
        # body defined INLINE here would need {promise} to already be
        # a complete type -- impossible, since {promise} itself names
        # this awaiter type in ITS OWN final_suspend() return type,
        # a couple of lines down (the same forward-declare-then-
        # define-out-of-line split proven safe by this project's own
        # GCC-15 promise-field repro -- see this method's docstring
        # and the commit introducing this comment for the hand-written,
        # Mojo-independent confirmation that adding a `continuation`
        # field to this (parameter-less, Step B/C/D's whole scope)
        # promise shape does NOT reproduce Milestone D's generator-
        # promise/2+-param frame-corruption bug: that bug was
        # specifically about a coroutine with real FORMAL PARAMETERS,
        # which no compiled async function has ever had, this step
        # included).
        f"struct {final_awaiter} {{",
        f"    bool await_ready() noexcept {{ return false; }}",
        f"    std::coroutine_handle<> await_suspend({handle_t} h) noexcept;",
        f"    void await_resume() noexcept {{}}",
        f"}};",
        f"struct {promise} {{",
        (f"    {cpp_value_ctype} result{{}};" if value_ctype != 'void'
         else "    /* void: no stored return value */"),
        # Step E (exceptions): an exception that escapes this
        # coroutine's own body uncaught is NOT translated straight into
        # the shared mojo_exc_*/mojo_exc_pending globals the way the
        # generator promise's unhandled_exception() does (see
        # _gen_cpp_generator_unit) -- doing that here would be too EARLY
        # for async, because of composition (Step D): if some OTHER
        # coroutine is awaiting this one, the exception needs to
        # surface as a real C++ exception thrown into THAT caller's own
        # body (so its own try/except can catch it, exactly like real
        # Python's `await` propagating an exception), not silently
        # swallowed into global state before the caller even gets a
        # chance to see it. So it's staged here instead, on the promise
        # itself, and only the ONE place that's genuinely the "nobody
        # left awaiting" outermost edge -- the `asyncio.run(...)`
        # bridge in _lower_call, via the `{base}_translate_pending_exc`
        # extern "C" helper below -- ever copies it into the shared
        # globals, reusing the generator's exact translation
        # convention there and ONLY there. Adding these two fields to
        # this promise is safe against Milestone D's GCC-15 promise-
        # field/2+-parameter-coroutine-frame-corruption bug (see
        # {final_awaiter}'s own docstring above): that bug's trigger
        # was specifically a coroutine with real formal PARAMETERS,
        # which no compiled async function has ever had, `continuation`
        # (Step D) included -- verified via this project's own
        # from-scratch hand repro before Step D ever added a field
        # here, and unchanged by adding two more of the same
        # (parameter-less) kind.
        f"    _MojoCppExc exc{{}};",
        f"    bool exc_pending{{}};",
        # Type-erased (not `{handle_t}`): the coroutine AWAITING this
        # one may be an entirely different async function with its own
        # distinct promise type (e.g. `outer`'s promise stores a
        # continuation of type `_mojoasync_outer_handle`-independent
        # `std::coroutine_handle<>` while awaiting `inner`'s promise,
        # which is `_mojoasync_inner_promise` -- there is no single
        # concrete handle type that could work here across every
        # possible caller). Default-constructed (`{{}}`) is the null/
        # empty handle -- `if (continuation)` below correctly reads as
        # "false" for a coroutine nobody is awaiting (the ordinary
        # `asyncio.run(...)`-driven top-level case, unchanged from
        # Step B/C), exactly like a null function pointer.
        f"    std::coroutine_handle<> continuation{{}};",
        f"    {task} get_return_object() {{ return {task}{{ {handle_t}::from_promise(*this) }}; }}",
        f"    std::suspend_always initial_suspend() noexcept {{ return {{}}; }}",
        # final_suspend() itself still ALWAYS suspends (the {final_
        # awaiter}'s own await_ready() is unconditionally false) --
        # exactly like Step B/C's plain `std::suspend_always`, and for
        # the same reason: `<base>_value()` needs to read `result`
        # back out of the (still-alive) promise AFTER the coroutine has
        # completed, so the frame must not auto-destroy itself the
        # instant co_return runs -- the caller (either the top-level
        # `asyncio.run(...)` bridge, unchanged, or -- Step D -- the
        # AWAITING coroutine's own `{base}_Awaiter::await_resume`, a
        # few lines down) destroys it explicitly, mirroring the
        # generator convention's `_destroy` exactly (not a new cleanup
        # convention). What's NEW in Step D is only what happens
        # DURING that final suspension (see {final_awaiter} above): if
        # some other coroutine is waiting on this one, it gets resumed
        # (via the ready queue) as a side effect of reaching here,
        # instead of nothing happening (Step B/C: nobody could ever be
        # waiting, since composition didn't exist yet).
        f"    {final_awaiter} final_suspend() noexcept {{ return {{}}; }}",
        # Step E: an exception that escapes this coroutine's own body
        # uncaught is caught here (the compiler-generated wrapper
        # around the whole coroutine body invokes this from within its
        # own catch-all), exactly like the generator promise's
        # unhandled_exception() -- but staged on THIS promise's own
        # exc/exc_pending fields instead of written straight to the
        # shared globals (see those fields' own docstring just above
        # for why: composition needs the exception to still be able to
        # surface as a real, catchable C++ exception in an awaiting
        # caller's own body, which writing to global state here, before
        # any caller gets a chance to see it, would foreclose).
        f"    void unhandled_exception() {{",
        f"        try {{ std::rethrow_exception(std::current_exception()); }}",
        f"        catch (_MojoCppExc &__e) {{ exc = __e; exc_pending = true; }}",
        f"        catch (...) {{",
        f"            /* Some other, non-Mojo C++ exception (e.g. a",
        f"               std::bad_alloc) escaped -- tag 0 (untyped) so",
        f"               it's still reported/catchable as SOME pending",
        f"               exception rather than silently discarded,",
        f"               mirroring the generator promise's own",
        f"               unhandled_exception() catch-all exactly. */",
        f"            exc = _MojoCppExc{{ (int64_t)0, nullptr, nullptr }};",
        f"            exc_pending = true;",
        f"        }}",
        f"    }}",
        (f"    void return_value({cpp_value_ctype} v) {{ result = v; }}"
         if value_ctype != 'void' else "    void return_void() noexcept {}"),
        f"}};",
        f"inline std::coroutine_handle<> {final_awaiter}::await_suspend({handle_t} h) noexcept {{",
        f"    std::coroutine_handle<> cont = h.promise().continuation;",
        f"    if (cont) mojo_async_schedule_ready(cont.address());",
        f"    return std::noop_coroutine();",
        f"}}",
        f"static {task} {impl} ({cpp_sig}) {{",
        *(f"    {d}" for d in func_decls),
        *body_lines,
        # Step I: an always-raising function's body (e.g. `raise
        # Error(...)` with no `return` anywhere at all — see the
        # value_ctype fallback above) has NO co_return/co_await/
        # co_yield anywhere in body_lines, which would mean the C++
        # compiler never even recognizes `{impl}` as a coroutine at
        # all (a hard C++20 requirement: at least one of those three
        # keywords must appear textually in the function body for it
        # to BE a coroutine, wired to {promise}/get_return_object()).
        # Unconditionally appending a dummy `co_return 0;` here is safe
        # for EVERY async function this codegen compiles, not just the
        # always-raising case: every reachable normal-exit path already
        # ends in a real `co_return <expr>;` from an explicit `return`
        # (see _cpp_stmt's ReturnStmt case), so this line is simply
        # unreachable dead code there (valid, harmless C++ — no error,
        # unlike a genuinely missing return); the only case where it is
        # NOT dead is exactly the one this fixes.
        f"    co_return ({cpp_value_ctype})0;",
        f"}}",
        f'extern "C" MojoAsync *{base}_start ({cpp_sig}) {{',
        f"    {task} t = {impl} ({call_args});",
        f"    return reinterpret_cast<MojoAsync *>(t.h.address());",
        f"}}",
        # 'bool' (not '_Bool' -- see _c_to_cpp_scalar_type's docstring:
        # '_Bool' is valid C99 but not a valid C++ type spelling). The
        # .c-side extern declaration for this same function correctly
        # keeps '_Bool' (see gen_module's preamble emission) -- only the
        # spelling differs per language, same convention as every other
        # scalar crossing this boundary.
        f'extern "C" bool {base}_is_done (MojoAsync *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    return h.done();",
        f"}}",
        f'extern "C" {cpp_value_ctype} {base}_value (MojoAsync *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        ("    (void)h;" if value_ctype == 'void' else "    return h.promise().result;"),
        f"}}",
        f'extern "C" void {base}_destroy (MojoAsync *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    if (h) h.destroy();",
        f"}}",
        # Step E: the OUTERMOST-edge translation -- called ONLY from the
        # `asyncio.run(...)` bridge in _lower_call, right after
        # mojo_async_run_until_complete() drives this top-level
        # coroutine to completion (genuinely never-suspended ordinary
        # GIMPLE C code at that call site, exactly like the generator
        # convention's own `_resume()` boundary -- see
        # _gen_cpp_generator_unit's unhandled_exception()/mojo_runtime.h's
        # long comment on _mojo_exc_pending), never from inside another
        # coroutine's own body (composition's rethrow-into-caller,
        # above, handles that case instead -- this function and that
        # one read the SAME staged exc/exc_pending state, just from two
        # different callers depending on whether anyone is actually
        # awaiting). If this top-level coroutine completed via an
        # uncaught exception, copies it into the shared mojo_exc_type/
        # msg/obj/mojo_exc_pending globals -- the EXACT SAME translation
        # convention the generator promise's own unhandled_exception()
        # used to write directly, reused here rather than reinvented --
        # so ordinary (non-async, non-generator) compiled code calling
        # `asyncio.run(...)` inside its own try/except (a real setjmp-
        # based frame, safe to longjmp into from here since this call
        # site was never itself suspended) observes it the normal way
        # once _lower_call's own mojo_exc_pending_get()/mojo_raise()
        # check (mirroring _emit_generator_pending_exc_check exactly)
        # runs right after this call returns.
        f'extern "C" void {base}_translate_pending_exc (MojoAsync *g) {{',
        f"    {handle_t} h = {handle_t}::from_address(reinterpret_cast<void *>(g));",
        f"    if (h.promise().exc_pending) {{",
        f"        mojo_exc_type_set(h.promise().exc.type_id);",
        f"        mojo_exc_msg_set(h.promise().exc.msg);",
        f"        mojo_exc_obj_set(h.promise().exc.obj);",
        f"        mojo_exc_pending_set(1);",
        f"    }}",
        f"}}",
        # Step D: the awaiter ANOTHER compiled async function's body
        # uses to `await {fn.name}()` -- see GimpleGen._cpp_expr's own
        # AwaitExpr case, which emits exactly
        # `co_await {awaiter}{{{impl} ().h}}` at each such call site.
        # Constructed directly from `{impl} ()` (the internal,
        # strongly-typed constructor function a few lines up), NOT
        # through the `extern "C"`/`MojoAsync *` boundary {base}_start
        # uses -- composition only ever happens between two coroutines
        # in the SAME .cpp translation unit (this whole module's
        # `_generator_cpp_units` are concatenated into one .cpp file --
        # see gen_module), so there is no ABI boundary to cross here,
        # and going through the untyped `void *`/from_address() round
        # trip {base}_start exists for would only add risk (a
        # same-address-different-promise-type reinterpret_cast bug)
        # for zero benefit. `await_suspend` registers the awaiting
        # coroutine as this callee's continuation and pushes the
        # callee onto Step A's ready queue (mirrors the
        # `asyncio.run(...)` bridge's own
        # `mojo_async_schedule_ready`+drive pattern, reused rather than
        # a second scheduling convention) -- the callee genuinely runs
        # as its own independently-scheduled turn of the SAME
        # scheduler loop the caller itself is being driven by, not a
        # direct/inline call, so a callee that itself awaits something
        # real (asyncio.sleep, or a further nested async call) composes
        # correctly: the caller stays suspended until the callee's own
        # {final_awaiter} reschedules it, exactly like every other
        # ready-queue-driven resume in this runtime. `await_resume`
        # reads the completed value back out of the callee's promise
        # and destroys its frame (the callee is never separately
        # `_destroy`-ed by anyone else -- this awaiter, not the
        # `asyncio.run(...)` bridge, owns that callee's whole
        # lifetime, since nothing outside this awaiter ever held a
        # reference to it).
        #
        # Step E: this is the one genuinely NEW piece of design this
        # step adds (not a copy of anything the generator project
        # already built) -- the per-awaiter rethrow. If the callee
        # completed via an uncaught exception rather than an ordinary
        # `co_return` (staged on the callee's OWN promise by its
        # unhandled_exception(), above), `await_resume` -- which runs
        # as part of the AWAITING coroutine's own resumption, right at
        # the point the `co_await` expression is being evaluated --
        # throws a FRESH `_MojoCppExc` built from that staged state,
        # INTO the awaiting coroutine's own body. This is exactly the
        # same "real C++ exception, confined to this translation unit"
        # representation _cpp_raise_stmt/_cpp_try_stmt already use, so
        # an enclosing `try`/`except` the awaiting function's own body
        # wraps around this `await` (translated by the SAME
        # _cpp_try_stmt every other try/except in this coroutine's body
        # already goes through -- no separate/special case needed
        # there) catches it exactly like real Python's `await`
        # propagating an exception through ordinary exception
        # machinery. If nobody awaits this callee at all (the top-level
        # `asyncio.run(...)` case), this awaiter is never constructed
        # for it, so the staged exc/exc_pending is picked up instead by
        # `{base}_translate_pending_exc` below -- the SAME staged state,
        # read from two different places depending on who's actually
        # waiting on it, not two different representations.
        f"struct {awaiter} {{",
        f"    {handle_t} callee_h;",
        f"    bool await_ready() noexcept {{ return false; }}",
        f"    void await_suspend(std::coroutine_handle<> caller_h) noexcept {{",
        f"        callee_h.promise().continuation = caller_h;",
        f"        mojo_async_schedule_ready(callee_h.address());",
        f"    }}",
        f"    {cpp_value_ctype} await_resume() {{",
        f"        if (callee_h.promise().exc_pending) {{",
        f"            _MojoCppExc __e = callee_h.promise().exc;",
        f"            callee_h.destroy();",
        f"            throw __e;",
        f"        }}",
        (f"        {cpp_value_ctype} v = callee_h.promise().result;"
         if value_ctype != 'void' else "        callee_h.destroy();"),
        ("        callee_h.destroy();" if value_ctype != 'void' else ""),
        ("        return v;" if value_ctype != 'void' else "        return;"),
        f"    }}",
        f"}};",
    ]
    return '\n'.join(lines), value_ctype, base, [ct for _, ct in param_ctypes]


def _resolve_and_start_task(gen, inner) -> tuple[str, dict] | None:
    """Resolves `inner` (a bare-name `CallExpr`, e.g. `inc()`, `f(x,
    y)`, OR a bracket-parametrized `CallExpr`, e.g. `test_tracing_add
    [enabled, 1](rhs)` -- test_tracing.mojo's own real shape, a nested
    async def with its OWN comptime bracket params, called via
    `create_task(...)` from the ENCLOSING (non-async, ordinary) code,
    not from inside another coroutine's `await` composition) against
    `self._async_api` / `self._async_closure_api`'s fallback, and if
    resolvable, actually CONSTRUCTS + SCHEDULES the task (`{base}_
    start(...)`, `mojo_async_schedule_ready(...)`) -- forwarding any
    captured free variable(s) as extra trailing arguments (a mutated
    one by ADDRESS, via a proper GIMPLE temp; `-fgimple` forbids a bare
    `&name` as an inline call-argument expression -- see `_gen_cpp_
    async_unit`'s `mut_capture_names` docstring for the by-reference-
    capture design this mirrors) and, for a bracket-parametrized
    callee, its bracket ARGUMENT EXPRESSIONS (lowered at THIS call
    site, not resolved by name -- a comptime bracket param is always
    passed BY VALUE, like an ordinary parameter, never boxed/mutable,
    since this codegen threads every nested async function's comptime
    bracket parameter through as an ordinary trailing runtime
    parameter regardless of its annotated type -- see the "Async
    closures/functions NESTED INSIDE A TOP-LEVEL FUNCTION" gen_module
    pass's own docstring).
    Returns `(handle, api)` on success, `None` if `inner` doesn't
    resolve to a known compiled async unit this way (the caller is
    responsible for its own fallback/refusal in that case -- this
    method never raises for an unresolvable `inner`, only for a
    genuinely malformed argument count mismatch it can't recover from
    by construction).

    Factored out of the free `create_task(...)`/`create_raising_task(
    ...)` call-site lowering (the ONLY call site until `TaskGroup.
    create_task(...)` needed the exact same resolve+construct+schedule
    sequence a second time) -- CLAUDE.md's consolidation principle:
    one shared implementation, not two independently-maintained
    copies of this same, fairly intricate sequence."""
    _bracket_vals: dict = {}
    if (isinstance(inner, gimple_ctypes.CallExpr) and isinstance(inner.func, gimple_ctypes.SubscriptExpr)
            and isinstance(inner.func.obj, gimple_ctypes.IdentExpr) and not getattr(inner, 'kwargs', None)):
        base_name = inner.func.obj.name
        api = gen._async_closure_api.get((gen.current_func_name, base_name))
        if api is None:
            return None
        idx = inner.func.index
        elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
        cp_names = api.get('comptime_params') or []
        if len(elems) != len(cp_names):
            # Arity mismatch against what this callee was actually
            # compiled with -- not this codegen's shape at all (a
            # genuinely malformed/unsupported call); let the caller's
            # own fallback/refusal handle it rather than guessing.
            return None
        for cp_name, cp_expr in zip(cp_names, elems):
            _bracket_vals[cp_name] = gen.lower_expr(cp_expr)
        base = api['base']
        arg_pairs = [gen.lower_expr(a) for a in inner.args]
    elif (isinstance(inner, gimple_ctypes.CallExpr) and isinstance(inner.func, gimple_ctypes.IdentExpr)
            and not getattr(inner, 'kwargs', None)):
        _acl_fallback = gen._async_closure_api.get((gen.current_func_name, inner.func.name))
        api = gen._async_api.get(inner.func.name) or _acl_fallback
        if api is None:
            return None
        base = api['base']
        arg_pairs = [gen.lower_expr(a) for a in inner.args]
    else:
        return None
    # `api['captures']` always stores each capture's PLAIN
    # (dereferenced) ctype, e.g. "int64_t" -- never the pointer form --
    # so this call site and `_gen_cpp_async_unit`'s own `extra_
    # captures` construction both derive the pointer type (`f"{ctype}
    # *"`) the same way, in exactly one place each, rather than one of
    # them baking "int64_t *" into the stored dict and the other
    # stripping it back off.
    _mut_names = api.get('mut_capture_names') or frozenset()
    for _cap_name, _cap_ctype in (api.get('captures') or []):
        if _cap_name in _bracket_vals:
            # A comptime bracket parameter (`enabled`/`lhs` in
            # `test_tracing_add[enabled, 1](rhs)`) -- its value comes
            # from THIS call site's own bracket argument expression
            # (already lowered above), never from a captured free
            # variable of the same name, and is always passed BY
            # VALUE (never boxed/mutable -- see this method's own
            # docstring).
            arg_pairs.append(_bracket_vals[_cap_name])
        elif _cap_name in _mut_names:
            _ptr_ctype = f"{_cap_ctype} *"
            _boxed = getattr(gen, '_boxed_mut_locals', {})
            _mutptr = getattr(gen, '_gimple_mut_ptr', {})
            if _cap_name in _boxed:
                # `_cap_name` is a heap-boxed local of the CURRENT
                # function (see GimpleGen._seed_mut_captured_local_
                # types's docstring for why boxing, not `&stack_
                # local`) -- it's already a pointer, forward it
                # directly.
                ptr_val = gen._new_val(_ptr_ctype, gen._cname(_cap_name))
                arg_pairs.append((_ptr_ctype, ptr_val))
            elif _cap_name in gen._captures and _cap_name in _mutptr:
                # This call site is itself inside a closure body that
                # ALREADY captured `_cap_name` by reference (gap (1)'s
                # transitive-capture-propagation fix in _scan_for_
                # closures: test_locks.mojo's `test_atomic()` calling
                # `inc()` without itself textually referencing `inc()`'s
                # own captured `lock`/`rawCounter`) -- forward the
                # already-preloaded local pointer (`_gimple_mut_ptr`,
                # see _gen_lifted_closure) instead of taking its
                # address again.
                ptr_val = gen._new_val(_ptr_ctype, _mutptr[_cap_name])
                arg_pairs.append((_ptr_ctype, ptr_val))
            elif _cap_name in gen.var_types:
                # A genuinely plain, never-address-taken-elsewhere
                # local/parameter of the CURRENT function -- safe to
                # take its address directly here (true when this call
                # site is compiled directly inside the SAME enclosing
                # function the callee's capture was resolved against).
                _addr = gen._new_val(_ptr_ctype, f"&{_cap_name}")
                arg_pairs.append((_ptr_ctype, _addr))
            else:
                # `self.var_types` holds every name actually in scope
                # for whichever function is CURRENTLY being generated
                # (params, locals, and a lifted closure's own threaded
                # captures) -- an honest compile-time refusal here (not
                # a raw, confusing gcc "undeclared identifier" error)
                # when `_cap_name` isn't one of them, rather than
                # emitting a reference to a name this function's own C
                # body was never given.
                raise RuntimeError(
                    "cannot compile module: create_task(...)'s callee "
                    f"mutably captures {_cap_name!r}, which isn't in "
                    "scope at this particular call site (calling a "
                    "mutable-capturing async closure from a DIFFERENT "
                    "nested closure than the one that declares the "
                    "captured variable is not yet supported) -- "
                    "falling back to interpreting this module from "
                    "source instead")
        else:
            arg_pairs.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=_cap_name)))
    handle = gen._call_expr('MojoAsync *', f"{base}_start", arg_pairs)
    gen._emit(f"  mojo_async_schedule_ready ({handle});")
    return handle, api


def _resolve_kwargs_for_known_async_call(gen, call) -> None:
    """Step I (create_task/Task/TaskGroup/RaisingTask project): if
    `call` is a CallExpr using ONLY keyword arguments (e.g.
    `conditional_raise(should_fail=False)` — test_raising_asyncrt.mojo's
    own real shape, in a DIRECT `await conditional_raise(should_fail=
    False)` composition, no create_task/create_raising_task involved at
    all) targeting a top-level async function this module has already
    compiled (self._supported_async holds the real FunctionDef, with
    its real parameter names/order), reorders the keyword arguments
    into positional order matching the callee's own declared parameter
    list, mutating `call.args`/`call.kwargs` in place — every other
    piece of this codegen's async-composition machinery
    (_is_async_call_to_known_fn, the `_cpp_expr` AwaitExpr composition
    call site) is positional-only, matching this whole file's call-
    lowering convention throughout (no keyword-arg support exists for
    ANY call shape here, not just this one), so this is the one place
    that bridges a real Mojo keyword-argument call site onto that
    positional-only machinery, rather than teaching every consumer
    about keyword arguments individually.

    Leaves `call` COMPLETELY UNTOUCHED (no mutation at all) if it
    can't be resolved this way (unknown/not-yet-compiled callee, a
    keyword name that doesn't match any of the callee's real
    parameters, a mix of positional and keyword arguments, ...) — the
    ordinary composition eligibility check
    (_is_async_call_to_known_fn) still correctly refuses a call whose
    kwargs survive unresolved, exactly like any other not-yet-
    supported shape; never guesses at an argument order."""
    if not (isinstance(call, gimple_ctypes.CallExpr) and isinstance(call.func, gimple_ctypes.IdentExpr)):
        return
    if not getattr(call, 'kwargs', None) or call.args:
        return
    callee_fn = gen._supported_async.get(call.func.name)
    if callee_fn is None:
        return
    kwmap = dict(call.kwargs)
    new_args = []
    for pn, _pt in (callee_fn.params or []):
        if pn in kwmap:
            new_args.append(kwmap.pop(pn))
        else:
            return  # a required positional has no matching kwarg -- leave untouched
    if kwmap:
        return  # a leftover, unrecognized kwarg name -- leave untouched
    call.args = new_args
    call.kwargs = []


def _normalize_await_kwargs(gen, body: list) -> None:
    """Step I: applies _resolve_kwargs_for_known_async_call to every
    `await <call>`'s target anywhere in `body` (any nesting depth —
    `if`/`try`/etc. bodies included, via _walk_ast) — a small, generic
    AST-normalization pass run BEFORE _async_quick_eligible sees the
    body (mirrors _inline_single_use_task_composition's identical
    "must run before eligibility, since the pre-rewrite shape looks
    ineligible" ordering requirement — see both call sites, right next
    to each other in gen_module/_compile_nested_async_functions)."""
    for nd in gimple_exprtypes._walk_ast(body):
        if isinstance(nd, gimple_ctypes.AwaitExpr):
            gen._resolve_kwargs_for_known_async_call(nd.value)


def _inline_single_use_task_composition(gen, body: list) -> list:
    """Step I (create_task/Task/TaskGroup/RaisingTask project): a
    narrow, DOCUMENTED source-level simplification for real Mojo's own
    Phase-3 `RaisingTask` idiom (see test_raising_asyncrt.mojo):

        var task = create_raising_task(add_async(10, 20))
        try:
            return await task^
        except:
            return -1

    This codegen has no general representation for a `Task`/
    `RaisingTask` HANDLE held as a local variable INSIDE a compiled
    coroutine's own body (unlike ordinary, non-coroutine code, where
    `create_task(...)`'s result is a real `MojoAsync *` value tracked
    in self._async_var_api — see _lower_call/_lower_method_call's
    `.wait()` handling) — building that (a whole new ctype category
    for the narrow, scalar-only shared _cpp_stmt/_cpp_expr emitter,
    which _gen_cpp_generator_unit/_gen_cpp_async_unit's own docstrings
    both describe as a deliberately scalar-only whitelist) is a much
    larger, riskier addition than this one specific, very common
    idiom needs.

    Instead: when `var X = create_task(f(...))` / `create_raising_
    task(f(...))` is followed, anywhere later IN THIS SAME BODY, by
    EXACTLY ONE OTHER reference to `X` at all, and that one reference
    is `await X` (`await X^` parses identically — the `^` transfer
    sigil is stripped by the tokenizer), this is semantically IDENTICAL
    to composing `await f(...)` directly (Step D's existing, already-
    verified async-awaits-async composition) — creating a task and
    immediately awaiting it once, with the handle never read, passed,
    or awaited again anywhere else, cannot observably differ from
    inlining the two operations into one `await`. Rewrites the AST IN
    PLACE (mutates the matched AwaitExpr's own `.value` field from the
    bare variable reference to the original inner call expression) and
    drops the now-dead `var X = create_task(...)` declaration
    entirely, so the shared emitter never even sees either
    `create_task`/`create_raising_task` or a bare-variable `await` —
    it only ever sees the ordinary, already-supported `await
    f(...)` shape.

    If the single-use condition does NOT hold (the handle is read,
    reassigned, awaited more than once, or awaited zero times), this
    is left COMPLETELY UNTOUCHED — the un-rewritten `await X` then
    correctly fails _is_async_call_to_known_fn's "target must be a
    CallExpr" check, making the whole function ineligible and falling
    back to the honest whole-module refusal, exactly like any other
    not-yet-supported shape. This is never a silent-miscompilation
    risk: either the narrow, provably-equivalent single-use shape is
    detected and inlined, or nothing here changes at all.

    A keyword-argument inner call (e.g. `conditional_raise(should_fail
    =False)`) is resolved to positional order using the callee's real
    FunctionDef.params (self._supported_async holds the original
    FunctionDef for every top-level async function already compiled by
    the time this runs — see gen_module's pass ordering) — if the
    callee isn't resolvable this way (e.g. a nested callee, or a
    parameter-name mismatch), the kwargs are left as-is, which simply
    makes the inlined call ineligible at the ordinary
    _is_async_call_to_known_fn check (kwargs are refused there) rather
    than guessing at an argument order.

    Called on every async function's body (top-level and nested)
    BEFORE both `_async_quick_eligible` and `_gen_cpp_async_unit` see
    it (see both call sites in `_compile_nested_async_functions` and
    the top-level async pre-pass) — idempotent (a second call is a
    no-op, since the `var X = create_task(...)` statement this matches
    no longer exists after the first rewrite), so re-running it
    defensively at each call site is always safe."""
    result = []
    n = len(body)
    i = 0
    while i < n:
        s = body[i]
        if (isinstance(s, gimple_ctypes.VarDecl) and isinstance(s.value, gimple_ctypes.CallExpr)
                and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                and s.value.func.name in ('create_task', 'create_raising_task')
                and len(s.value.args) == 1 and not getattr(s.value, 'kwargs', None)):
            inner = s.value.args[0]
            # Step I: the inner call's callee may be a bare name
            # (`create_task(f(...))`) OR a bracket call to a sibling
            # comptime-bracket-parametrized nested async def
            # (`create_task(return_value[1]())`, test_asyncrt.mojo's
            # `run_as_group` shape) -- the single-use-handle inlining
            # reasoning above is identical either way (this rewrite
            # only ever moves `inner` verbatim into the matched `await`
            # site; it never inspects `inner.func`'s own shape beyond
            # this check), so both are accepted here. Whether the
            # inlined bracket call itself is actually composable is
            # decided later, by `_async_quick_eligible`/`_cpp_expr`'s
            # AwaitExpr case -- not duplicated here.
            if isinstance(inner, gimple_ctypes.CallExpr) and (
                    isinstance(inner.func, gimple_ctypes.IdentExpr)
                    or (isinstance(inner.func, gimple_ctypes.SubscriptExpr)
                        and isinstance(inner.func.obj, gimple_ctypes.IdentExpr))):
                varname = s.name
                rest = body[i + 1:]
                # `await X` and `await X^` (the `^` transfer sigil —
                # real Mojo's own idiom for `RaisingTask.wait()`/
                # `__await__(deinit self)`'s ownership-transfer
                # requirement, e.g. `return await task^`) must both be
                # recognized here: `X^` parses to
                # `UnaryOp(op='^', operand=IdentExpr(X))`, NOT a bare
                # IdentExpr (confirmed via the parser directly — this
                # is NOT stripped away at the tokenizer level the way
                # some other `^` contexts are). Both shapes reduce to
                # the same rewrite (the `^`'s ownership-transfer has no
                # separate representation to preserve once the
                # `create_task`/`await` pair collapses into one direct
                # `await <call>` — there is no handle left to
                # transfer ownership of).
                def _var_ref_name(node):
                    if isinstance(node, gimple_ctypes.IdentExpr):
                        return node.name
                    if (isinstance(node, gimple_ctypes.UnaryOp) and node.op == '^'
                            and isinstance(node.operand, gimple_ctypes.IdentExpr)):
                        return node.operand.name
                    return None
                all_refs = [nd for stmt in rest for nd in gimple_exprtypes._walk_ast(stmt)
                            if isinstance(nd, gimple_ctypes.IdentExpr) and nd.name == varname]
                await_refs = [nd for stmt in rest for nd in gimple_exprtypes._walk_ast(stmt)
                              if isinstance(nd, gimple_ctypes.AwaitExpr)
                              and _var_ref_name(nd.value) == varname]
                if len(all_refs) == 1 and len(await_refs) == 1:
                    # Reuses the SAME kwarg-to-positional resolution
                    # _normalize_await_kwargs applies to every OTHER
                    # `await <call>` in this module (see
                    # _resolve_kwargs_for_known_async_call's docstring)
                    # — not a second, parallel implementation of the
                    # same logic.
                    gen._resolve_kwargs_for_known_async_call(inner)
                    await_refs[0].value = inner
                    i += 1
                    continue
        result.append(s)
        i += 1
    return result


def _compile_nested_async_functions(gen, outer_fn: gimple_ctypes.FunctionDef,
                                     async_fns: dict) -> None:
    """Step I (create_task/Task/TaskGroup/RaisingTask project): compile
    any `async def` nested INSIDE an ordinary top-level function's own
    body (e.g. a local `@parameter async def wrapper(): ...` helper
    private to one `def test_xxx():`) via the exact same
    _gen_cpp_async_unit path a top-level `async def` already uses.

    gen_module's own `_walk_ast`-based scan (building `async_fns`)
    already DISCOVERS these, but the original compile-ATTEMPT loop only
    ever iterated top-level `stmts` — a nested async def was therefore
    always left uncompiled, silently tripping the final "unhandled
    async function(s)" whole-module refusal for any module containing
    one at all (which is every real test file `create_task`/`Task`
    needs, since real Mojo's own idiom is `@parameter async def
    wrapper(): ...` scoped inside the test function that uses it, never
    a bare top-level `async def`).

    Called once per ordinary top-level FunctionDef, from gen_module's
    own pre-pass (BEFORE the final "any remaining async_fns is an
    honest whole-module refusal" check — see that check's own
    docstring) — so this must itself decide eligibility/compile right
    here rather than deferring it, and must pop every id it resolves
    out of `async_fns` (the same dict gen_module's own top-level async
    loop already pops into), exactly mirroring that loop's own
    contract.

    Registers each successfully-compiled nested function into
    self._nested_async_api under the QUALIFIED key
    `f"{enclosing_name}::{nested_name}"` — never into self._async_api
    directly (see self._nested_async_api's own docstring for why: two
    different enclosing functions may each define their own same-named
    nested helper, and every compiled async cpp fragment in this module
    lands in ONE shared .cpp translation unit, so both the dict key AND
    the underlying C++ symbol names — see _gen_cpp_async_unit's
    `scope_prefix` — must stay qualified/unique). gen_module's main
    per-statement loop is responsible for temporarily copying the
    entries belonging to whichever function it's about to compile into
    self._async_api under their bare names (a scoped push/pop) right
    around that one `gen_func` call.

    An unsupported nested async def is silently left uncompiled here
    (not an error) — a caller that actually references it (e.g.
    `create_task(it())`) then hits that call site's own honest,
    already-existing refusal instead, exactly like any other
    not-yet-supported shape; nothing here ever emits a dangling/
    unresolved reference.

    Step I (mutable-capture follow-on): also computes this nested
    function's own captured free variable(s) via `_compute_nested_
    closure_captures`, using `_enclosing_scope_with_locals(outer_fn)`
    (params AND top-level local `var`s of `outer_fn` -- see that
    method's own docstring for why locals matter here: test_locks.
    mojo's `inc()` captures `lock`/`rawCounter`/`counter`, all locals
    of `test_basic_lock`, not parameters). A captured name `inc`'s own
    body REASSIGNS (`_mutated_free_names`) is threaded through as a
    by-reference (pointer) parameter instead of the by-value copy
    every other capture already used; see `_gen_cpp_async_unit`'s
    `mut_capture_names` docstring."""
    enclosing_name = outer_fn.name
    body = outer_fn.body
    outer_scope = gen._enclosing_scope_with_locals(outer_fn)
    for n in gimple_exprtypes._walk_ast(body):
        if not (isinstance(n, gimple_ctypes.FunctionDef) and n.is_async and not n.is_generator):
            continue
        if id(n) not in async_fns:
            # Already handled (e.g. also reachable as a top-level
            # statement, or visited by an earlier call to this method
            # for a different enclosing function that happens to share
            # a sub-body reference) — nothing left to do.
            continue
        qualified = f"{enclosing_name}::{n.name}"
        # See _inline_single_use_task_composition's/_normalize_await_
        # kwargs's own docstrings — both must run BEFORE the
        # eligibility check below: a bare `await task` (pre-rewrite)
        # or a keyword-argument await target (pre-normalization) would
        # otherwise make an eligible function look ineligible.
        _nb = gen._inline_single_use_task_composition(gen._get_fn_body(n))
        gen._normalize_await_kwargs(_nb)
        gen._set_fn_body(n, _nb)
        # A nested async def with its OWN comptime bracket parameter(s)
        # (test_asyncrt.mojo's/test_nested_async_generic.py's exact
        # shape: `async def test_asyncrt_add[lhs: Int](rhs: Int) ->
        # Int:`) is deliberately left untouched by THIS pass and instead
        # handled by gen_module's separate, dedicated "Async closures/
        # functions NESTED INSIDE A TOP-LEVEL FUNCTION" pass (registered
        # into self._async_closure_api, keyed by (enclosing_name,
        # n.name), with comptime bracket params threaded through as
        # ordinary trailing parameters — see that pass's own comment
        # and _compute_nested_closure_captures/_gen_cpp_async_unit's
        # `extra_captures`). This method's own _gen_cpp_async_unit call
        # only ever inspects `n.params` (ordinary runtime parameters),
        # never `n.comptime_params` — so calling it directly here for a
        # comptime-bracket-parametrized nested def would silently
        # compile a WRONG unit that simply drops the bracket
        # parameter(s) entirely (a real, hand-verified regression: this
        # exact gap let this pass claim `test_asyncrt_add` before the
        # dedicated pass ever got a chance, registering an incomplete
        # unit under the wrong dict and breaking the comptime-aware
        # asyncio.run(...) call-site lookup). Explicitly deferring here
        # (rather than relying on eligibility/exception behavior to
        # catch it) keeps the two passes' scopes genuinely disjoint:
        # this one owns "no comptime params", the other owns "has
        # comptime params" — for the identical nested-in-ordinary-
        # top-level-function parent shape.
        if n.comptime_params:
            continue
        _captures = gen._compute_nested_closure_captures(n, outer_scope)
        _mut_names = gen._mutated_free_names(n, {_cn for _cn, _ in _captures})
        eligible = gimple_exprtypes._async_quick_eligible(n, frozenset(gen._async_api.keys()))
        if eligible:
            try:
                cpp_text, value_ctype, base, param_ctypes = \
                    gen._gen_cpp_async_unit(n, extra_captures=_captures,
                                             scope_prefix=enclosing_name,
                                             enclosing_scope=enclosing_name,
                                             mut_capture_names=_mut_names)
            except gimple_exprtypes._UnsupportedGeneratorShape as e:
                gimple_ctypes._debug_note(f'nested async function {n.name!r} (inside '
                            f'{enclosing_name!r}) not eligible for C++ '
                            'coroutine path, falling back to honest '
                            'refusal', e)
                eligible = False
        if not eligible:
            # DELIBERATE, DOCUMENTED SIMPLIFICATION — see _lower_call's
            # create_task/create_raising_task stub-branch docstring for
            # the full rationale (a genuinely dead, upstream-
            # acknowledged-broken helper like test_raising_asyncrt.
            # mojo's `test_raising_async_error_message_via_wrapper`
            # otherwise hard-refuses the WHOLE module over one
            # provably-unreachable function). Narrowly scoped: only
            # skip adding this failure to the module-wide fatal list
            # (`async_fns` stays untouched, i.e. still counts as
            # "unhandled", UNLESS this exact narrow shape holds) when
            # `body` (this enclosing function's OWN remaining
            # statements) references `n.name` EXACTLY ONCE, and that
            # one reference is a bare `create_task(n.name())`/
            # `create_raising_task(n.name())` call — the EXACT shape
            # _lower_call's stub branch already handles gracefully at
            # its call site. Any OTHER reference shape (a bare call,
            # `await`, passed as a value, referenced more than once,
            # ...) leaves `id(n)` in `async_fns` completely unchanged,
            # so the existing whole-module fatal check still fires
            # exactly as it always has for every other genuinely
            # unhandled async function — this is not a general loosening
            # of that safety net, only a documented carve-out for the
            # one specific shape this codegen now has a real (if
            # degraded) answer for.
            refs = [nd for stmt in body for nd in gimple_exprtypes._walk_ast(stmt)
                    if isinstance(nd, gimple_ctypes.IdentExpr) and nd.name == n.name]
            task_refs = [nd for stmt in body for nd in gimple_exprtypes._walk_ast(stmt)
                         if isinstance(nd, gimple_ctypes.CallExpr) and isinstance(nd.func, gimple_ctypes.IdentExpr)
                         and nd.func.name in ('create_task', 'create_raising_task')
                         and len(nd.args) == 1 and not getattr(nd, 'kwargs', None)
                         and isinstance(nd.args[0], gimple_ctypes.CallExpr)
                         and isinstance(nd.args[0].func, gimple_ctypes.IdentExpr)
                         and nd.args[0].func.name == n.name and not nd.args[0].args
                         and not getattr(nd.args[0], 'kwargs', None)]
            if len(refs) == 1 and len(task_refs) == 1:
                async_fns.pop(id(n), None)
            continue
        gen._nested_async_api[qualified] = {
            'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            'nested_name': n.name, 'captures': _captures,
            'mut_capture_names': _mut_names,
        }
        gen.func_param_types[f"{base}_start"] = param_ctypes
        gen._generator_cpp_units.append(cpp_text)
        async_fns.pop(id(n), None)


def _gen_cpp_async_generator_unit(gen, fn: gimple_ctypes.FunctionDef) -> tuple[str, str, str, list]:
    """Final step of the compiled-path async/await codegen project:
    `async def f(): ... yield ... ...` -- an async GENERATOR (is_async
    AND is_generator both true). A THIRD, distinct promise type, not a
    reuse of either `_gen_cpp_generator_unit`'s or `_gen_cpp_async_unit`'s
    -- it needs customization points from BOTH (yield_value(), from the
    generator side; a continuation field plus a suspend-and-wake
    final_suspend(), from the async side, so an awaiting caller composes
    exactly like Step D's async-awaits-async).

    GCC-15 risk (see _gen_cpp_generator_unit's `unhandled_exception()`
    docstring for Milestone D's original finding, and
    _gen_cpp_async_unit's docstring for how Step B/D each re-confirmed
    their own shape's safety): that bug's confirmed trigger is a
    coroutine with real FORMAL PARAMETERS plus an added/extra promise
    field -- corrupting the frame layout so a later parameter's value
    bled into an unrelated promise field. This step's promise combines
    MORE fields than either predecessor (current_value + continuation +
    exc + exc_pending together) -- verified SAFE via a fresh, minimal,
    Mojo-independent hand-written repro (yield_value + continuation
    field + a 2- and a 3-parameter coroutine, both compiled and RUN, at
    -O0 and -O2, on this project's actual g++-mp-15) before this method
    was written at all, mirroring Step D's own precedent exactly --
    every value came back correct, no corruption reproduced even with
    real parameters. Scope is kept parameter-less anyway (see
    `_async_gen_quick_eligible`), matching every other step in this
    project's own "narrowest shape first" pattern (Milestone B and Step
    B both started at zero parameters too) -- not because the repro
    found trouble, but because there is no need to widen scope beyond
    this step's one target shape (`async for x in f(): ...`) to close
    out the project, and a real compiled generator with parameters
    remains available via the plain (non-async) generator path for
    anyone who needs it.

    Consumption protocol (real Python: an async generator is consumed
    via `async for`, never awaited directly -- `__anext__()` is what's
    awaitable under the hood). Rather than inventing a fourth extern
    "C" calling convention (a `_anext_start`/`_anext_resume`/
    `_anext_is_done`/`_anext_value` quadruplet), this reuses Step D's
    own established pattern EXACTLY: composition only ever happens
    between two coroutines in the SAME .cpp translation unit (every
    function's own `_generator_cpp_units` fragment is concatenated into
    one .cpp file -- see gen_module), so `async for` is lowered
    (GimpleGen._cpp_stmt's own ForStmt case) straight to a `co_await` on
    a dedicated `<base>_AnextAwaiter`, constructed directly from
    `{impl}().h` exactly like Step D's own `<base>_Awaiter` is
    constructed from an inner async call -- no `extern "C"` boundary,
    no new driving mechanism. `<base>_AnextAwaiter::await_suspend`
    registers the awaiting coroutine (the `async for`'s own enclosing
    function) as this generator's continuation and pushes the generator
    onto Step A's ready queue, exactly like `<base>_Awaiter`; the
    generator's OWN yield_value() and final_suspend() BOTH return the
    SAME `<base>_WakeAwaiter` (consolidated -- "suspend, and if
    something is waiting on us, wake it via the ready queue" is
    identical logic whether the coroutine suspended because it yielded
    a value or because it's genuinely done), so the awaiting coroutine
    gets rescheduled at every yield point exactly as it does at
    completion. `<base>_AnextAwaiter::await_resume` reads `h.done()` to
    tell "yielded another value" (false) from "exhausted" (true,
    StopAsyncIteration-equivalent) apart -- exactly the same
    `h.done()` reads-false-at-a-yield-point/true-at-final-suspend
    distinction the PLAIN generator's `_resume()` already relies on,
    reused here rather than a new signal.

    Exceptions: staged on the promise's own exc/exc_pending fields
    (Step E's exact representation, not Milestone D's straight-to-
    globals one -- for the identical reason Step E chose it: a caller
    awaiting this generator's next value must see a real, catchable
    C++ exception in its OWN body, not silently-already-translated
    global state). `<base>_AnextAwaiter::await_resume` rethrows it into
    the awaiting coroutine's body exactly like `<base>_Awaiter`'s own
    await_resume does for plain async-awaits-async composition -- no
    new exception mechanism, straight reuse.

    Returns (cpp_text, value_ctype, base, param_ctypes) mirroring both
    predecessors' return shape (param_ctypes always `[]` this step)."""
    # See _gen_cpp_generator_unit's identical reset for why this must
    # happen up front, before any early exception/refusal.
    gen._cpp_last_tuple_slot_ctypes = None
    param_ctypes: list[tuple[str, str]] = []
    for pn, pt in (fn.params or []):
        if pn.startswith('*'):
            raise gimple_exprtypes._UnsupportedAsyncShape(
                f"{fn.name}: *args/**kwargs parameters not supported "
                "for compiled async generators")
        ctype = gen._param_ctype(pn, pt, fn)
        # See the identical struct-pointer-acceptance note in
        # _gen_cpp_generator_unit — same allow-list, same reasoning,
        # same shared _cpp_expr body-side machinery.
        _is_struct_ptr = (ctype.endswith(' *')
                          and ctype[:-2] in gen.struct_field_types)
        if _is_struct_ptr:
            gen._cpp_param_struct_names.add(ctype[:-2])
        if ctype not in ('int64_t', 'double', '_Bool', 'char *', 'MojoList *',
                         'MojoDict *', 'MojoSet *') and not _is_struct_ptr:
            raise gimple_exprtypes._UnsupportedAsyncShape(
                f"{fn.name}: async generator parameter '{pn}' has "
                f"unsupported type {ctype!r} (only int64_t/"
                "double/_Bool/char*/<known struct>* parameters are "
                "supported)")
        param_ctypes.append((pn, ctype))
    base = f"_mojoasyncgen_{gimple_ctypes._safe_name(fn.name)}"
    declared: dict[str, str] = {pn: ct for pn, ct in param_ctypes}
    # Reset self._cpp_kw_param_renames for this unit too (see its own
    # docstring) — this method's own signature emission doesn't
    # currently reuse keyword-collidable parameter names in its
    # extern "C" boundary the way _gen_cpp_generator_unit/_gen_cpp_
    # async_unit's do, but resetting here still matters: without it,
    # a PRIOR sibling unit's own renames (e.g. some earlier generator
    # method's `default` parameter) could otherwise leak into this
    # one's body lowering via _cpp_expr's shared IdentExpr fallback.
    gen._cpp_kw_param_renames = {}
    gen._cpp_gen_self_struct = None
    gen._cpp_gen_self_fields = None
    gen._cpp_emit_kind = 'async_gen'
    # See _gen_cpp_generator_unit's identical pre-body-emission
    # tuple-slot arity pass for the full rationale — same stash, same
    # `finally` clearing, reused verbatim for the async-generator case.
    _pre_ok, _pre_slots = gimple_exprtypes._generator_tuple_yield_slot_ctypes(
        fn, declared, None, gen._async_api,
        generator_api=gen._generator_api)
    gen._cpp_pending_tuple_slots = list(_pre_slots) if (_pre_ok and _pre_slots) else None
    try:
        body_lines: list[str] = []
        for s in fn.body:
            body_lines.extend(gen._cpp_stmt(s, declared, '    '))
        # Struct-pointer-yield support — mirrors _gen_cpp_generator_
        # unit's/_gen_cpp_async_unit's identical widening (see their own
        # comments): async generator methods aren't struct-scoped here
        # either (self_fields=None, same as _gen_cpp_async_unit), so
        # only the struct-typed-parameter + struct-method-call-chain
        # shape applies.
        value_ctype = gimple_exprtypes._generator_yield_ctype(
            fn, declared, generator_api=gen._generator_api,
            self_fields=None, async_api=gen._async_api,
            known_structs=frozenset(gen.struct_field_types.keys()),
            method_return_types=gen.func_return_types)
        # See _gen_cpp_generator_unit's identical companion call for
        # the full rationale — same tuple-yield slot-type resolution,
        # reused verbatim for the async-generator (`async for`) case.
        has_tuple_yield, tuple_slot_ctypes = gimple_exprtypes._generator_tuple_yield_slot_ctypes(
            fn, declared, None, gen._async_api,
            generator_api=gen._generator_api)
        if has_tuple_yield and tuple_slot_ctypes is None:
            value_ctype = None
        gen._cpp_last_tuple_slot_ctypes = tuple_slot_ctypes if has_tuple_yield else None
    finally:
        gen._cpp_emit_kind = 'generator'
        gen._cpp_gen_self_struct = None
        gen._cpp_gen_self_fields = None
    if value_ctype is None:
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"{fn.name}: every `yield <value>` must carry a scalar "
            "value (int64_t/double/_Bool), and all of them must agree "
            "on one consistent type")
    if (value_ctype.endswith(' *') and value_ctype not in ('MojoList *', 'MojoDict *', 'MojoSet *')
            and value_ctype[:-2] in gen.struct_field_types):
        gen._cpp_value_struct_names.add(value_ctype[:-2])

    promise, handle_t, task, impl = (
        f"{base}_promise", f"{base}_handle", f"{base}_Task", f"{base}_impl")
    wake_awaiter, anext_awaiter = f"{base}_WakeAwaiter", f"{base}_AnextAwaiter"
    cpp_value_ctype = gimple_exprtypes._c_to_cpp_scalar_type(value_ctype)
    lines = [
        f"struct {promise};",
        f"using {handle_t} = std::coroutine_handle<{promise}>;",
        f"struct {task} {{",
        f"    using promise_type = {promise};",
        f"    {handle_t} h;",
        f"}};",
        # Shared by both yield_value()'s return and final_suspend()'s
        # return -- see this method's own docstring for why one type
        # correctly serves both suspend points. Forward-declared here,
        # defined out-of-line below {promise} (needs {promise} to be a
        # complete type for `h.promise().continuation`) -- the same
        # split _gen_cpp_async_unit's own {final_awaiter} already uses,
        # proven safe by this project's GCC-15 repro precedent.
        f"struct {wake_awaiter} {{",
        f"    bool await_ready() noexcept {{ return false; }}",
        f"    std::coroutine_handle<> await_suspend({handle_t} h) noexcept;",
        f"    void await_resume() noexcept {{}}",
        f"}};",
        f"struct {promise} {{",
        f"    {cpp_value_ctype} current_value{{}};",
        f"    _MojoCppExc exc{{}};",
        f"    bool exc_pending{{}};",
        f"    std::coroutine_handle<> continuation{{}};",
        f"    {task} get_return_object() {{ return {task}{{ {handle_t}::from_promise(*this) }}; }}",
        f"    std::suspend_always initial_suspend() noexcept {{ return {{}}; }}",
        f"    {wake_awaiter} final_suspend() noexcept {{ return {{}}; }}",
        f"    void unhandled_exception() {{",
        f"        try {{ std::rethrow_exception(std::current_exception()); }}",
        f"        catch (_MojoCppExc &__e) {{ exc = __e; exc_pending = true; }}",
        f"        catch (...) {{",
        f"            exc = _MojoCppExc{{ (int64_t)0, nullptr, nullptr }};",
        f"            exc_pending = true;",
        f"        }}",
        f"    }}",
        f"    {wake_awaiter} yield_value({cpp_value_ctype} v) {{ current_value = v; return {{}}; }}",
        f"    void return_void() {{}}",
        f"}};",
        f"inline std::coroutine_handle<> {wake_awaiter}::await_suspend({handle_t} h) noexcept {{",
        f"    std::coroutine_handle<> cont = h.promise().continuation;",
        f"    if (cont) mojo_async_schedule_ready(cont.address());",
        f"    return std::noop_coroutine();",
        f"}}",
        f"static {task} {impl} ({', '.join(f'{gimple_exprtypes._c_to_cpp_scalar_type(ct)} {pn}' for pn, ct in param_ctypes) or 'void'}) {{",
        *body_lines,
        f"    co_return;",
        f"}}",
        # `async for` (GimpleGen._cpp_stmt's own ForStmt case) is this
        # generator's ONLY consumer in this step's scope, and it always
        # constructs `{impl}()` directly (same-translation-unit
        # composition, exactly like `_gen_cpp_async_unit`'s own
        # `_Awaiter`) -- so no `extern "C"` boundary is needed at all
        # for this step's one target shape. `await_suspend` registers
        # the awaiting coroutine as this generator's continuation and
        # schedules it, exactly like `_Awaiter`; `await_resume` reads
        # `h.done()` to tell "yielded" from "exhausted" apart (see
        # `_gen_cpp_generator_unit`'s own `_resume()` for the identical
        # `h.done()` convention on the plain-generator side), and
        # rethrows a staged exception into the awaiting body exactly
        # like `_Awaiter::await_resume` does for composition.
        f"struct {anext_awaiter} {{",
        f"    {handle_t} callee_h;",
        f"    bool await_ready() noexcept {{ return false; }}",
        f"    void await_suspend(std::coroutine_handle<> caller_h) noexcept {{",
        f"        callee_h.promise().continuation = caller_h;",
        f"        mojo_async_schedule_ready(callee_h.address());",
        f"    }}",
        f"    bool await_resume() {{",
        f"        if (callee_h.promise().exc_pending) {{",
        f"            _MojoCppExc __e = callee_h.promise().exc;",
        f"            callee_h.destroy();",
        f"            throw __e;",
        f"        }}",
        f"        return !callee_h.done();",
        f"    }}",
        f"}};",
    ]
    return '\n'.join(lines), value_ctype, base, param_ctypes
