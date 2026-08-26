"""Expression lowering for the GIMPLE backend.

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

def _lower_strided(gen, node, store: bool):
    """Scalar (SIMD-width-1) lowering of the strided_load/strided_store
    intrinsics: a plain load/store of the pointer's scalar element. Consistent
    with the codegen's existing SIMD-to-scalar erasure."""
    if store:
        # strided_store(value, ptr, stride, mask)
        _, vv = gen.lower_expr(node.args[0])
        pt, pv = gen.lower_expr(node.args[1])
        for a in node.args[2:]:
            gen.lower_expr(a)
        dp = gen._strided_data_ptr(pt, pv)
        gen._emit(f"  *{dp} = {vv};")
        return 'int', gen._new_val('int', '0')
    # strided_load(ptr, stride, mask)
    pt, pv = gen.lower_expr(node.args[0])
    for a in node.args[1:]:
        gen.lower_expr(a)
    dp = gen._strided_data_ptr(pt, pv)
    return 'int64_t', gen._new_val('int64_t', f"*{dp}")


def lower_expr(gen, node) -> tuple[str, str]:
    """Return (ctype, simple_rvalue). May emit temp assignments."""
    # Static dispatch: an explicit isinstance chain (one branch per
    # expression kind), NOT getattr(self, name)(node) on _EXPR_DISPATCH.
    # getattr's dynamic indirect call compiles to a no-op when this file
    # is itself compiled into the mojoc binary, silently lowering every
    # expression to the zero fallback; the isinstance chain compiles to
    # plain branch checks (the same pattern _cpp_stmt uses successfully).
    if isinstance(node, gimple_ctypes.IntLiteral):
        return gen._lower_IntLiteral(node)
    elif isinstance(node, gimple_ctypes.FloatLiteral):
        return gen._lower_FloatLiteral(node)
    elif isinstance(node, gimple_ctypes.BoolLiteral):
        return gen._lower_BoolLiteral(node)
    elif isinstance(node, gimple_ctypes.EllipsisLiteral):
        return gen._lower_EllipsisLiteral(node)
    elif isinstance(node, gimple_ctypes.StringLiteral):
        return gen._lower_StringLiteral(node)
    elif isinstance(node, gimple_ctypes.IdentExpr):
        return gen._lower_IdentExpr(node)
    elif isinstance(node, gimple_ctypes.WalrusExpr):
        return gen._lower_WalrusExpr(node)
    elif isinstance(node, gimple_ctypes.BinaryOp):
        return gen._lower_binary(node)
    elif isinstance(node, gimple_ctypes.CompareChain):
        return gen._lower_compare_chain(node)
    elif isinstance(node, gimple_ctypes.UnaryOp):
        return gen._lower_UnaryOp(node)
    elif isinstance(node, gimple_ctypes.CallExpr):
        return gen._lower_call(node)
    elif isinstance(node, gimple_ctypes.TernaryExpr):
        return gen._lower_TernaryExpr(node)
    elif isinstance(node, gimple_ctypes.MemberExpr):
        return gen._lower_MemberExpr(node)
    elif isinstance(node, gimple_ctypes.SubscriptExpr):
        return gen._lower_subscript(node)
    elif isinstance(node, gimple_ctypes.SliceExpr):
        return gen._lower_slice(node)
    elif isinstance(node, gimple_ctypes.ListExpr):
        return gen._lower_list_literal(node)
    elif isinstance(node, gimple_ctypes.DictExpr):
        return gen._lower_dict_literal(node)
    elif isinstance(node, gimple_ctypes.SetExpr):
        return gen._lower_set_literal(node)
    elif isinstance(node, gimple_ctypes.TupleExpr):
        return gen._lower_tuple_literal(node)
    elif isinstance(node, gimple_ctypes.Comprehension):
        return gen._lower_comprehension(node)
    elif isinstance(node, gimple_ctypes.LambdaExpr):
        return gen._lower_LambdaExpr(node)
    elif isinstance(node, gimple_ctypes.TstringLiteral):
        return gen._lower_TstringLiteral(node)
    gimple_ctypes._debug_note('unknown expression lowered to 0', type(node).__name__)
    gen._emit(f"  /* TODO: unknown expr {type(node).__name__} */")
    t = gen._new_val('int', "0")
    return 'int', t


def _lower_IntLiteral(gen, node) -> tuple[str, str]:
    # A literal beyond INT64_MAX (e.g. UInt64.MAX == 2**64-1, used as a
    # mask) doesn't fit any signed C integer type; GCC silently treats
    # the bare decimal as unsigned but still warns ("integer constant is
    # so large that it is unsigned"). An explicit ULL suffix says what we
    # mean and silences the warning without changing the value.
    if node.value > 0x7FFFFFFFFFFFFFFF:
        # Also widen the type tag to uint64_t: a plain 'int' temp holding
        # this literal would itself overflow (e.g. UInt64.MAX truncating
        # to -1) before any later cast gets a chance to widen it.
        return 'uint64_t', f'{node.value}ULL'
    return 'int', str(node.value)


def _lower_FloatLiteral(gen, node) -> tuple[str, str]:
    s = repr(node.value)
    if '.' not in s and 'e' not in s.lower():
        s += '.0'
    return 'double', s


def _lower_BoolLiteral(gen, node) -> tuple[str, str]:
    return 'int', ('1' if node.value else '0')


def _lower_EllipsisLiteral(gen, node) -> tuple[str, str]:
    t = gen._new_temp('int')
    gen._emit(f"  {t} = 0;  /* ... */")
    return 'int', t


def _lower_StringLiteral(gen, node):
    val = node.value
    # Backtick-quoted Mojo identifiers tokenize as STRING — treat as variable reference
    if val.startswith('`') and val.endswith('`') and len(val) > 2:
        return gen._lower_IdentExpr(gimple_ctypes.IdentExpr(name=val))
    val, is_fstring = gen._decode_str_literal_text(val)
    if not is_fstring:
        escaped = gimple_ctypes._c_escape(val)
        # GIMPLE: char[] arrays can't be implicitly assigned to char* locals.
        # Register in the module-level string pool (emitted as C global char arrays)
        # and emit an explicit (char*) cast so callers always get a plain char* temp.
        sname = gen._intern_string(escaped)
        temp = gen._new_val('char *', f'{sname}')
        return 'char *', temp
    # F-string: for now, just extract literal parts and return as plain string
    # Full f-string formatting with snprintf requires static buffers, which aren't allowed in __GIMPLE
    parts = gen._parse_fstring_parts(val)
    if not parts or all(k == 'lit' for k, _v, _s, _c in parts):
        plain = ''.join(v for k, v, _s, _c in parts)
        escaped = gimple_ctypes._c_escape(plain)
        temp = gen._new_val('char *', f'{gen._intern_string(escaped)}')
        return 'char *', temp

    # For f-strings with expressions: build a concatenation of all parts
    # Lower each expression part and concatenate via mojo_str_cat
    acc_val = None
    for kind, text, _spec, _conv in parts:
        if kind == 'lit':
            if not text:
                continue
            esc = gimple_ctypes._c_escape(text)
            part_t = gen._new_val('char *', f'{gen._intern_string(esc)}')
            part_val = part_t
        else:
            # Expression: try to evaluate and convert to char*
            try:
                from mojo_compiler import Parser as _P, py_tokenize as _tok
                expr_node = _P(_tok(text))._parse_expr(0)
                # This is parsed fresh from raw source text at codegen
                # time (unlike the rest of the module), so it never went
                # through ast_rewriter.rewrite() — do that here, or e.g.
                # f"...{result.stderr}..." falls straight to
                # mojo_obj_getattr's stub instead of the real rewrite.
                expr_node = gimple_ctypes.ast_rewriter.rewrite_node(expr_node)
                et, ev = gen.lower_expr(expr_node)
                if _conv == 'r':
                    # repr() the ORIGINAL typed value, not the stringified
                    # one — _repr_value(et, ev) expects the raw value.
                    part_val = gen._repr_value(et, ev)
                else:
                    part_val = gen._stringify_value(et, ev)
                if _spec:
                    part_val = gen._apply_fstring_spec(part_val, _spec)
            except Exception as e:
                # The interpolation can't be lowered.  Dropping it would
                # silently corrupt the program's output, so warn and keep
                # the source text visible in the produced string instead.
                fname = gen._current_filename or '<unknown>'
                print(f"{fname}: warning: f-string interpolation "
                      f"'{{{text}}}' could not be compiled; emitting it "
                      f"as literal text ({type(e).__name__}: {e})",
                      file=gimple_ctypes.sys.stderr)
                esc = gimple_ctypes._c_escape('{' + text + '}')
                part_val = gen._new_val('char *', f'{gen._intern_string(esc)}')
        if acc_val is None:
            acc_val = part_val
        else:
            cat_t = gen._new_val('char *', f'mojo_str_cat ({acc_val}, {part_val})')
            acc_val = cat_t
    if acc_val is None:
        # Only reachable for an f-string whose parts are all empty
        # literals (e.g. f"{''}") — emit an empty string, not the old
        # "<formatted>" placeholder that leaked into program output.
        acc_val_t = gen._new_val('char *', f'{gen._intern_string("")}')
        return 'char *', acc_val_t
    return 'char *', acc_val


def _lower_TstringLiteral(gen, node) -> tuple[str, str]:
    val = node.value
    val, _ = gen._decode_str_literal_text(val)
    parts = gen._parse_fstring_parts(val)
    plain = ''.join(v for k, v, _s, _c in parts)
    escaped = gimple_ctypes._c_escape(plain)
    temp = gen._new_val('char *', f'{gen._intern_string(escaped)}')
    return 'char *', temp


def _lower_IdentExpr(gen, node) -> tuple[str, str]:
    name = node.name
    if name == 'None':  return 'int', '0'
    if name == 'True':  return 'int', '1'
    if name == 'False': return 'int', '0'
    if name in gen._boxed_mut_locals and name not in gen._captures:
        # This function's OWN local is heap-boxed because some nested
        # closure captures it by reference -- see _seed_mut_captured_
        # local_types's docstring. `name not in self._captures`:
        # inside a closure body, a same-named captured field is a
        # DIFFERENT thing (handled by the branch below via `_gimple_
        # mut_ptr`) -- this branch is only for reading the box from
        # the ENCLOSING function that owns it.
        ctype = gen._boxed_mut_locals[name]
        t = gen._new_val(ctype, f'*{gen._cname(name)}')
        return ctype, t
    if name == '__file__':
        t = gen._new_val('char *', f'{gen._intern_string("<bootstrap>")}')
        return 'char *', t
    if name == '__name__':
        # self.module_name is "" only for the root module actually being
        # compiled as the entry point (compile_to_gimple's own GimpleGen);
        # every transitively-inlined import gets its real module name
        # (see _compile_imported_module). Hardcoding "__main__"
        # unconditionally here meant every imported script's own
        # `if __name__ == '__main__': main()` guard fired too, running
        # that script's CLI entry point as a side effect of merely being
        # imported into the closure (found via build_stdlib_dylib.py's
        # main() executing during a plain `--dump` of mojo.py).
        own_name = gen.module_name if gen.module_name else "__main__"
        t = gen._new_val('char *', f'{gen._intern_string(own_name)}')
        return 'char *', t
    if name in gen._captures and gen._env_param:
        ctype = gen._captures[name]
        mut_ptr = getattr(gen, '_gimple_mut_ptr', None)
        if mut_ptr and name in mut_ptr:
            # `{mut}`-capture-spec (ClosureInfo.mut_names): the env
            # field is a POINTER to the real outer local, preloaded
            # into `mut_ptr[name]` once at closure entry (see
            # _gen_lifted_closure) -- dereference it, mirroring
            # `_write_dest`'s identical special case for writes.
            t = gen._new_val(ctype, f'*{mut_ptr[name]}')
        else:
            t = gen._new_val(ctype, f'{gen._env_param}->{gimple_ctypes._c_field_name(name)}')
        return ctype, t
    # Bare-imported module-scope `var` global (BUG-2026-009) — read it
    # via a real cross-translation-unit call into the DEFINING module's
    # own synthesized accessor, instead of falling through to the
    # "unknown identifier" zero/NULL placeholder further below (which
    # a per-module-independent `mojo dylib` compile previously always
    # hit for this shape, silently reading zero or a stale/garbage
    # pointer). `name not in self.var_types`: an ordinary same-named
    # LOCAL variable always shadows the imported global, exactly like
    # every other special-case branch in this method.
    if name in gen._imported_global_accessors and name not in gen.var_types:
        _acc_ctype, _acc_csym = gen._imported_global_accessors[name]
        t = gen._call_expr(_acc_ctype, _acc_csym, [])
        return _acc_ctype, t
    # Struct/class type name used as a value (e.g. cls arg) — return zero placeholder
    _BUILTIN_TYPE_NAMES = frozenset({
        'Bool', 'Int', 'UInt', 'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
        'Float16', 'BFloat16', 'Float32', 'Float64',
        'String', 'Error', 'Pointer',
        # Mojo stdlib enum/class types that may be used as class refs (e.g. DType.float32)
        'DType', 'SIMD', 'StringLiteral', 'StringRef',
        'UnsafePointer', 'ArcPointer', 'OwnedPointer',
        'Optional', 'Variant', 'Tuple',
        'InlineArray', 'InlineList', 'StaticTuple',
    })
    if (name in gen.struct_field_types or name in _BUILTIN_TYPE_NAMES) and name not in gen.var_types:
        # int64_t, not int: this placeholder commonly flows into a (void *)
        # cast (e.g. boxed for mojo_obj_getattr on `UInt64.MAX`-style class
        # refs) — a 4-byte int there is a real -Wint-to-pointer-cast size
        # mismatch on LP64, whereas int64_t matches pointer width exactly.
        t = gen._new_temp('int64_t')
        # GIMPLE requires an int64_t lvalue's initializer to itself be an
        # int64_t-typed constant — a bare `0` is `int` and GCC rejects the
        # mismatch as a "non-trivial conversion in 'integer_cst'".
        gen._emit(f'  {t} = (int64_t)0;  /* class ref {name} as value */')
        return 'int64_t', t
    # Python builtin used as a value (e.g. passed to scope.define) — map to C function pointer
    if name in gen.BUILTIN_VALUE_MAP and name not in gen.var_types:
        c_name = gen.BUILTIN_VALUE_MAP[name]
        # Use a pre-declared static void* (emitted in non-GIMPLE context) to avoid
        # the invalid `&func_name` syntax that GIMPLE strict mode rejects.
        # Only add if c_name is a valid C identifier (skip casts like ((int)0))
        if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
            gen._funcptr_builtins_needed.add(c_name)
            static_name = f'_funcptr_{c_name}'
            t = gen._new_val('void *', f'{static_name}')
            return 'void *', t
        else:
            # For non-identifier expressions like ((int)0), emit directly
            t = gen._new_val('void *', f'(void *){c_name}')
            return 'void *', t
    # C function name used as a value (e.g. tokenize, MojoParser passed to Scope_define).
    # Can't use a function name as rvalue in GIMPLE — use a pre-declared static void*.
    if (name in gen.func_return_types and name not in gen.var_types
            and name not in gen.struct_field_types and name not in gen._global_var_types):
        # Use the overload-mangled C symbol so &fn points at the real definition.
        c_name = gen._c_names.get(name, gen._func_csym(name))
        gen._funcptr_builtins_needed.add(c_name)
        static_name = f'_funcptr_{c_name}'
        t = gen._new_val('void *', f'{static_name}')
        return 'void *', t
    # Module-level global variable (persistent type known across functions).
    # Also catches `global x` declarations inside functions (_func_declared_globals).
    #
    # A BARE (unqualified) identifier can only legitimately refer to a
    # global belonging to THIS module — real Python scoping never lets
    # a plain name resolve to some OTHER module's global (that needs
    # `othermodule.name` qualification, handled entirely separately by
    # MemberExpr lowering). `_global_var_types`/`_global_to_module` are
    # shared, whole-transitive-tree-scoped dicts (populated once per
    # name, first writer wins, across every module ever compiled in
    # the closure — see gen_module's "Phase 1.7 pre-scan" and "Module-
    # level globals" passes) — deliberately a superset for cross-
    # module `mod.attr` MEMBER access to work regardless of which
    # level first discovers a given module. Using that same superset
    # to decide whether a BARE name is a global at all is wrong: if
    # some OTHER module (anywhere in the whole closure) happens to
    # ALSO declare a same-named top-level global, `_global_to_module`
    # already recorded which module actually owns it — skip this
    # branch (fall through to the ordinary "unknown identifier"
    # placeholder below) unless it's OUR OWN module's global. Found
    # via `mojo.py`'s self-host build: a lambda inside gimple_codegen.
    # py's own `compile_to_gimple_cached` closing over its enclosing
    # function's `filename` PARAMETER (an ordinary, if imperfectly-
    # supported, closure capture — see the sibling `mojo_src`/
    # `do_imports` captures right next to it, which already correctly
    # fall through to the same placeholder) got misresolved as
    # `_gimple_codegen_globals.filename` — a field gimple_codegen.py
    # never declares — because `mojo_compiler.py`'s OWN unrelated
    # top-level `filename = sys.argv[1] if ... else "<stdin>"` (inside
    # its `if __name__ == "__main__":` block) is also named `filename`
    # and is reachable via the whole-tree scan. See bugs/CODEGEN_
    # generator_function_Lib_weakref.md.
    _global_owner_mod = getattr(gen, '_global_to_module', {}).get(name)
    _this_mod = gen.module_name or "root"
    if (_global_owner_mod is None or _global_owner_mod == _this_mod) and \
            (name in gen._func_declared_globals or name not in gen.var_types) and name in gen._global_var_types:
        gtype = gen._global_var_types[name]
        # Globals are stored at C level as int64_t (boxed pointers) except
        # for char * and simple int globals whose C type matches the Mojo type.
        if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            ctype = 'int64_t'
        else:
            ctype = gtype
        t = gen._new_temp(ctype)
        # Use the overridden actual type (set during global store, e.g.
        # a MojoDict* stored in an int64_t global field) if available,
        # falling back to the declared gtype.
        if name in gen._actual_types and gen._actual_types[name].endswith(' *'):
            gen._actual_types[t] = gen._actual_types[name]
        else:
            gen._actual_types[t] = gtype  # store Mojo type for later dispatch
        # Propagate dict value type even when gtype is int64_t (boxed
        # pointer), so a MojoDict * stored as int64_t in a global still
        # dispatches d["key"] to mojo_dict_get_str — see BUG-2026-044.
        if name in gen._dict_val_types:
            gen._dict_val_types[t] = gen._dict_val_types[name]
        # Same for the list element type of a boxed MojoList * global:
        # without it, print()/repr() of a read-back list temp can't pick
        # the double-aware repr (see _list_repr_fn) — found via
        # `lst = [3.5, 2.5]; print(lst)` printing garbage/segfaulting.
        if name in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[name]
        # Resolve the C decl type through the same own-overlay helper the
        # module-globals struct field freeze (gen_module_impl's
        # `_declared_globals` loop) and the assignment-site coercion
        # (`_global_dst_ctype`) already use — a cross-module same-bare-name
        # homonym that overwrites the SHARED `_global_c_decl_types` between
        # this module's field-freeze and its body emission must not make
        # THIS read load a pointer-shaped field into an int64_t temp without
        # the boxed-pointer cast (the observed encodings/__init__.py
        # `_aliases` failure: field frozen `MojoDict *`, then codecs.py's
        # own `{}`-initialized `_aliases` cdecl'd 'int64_t' into the shared
        # dict, then every `aliased_encoding = _aliases.get(...)` receiver
        # load emitted a bare `int64_t t = MojoDict * field;`
        # -Wint-conversion error).
        c_decl_type = gen._own_overlay_global_ctype(name)
        if c_decl_type is None:
            c_decl_type = gen._global_c_decl_types.get(name, ctype)
        # Access global from module struct (use which module the global belongs to)
        global_module = getattr(gen, '_global_to_module', {}).get(name, gen._current_module_ctx or "root")
        safe_module = gimple_ctypes._c_field_name(global_module) if global_module else "root"
        field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(name)}"
        if ctype == 'int64_t' and c_decl_type.endswith(' *'):
            # Global is declared as a pointer type at C level but we box it as int64_t.
            # GIMPLE: must load pointer into matching-type local, then cast via void* → int64_t.
            raw_ptr = gen._new_val(c_decl_type, f'{field_ref}')
            vp = gen._new_val('void *', f'(void *){raw_ptr}')
            gen._emit(f'  {t} = (int64_t){vp};')
        else:
            # Global is int64_t or same type as ctype — direct assignment is valid.
            gen._emit(f'  {t} = {field_ref};')
        return ctype, t
    ctype = gen._type_of(name)
    cname = gen._c_names.get(name, name)
    if name in gen.var_types:
        return ctype, cname
    # A nested function (closure) referenced as a VALUE (`return add`,
    # `var f = add`, `foo(add)`) — materialize a first-class callable
    # instead of falling through to the unknown-identifier NULL
    # placeholder below (which made `return add` return NULL and any
    # later call through the value segfault). A capturing closure
    # bundles its captured env with the lifted function pointer as a
    # `MojoBoundMethod *` (`fn` + `self`), exactly the representation
    # _lower_bound_method_value already uses, so a later call through
    # the value (`add5(37)` → mojo_bound_method_call_1) can re-supply
    # the env as the lifted function's implicit first argument
    # (`make_adder_add(_env->n, x)`); a non-capturing closure needs no
    # env and is a bare function pointer, matching _lower_LambdaExpr's
    # value representation. Uses the same pre-declared static void*
    # `_funcptr_<name>` var the function-value branches above use
    # (GIMPLE forbids `&func_name` as an rvalue).
    _ci = gen._closure_info_for_ident(name)
    if _ci is not None:
        lifted = _ci.lifted_name
        gen._funcptr_builtins_needed.add(lifted)
        fp = gen._new_val('void *', f'_funcptr_{lifted}')
        if _ci.env_struct:
            env_void = gen._new_val(
                'void *', f'(void *){gen._closure_envs.get(name) or "0"}')
            t = gen._call_expr('MojoBoundMethod *', 'mojo_bound_method_new',
                                [('void *', fp), ('void *', env_void)])
            gen._bound_method_ret_types[t] = gen.func_return_types.get(lifted, 'int64_t')
            return 'MojoBoundMethod *', t
        return 'void *', fp
    # A local `comptime NAME = <value>` (e.g. `comptime maxI = 100`,
    # test_locks.mojo's own idiom for its stress-test loop bounds) is
    # folded by `_gen_stmt_ComptimeVarStmt` into `self._comptime_vals`,
    # but that dict was previously ONLY ever consulted by `_eval_const`
    # (comptime `if`/expression contexts) -- an ORDINARY runtime read of
    # the same name (e.g. `range(0, maxI)`, reached via this generic
    # IdentExpr fallback, not a comptime-only context) fell all the way
    # through to the "unknown identifier" placeholder below, silently
    # substituting `0` for the comptime variable's REAL value -- a real,
    # hand-verified silent-miscompile risk (`for _ in range(0, maxI):`
    # ran ZERO iterations instead of the real 100 the source declared).
    # Consulted here too, before the placeholder, so a comptime
    # variable behaves like the ordinary compile-time constant it is
    # regardless of which kind of expression context reads it.
    _ct = gen._comptime_vals.get(name)
    if isinstance(_ct, bool):
        return '_Bool', gen._new_val('_Bool', 'true' if _ct else 'false')
    if isinstance(_ct, int):
        # Pass the BARE literal (not pre-wrapped in a cast) so
        # `_new_val`'s own int64_t/_Bool literal handling applies —
        # including its negative-literal parenthesization fix, needed
        # since a comptime int can legitimately be negative (e.g. a
        # sentinel `comptime _InvalidIndex: Int = -1`) and `-fgimple`
        # rejects a cast applied directly to a negative literal.
        return 'int64_t', gen._new_val('int64_t', str(_ct))
    # Unknown identifier (compile-time param, undeclared external, etc.).
    # Emit a placeholder so GCC doesn't see an undeclared reference.
    t = gen._new_temp('int64_t')
    gen._emit(f'  {t} = (int64_t)0;  /* ct param or undeclared: {name} */')
    return 'int64_t', t


def _lower_WalrusExpr(gen, node) -> tuple[str, str]:
    vtype, vv = gen.lower_expr(node.value)
    if node.name not in gen.var_types:
        gen._declare_var(node.name, vtype)
    dst = gen.var_types[node.name]
    gen._safe_coerce_emit(vtype, dst, vv, gen._cname(node.name))
    return dst, gen._cname(node.name)


def _lower_UnaryOp(gen, node) -> tuple[str, str]:
    ot, ov = gen.lower_expr(node.operand)
    if node.op == 'not':
        t = gen._new_temp('_Bool')
        if ot in gen._CONTAINER_LEN_FN or ot == 'char *':
            # Delegate to _ensure_bool_cond for real Python truthiness
            # (container length / non-empty string), then negate.
            # GIMPLE doesn't accept `!x`; cast-and-compare instead
            # (mirrors the existing _Bool branch below).
            cond = gen._ensure_bool_cond(ot, ov)
            cond_i = gen._new_val('int', f"(int){cond}")
            gen._emit(f"  {t} = {cond_i} == 0;")
            return '_Bool', t
        if ot in ('void *',) or (ot.endswith(' *') and ot != '_Bool'):
            ip = gen._new_temp('int64_t')
            zero = gen._new_temp('int64_t')
            gen._emit(f"  {ip} = (int64_t){ov};")
            gen._emit(f"  {zero} = (int64_t)0;")
            gen._emit(f"  {t} = {ip} == {zero};")
        elif ot == 'int64_t':
            zero = gen._new_val('int64_t', "(int64_t)0")
            gen._emit(f"  {t} = {ov} == {zero};")
        elif ot == '_Bool':
            # GIMPLE: both operands of comparison must have same type
            # Cast _Bool to int before comparing with integer 0
            int_t = gen._new_val('int', f"(int){ov}")
            gen._emit(f"  {t} = {int_t} == 0;")
        else:
            gen._emit(f"  {t} = {ov} == 0;")
        return '_Bool', t
    # Ownership transfer operator (^) - just pass the value through
    if node.op == '^':
        return ot, ov
    # Spread/unpack operators (* and **) — just pass the value through;
    # the list/call context handles iteration. `**` has no other meaning
    # in this codebase (no real double-pointer dereference use), so it's
    # always a spread marker regardless of operand type. A bare `*` is
    # ambiguous with real pointer dereference (mojo_compiler.py's parser
    # produces the identical UnaryOp(op='*', ...) node shape for both
    # `*ptr` and a spread `*args`), so treat it as a spread pass-through
    # when the operand is one of the boxed container types a spread
    # always operates on (MojoList*/MojoDict*/MojoSet* — e.g.
    # `os.path.join(*path_parts)`'s single-MojoList-arg special case a
    # few hundred lines down relies on getting the bare 'MojoList *'
    # type/value here, not a dereferenced-once type) OR isn't a pointer
    # at all — dereferencing a non-pointer value was never valid codegen
    # anyway and used to fall through to the generic operator-emission
    # code below, which for op='**' literally emitted invalid C like
    # "**some_int64_var" (GCC: "invalid type argument of unary '*'") —
    # found via self-hosting myinterpreter.py's own
    # `SimpleNamespace(**_build_testing_shims(self))` call.
    # `void *` also needs the spread pass-through, not just the three
    # named container types: map()/filter()/zip() are lowered to
    # mojo_map/mojo_filter/mojo_zip, whose C return type is a generic
    # `void *` (mojo_map: `void *mojo_map(void *func, void *iterable) {
    # return iterable; }` — a lazy passthrough of whatever
    # MojoList*/MojoDict*/MojoSet* it was given, just type-erased to
    # void* in C). Real: tokenize.py's `Special = group(*map(re.escape,
    # sorted(EXACT_TOKEN_TYPES, reverse=True)))` — `*map(...)` fell
    # through to the "Pointer dereference" branch below since 'void *'
    # wasn't in the recognized set, emitting a literal `*_t211` on a
    # void* value — always invalid C ("invalid use of void expression"),
    # never a case genuine dereference code could have produced a valid
    # program from (dereferencing `void *` is never legal C regardless
    # of the elem_type it's cast to afterward), so this was dead/broken
    # for every caller, not just this one.
    if node.op == '**' or (node.op == '*' and (
            ot in ('MojoList *', 'MojoDict *', 'MojoSet *', 'void *')
            or not ot.endswith(' *'))):
        return ot, ov
    # Pointer dereference * on a known pointer type
    if node.op == '*':
        if ot.endswith(' *'):
            elem_type = ot[:-2].strip() or 'int64_t'
            if elem_type == 'void':
                elem_type = 'int64_t'
            # Struct types: return int64_t (opaque handle) — can't cast struct to int64_t in GIMPLE
            if elem_type in gen.struct_field_types or elem_type == 'StringSlice':
                t = gen._new_val('int64_t', f"(int64_t){ov}")
                return 'int64_t', t
            t = gen._new_val(elem_type, f"*{ov}")
            return elem_type, t
        else:
            # int typed as pointer — can't safely dereference; return as-is
            return ot, ov
    if node.op == '+':
        return ot, ov
    c_op = {'-': '-', '~': '~'}.get(node.op, node.op)
    # Struct pointers can't be negated/inverted — coerce to int64_t first.
    # char* included: `-<char*>` is never valid Python (negating a string
    # is a TypeError), but the runtime-dispatch for-loop lowers both a
    # dict-key branch (loop var as char*) and a list-of-pairs branch for
    # the same body — the dead dict branch must still COMPILE even though
    # its `-item.value` (item = a char* key, `.value` → identity) is
    # semantically meaningless.
    actual_ot = ot
    actual_ov = ov
    if ot.endswith(' *') and c_op in ('-', '~'):
        ip = gen._new_val('int64_t', f"(int64_t){ov}")
        actual_ot = 'int64_t'
        actual_ov = ip
    t = gen._new_val(actual_ot, f"{c_op}{actual_ov}")
    return actual_ot, t


def _lower_TernaryExpr(gen, node) -> tuple[str, str]:
    # Real branching, not a C `?:` built from two already-evaluated
    # operands: the previous lowering unconditionally emitted code for
    # BOTH then_val and else_val before selecting between the results,
    # so any side effect in the untaken branch (I/O, a function call)
    # still happened — a real correctness bug, not just waste, and one
    # every ternary in the self-hosted closure was exposed to (see
    # BACKLOG-CODEGEN.md §4d; found via mojo_compiler.py's own
    # `sys.stdin.read() if len(sys.argv) < 2 else open(...).read()`
    # reading stdin unconditionally even when a file argv was given).
    # _quick_type gives each branch's C type WITHOUT evaluating it (the
    # same "estimate a type, don't run the code" contract already used
    # for list/tuple literal element-type inference), so the merged
    # result type — and therefore the shared result temp's declared
    # type — can be fixed before either branch actually executes.
    ct, cv = gen.lower_expr(node.condition)
    cv = gen._ensure_bool_cond(ct, cv)
    res_type = gimple_ctypes.TypeLattice.join(gen._quick_type(node.then_val), gen._quick_type(node.else_val))
    result = gen._new_temp(res_type)
    bb_then = gen._new_bb()
    bb_else = gen._new_bb()
    bb_merge = gen._new_bb()
    gen._emit(f"  if ({cv}) goto {bb_then}; else goto {bb_else};")
    gen._emit_label(bb_then)
    tt, tv = gen.lower_expr(node.then_val)
    gen._safe_coerce_emit(tt, res_type, tv, result)
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_else)
    et, ev = gen.lower_expr(node.else_val)
    gen._safe_coerce_emit(et, res_type, ev, result)
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return res_type, result


def _lower_MemberExpr(gen, node) -> tuple[str, str]:
    # `m.lastgroup` where m is a regex-match for-loop variable — see
    # _gen_for_regex_iter / regex_compile.py / BACKLOG-CODEGEN.md §4f.
    if (isinstance(node.obj, gimple_ctypes.IdentExpr) and node.obj.name in gen._regex_match_vars
            and node.member == 'lastgroup'):
        ctx = gen._regex_match_vars[node.obj.name]
        return 'char *', gen._call_expr('char *', 'mojo_regex_lastgroup',
                                          [('const char * *', ctx['names_var']),
                                           ('int', str(ctx['ngroups'])),
                                           ('int64_t *', ctx['gstart_var'])])

    # `item.key` / `item.value` where `item` is a `for item in d.items():`
    # loop var — ONE var bound to the whole [key, value] pair (see
    # _dict_item_pair_vars). The runtime pair is a 2-element MojoList:
    # slot 0 is the key (always a string — mojo_dict_items appends it via
    # append_str), slot 1 is the value, boxed per the dict's value type.
    # Without this, both members fell through to the generic dynamic
    # getattr (which knows nothing about pairs) and resolved to 0/an
    # identity, so `-item.value` negated the pair handle or the char*
    # key — a GIMPLE "wrong type argument to unary minus", or a build2
    # ICE, in counter/interval/_unicode/string_slice (A5-BUG.md §1).
    if (isinstance(node.obj, gimple_ctypes.IdentExpr)
            and node.obj.name in gen._dict_item_pair_vars
            and node.member in ('key', 'value')):
        _pv_type = gen._dict_item_pair_vars[node.obj.name]
        _pv_raw = gen._cname(node.obj.name)
        _pair = gen._new_val('MojoList *', f"(MojoList *){_pv_raw}")
        if node.member == 'key':
            return 'char *', gen._new_val(
                'char *', f"mojo_list_get_str ({_pair}, 0)")
        _suf = gimple_ctypes.TypeLattice.list_suffix(_pv_type)
        if _suf == 'str':
            return 'char *', gen._new_val(
                'char *', f"mojo_list_get_str ({_pair}, 1)")
        if _suf == 'double':
            return 'double', gen._new_val(
                'double', f"mojo_list_get_double ({_pair}, 1)")
        _raw = gen._new_val('int64_t', f"mojo_list_get_int ({_pair}, 1)")
        if _pv_type in ('int64_t', 'int', ''):
            return 'int64_t', _raw
        # A struct-pointer / other non-scalar value type: keep the real
        # static type so a later field read or call resolves statically.
        return _pv_type, gen._new_val(_pv_type, f"({_pv_type}){_raw}")

    # `f.name` where f is a `for f in dataclasses.fields(x):` loop var —
    # see _gen_for_iter's is_dataclass_fields_loop handling. `f` is
    # already the field-name string (a real dataclasses.Field object
    # is never materialized), so `.name` is just identity.
    if (isinstance(node.obj, gimple_ctypes.IdentExpr) and node.obj.name in gen._dataclass_fields_vars
            and node.member == 'name'):
        return gen.lower_expr(node.obj)

    # Check if obj is a simple identifier (module access)
    if isinstance(node.obj, gimple_ctypes.IdentExpr):
        module_name = node.obj.name

        # `f.attr` read where `f` is a free function memoizing a value on
        # itself (`f._cached`) — see the `_func_attrs` pre-scan (Phase 1,
        # gen_module) for the full BUG-2026-049-adjacent story. Redirects
        # to the synthesized global backing this attribute, exactly like
        # `_class_attrs` does for `ClassName.attr` a little further down
        # in this same method.
        _fattrs = gen._func_attrs
        if _fattrs and module_name in _fattrs and node.member in _fattrs[module_name]:
            mangled = _fattrs[module_name][node.member]
            gtype = gen._global_var_types.get(mangled, 'int64_t')
            t = gen._new_val(gtype, mangled)
            return gtype, t

        # A free function reached through a module alias and used as a
        # VALUE, not immediately called — `x = m.helper_add` (as opposed
        # to `m.helper_add(...)`, which never reaches this method at all:
        # `_lower_call` special-cases `isinstance(node.func, MemberExpr)`
        # and routes straight to `_lower_method_call`/the import-aware
        # call path BEFORE any operand is lowered as a plain value). This
        # method has no such special-case, so `m.helper_add` used as a
        # bare expression used to fall all the way through to the
        # generic "opaque object, dynamic runtime getattr" branch further
        # down (`_mojo_dispatch_getattr`) — a struct-instance reflection
        # helper that has no idea `m` is a module marker or that
        # "helper_add" names a real, statically-known function; it
        # always returned a bogus non-pointer value. Whatever got stored
        # in the target variable was later called (see `_lower_call`'s
        # "local/global variable holding a function pointer" case,
        # `_lower_fnptr_call`) as if it were a genuine function pointer —
        # it never was one, hence BUG-2026-049's undefined-symbol link
        # error (the SEPARATE, `_lower_named_call` fallback path that
        # mis-fired instead, guessing the call target was a C function
        # literally named after the Mojo variable).
        #
        # `module_name in self.imported_symbols` is true for ANY alias
        # bound by `import ... as module_name` — see
        # `_gen_stmt_ImportStmt`, which populates this dict for every
        # import target regardless of whether the `import` statement
        # itself sits at module top level or nested inside a function
        # body (do_imports=True's Phase 0 `find_imports` scan already
        # recurses into function bodies, so the module is genuinely
        # compiled/inlined into this same translation unit by the time
        # any function runs). `node.member in self.func_return_types` is
        # true only for a real, statically-known function (populated for
        # BOTH this module's own top-level defs and every transitively
        # inlined imported module's defs, in gen_module's Phase 1 type
        # table build) — so this only fires for a genuine function
        # reference, not an arbitrary/unknown module attribute (which
        # still falls through to the generic dynamic-dispatch fallback
        # below, unchanged).
        if (module_name in gen.imported_symbols
                and node.member in gen.func_return_types
                and node.member not in gen.struct_field_types):
            # Can't use a function name as a bare rvalue under -fgimple
            # (same restriction the "C function name used as a value"
            # case in _lower_IdentExpr already documents) — go through
            # the same pre-declared-static-void* mechanism it uses
            # (_funcptr_builtins_needed / `_funcptr_{c_name}`) rather
            # than emitting an inline `(void *)csym` cast here.
            csym = gen._func_csym(node.member)
            gen._funcptr_builtins_needed.add(csym)
            static_name = f'_funcptr_{csym}'
            t = gen._new_val('void *', f'{static_name}')
            return 'void *', t

        # `submod.GLOBAL` — a plain module-level global/constant read
        # off a real SUBMODULE marker (`from PKG import submod`, see
        # `_gen_stmt_FromImportStmt`'s submodule branch, or a plain
        # `import submod`). `self.imported_symbols[module_name]
        # ['module']` is the submodule's own full dotted name;
        # `_global_to_module`/`_global_var_types` (populated when
        # do_imports=True's Phase 0 inline-compiles that exact
        # submodule — see `_compile_imported_module`'s `module_name=
        # module_name` temp_gen, and gen_module's "Phase 1.7 pre-scan"/
        # "Module-level globals" passes) record which module really
        # OWNS a given global name and its real C type. Mirrors
        # `_lower_IdentExpr`'s identical bare-name global-read branch
        # (used when the import binds a plain symbol instead of a
        # submodule) — same field-access shape, same `_{module}_
        # globals.<field>` struct this codegen already emits in its
        # preamble for cross-module global access. Only fires when the
        # global's OWNER module is EXACTLY the module `module_name` is
        # bound to, so an unrelated same-named global defined in some
        # OTHER transitively-compiled module never misfires here (see
        # `_lower_IdentExpr`'s own "shared, whole-tree-scoped dicts"
        # caveat — identical reasoning applies to this member-access
        # form). Without this, `os_helper.TESTFN` (from `from test.
        # support import os_helper`) fell through to the fully-dynamic
        # `_mojo_dispatch_getattr` runtime dispatch on the module
        # marker's `(int64_t)0` placeholder — a NULL-pointer read, not
        # the real global value (see bugs/CODEGEN_generator_function_
        # Lib_test_test_support.md's 2026-08-09 root-cause).
        _bound_mod = gen.imported_symbols.get(module_name, {}).get('module') \
            if module_name in gen.imported_symbols else None
        if (_bound_mod and node.member in gen._global_var_types
                and getattr(gen, '_global_to_module', {}).get(node.member) == _bound_mod):
            gtype = gen._global_var_types[node.member]
            ctype = 'int64_t' if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *') else gtype
            t = gen._new_temp(ctype)
            if node.member in gen._actual_types and gen._actual_types[node.member].endswith(' *'):
                gen._actual_types[t] = gen._actual_types[node.member]
            else:
                gen._actual_types[t] = gtype
            if node.member in gen._dict_val_types:
                gen._dict_val_types[t] = gen._dict_val_types[node.member]
            if node.member in gen._elem_types:
                gen._elem_types[t] = gen._elem_types[node.member]
            # Same own-overlay-first resolution as the bare-name global-read
            # branch above — the submod.GLOBAL field load must agree with the
            # struct-field freeze for the exact same homonym reason.
            c_decl_type = gen._own_overlay_global_ctype(node.member)
            if c_decl_type is None:
                c_decl_type = gen._global_c_decl_types.get(node.member, ctype)
            safe_module = gimple_ctypes._c_field_name(_bound_mod) if _bound_mod else "root"
            field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(node.member)}"
            if ctype == 'int64_t' and c_decl_type.endswith(' *'):
                raw_ptr = gen._new_val(c_decl_type, f'{field_ref}')
                vp = gen._new_val('void *', f'(void *){raw_ptr}')
                gen._emit(f'  {t} = (int64_t){vp};')
            else:
                gen._emit(f'  {t} = {field_ref};')
            return ctype, t

        # __mlir_attr.`literal` — a typed MLIR attribute used as a value
        # (integer constants like `0 : index`).  Lower to the constant.
        if module_name == '__mlir_attr':
            kind, val = gimple_ctypes.mlir.parse_attr(node.member)
            if kind in ('int', 'simd'):   # typed int / scalar-simd constant
                t = gen._new_val('int64_t', f"(int64_t){val}")
                return 'int64_t', t
            # Predicate / unmodeled attrs only matter as op subscript params,
            # which are read directly at the op call site; yield a placeholder.
            t = gen._new_temp('int')
            gen._emit(f"  {t} = 0;  /* __mlir_attr {gimple_ctypes.mlir.unwrap(node.member)} */")
            return 'int', t

        # Module attribute access: sys.argv, tokenizer.X, etc.
        if module_name == 'sys' and node.member == 'argv':
            # Return the argv list wired from C main(argc, argv)
            t = gen._new_temp('MojoList *')
            gen._emit(f"  {t} = mojo_get_argv();  /* sys.argv from C */")
            # Track element type so subscript uses mojo_list_get_str
            gen._elem_types[t] = 'char *'
            return 'MojoList *', t
        if module_name == 'sys' and node.member == 'path':
            t = gen._new_temp('MojoList *')
            gen._emit(f"  {t} = mojo_list_new ();  /* sys.path stub */")
            gen._elem_types[t] = 'char *'
            return 'MojoList *', t
        if module_name == 'sys' and node.member in ('stdout', 'stderr', 'stdin'):
            # The three standard stream FILE objects. This runtime has no
            # Python-file-object model, so each is represented as its POSIX
            # file descriptor (0/1/2 — the same identity libc's
            # fileno(stdin/stdout/stderr) yields) boxed as an opaque scalar
            # handle: enough for `for s in [sys.stdout, sys.stderr]:
            # s.reconfigure(...)` (the unknown-method scalar stub passes the
            # handle through, an honest no-op — this runtime's printf output
            # is already unbuffered) and any future fd-level write support,
            # WITHOUT crashing the way the previous fallthrough did: `sys`
            # binds to a bare module marker (int64_t 0), so the generic
            # dynamic-getattr dispatch received obj=NULL and raised a fatal
            # `AttributeError: stdout` at runtime (real:
            # Apple/__main__.py's entry tail reconfigures both streams
            # before main()). Deliberately NOT the ast_rewriter's
            # `sys.stdin.read()` rule's job — that fires on the CALL shape
            # before this value read is ever reached; this case covers
            # bare VALUE reads of the streams themselves.
            fd = {'stdin': '0', 'stdout': '1', 'stderr': '2'}[node.member]
            t = gen._new_val('int64_t', fd)
            return 'int64_t', t

        # Special handling for os.path attribute access
        if module_name == 'os' and node.member == 'path':
            # os.path is a marker - return a special value indicating path module
            # The actual function call will be handled at the call site
            t = gen._new_temp('int')
            gen._emit(f"  {t} = 0;  /* os.path module marker */")
            return 'int', t

        # os.sep / os.pathsep / os.curdir / os.pardir / os.linesep —
        # this platform is always POSIX ('/'), so all five are genuine
        # compile-time constants straight out of os.py's own module body
        # (sep='/'; pathsep=':'; curdir='.'; pardir='..'; linesep='\n').
        # `sep`/`pathsep` were always handled here; the other three fell
        # through to the generic unresolved-module-attribute paths below
        # — a silent `(int)0` stub where one was reachable, else a fatal
        # runtime `AttributeError: curdir`/`AttributeError: linesep`
        # from the generic dynamic-dispatch fallback (real:
        # Lib/mailbox.py:32's `linesep = os.linesep.encode('ascii')`,
        # whose global then also mis-typed against the mismatched RHS).
        if module_name == 'os' and node.member in ('sep', 'pathsep',
                                                   'curdir', 'pardir',
                                                   'linesep'):
            val = {'sep': '/', 'pathsep': ':', 'curdir': '.',
                   'pardir': '..', 'linesep': '\n'}[node.member]
            # _intern_string wants an already-C-escaped literal body —
            # linesep's raw newline must go through _c_escape (the same
            # shared helper every other string-emission site uses) or it
            # splices a literal line break into the .ci string pool.
            t = gen._new_val('char *',
                             gen._intern_string(gimple_ctypes._c_escape(val)))
            return 'char *', t

        # signal.SIG* — the portable POSIX signal numbers, genuine
        # compile-time constants fixed by the OS ABI (identical on every
        # POSIX system this runtime targets). `signal` binds to a bare
        # module marker, so these fell through to the dynamic-getattr
        # fallback — obj=NULL, fatal `AttributeError: SIGTERM` at runtime
        # (real: Apple/__main__.py's main(): `signal.signal(signal.SIGTERM,
        # signal_handler)`). Only the eleven numbers that are identical
        # across all POSIX platforms are listed; BSD/Linux-only members
        # (SIGUSR1/SIGCHLD/...) deliberately keep the honest AttributeError
        # rather than risk emitting a wrong number.
        if module_name == 'signal' and node.member in (
                'SIGHUP', 'SIGINT', 'SIGQUIT', 'SIGILL', 'SIGABRT',
                'SIGFPE', 'SIGKILL', 'SIGSEGV', 'SIGPIPE', 'SIGALRM',
                'SIGTERM'):
            val = {'SIGHUP': 1, 'SIGINT': 2, 'SIGQUIT': 3, 'SIGILL': 4,
                   'SIGABRT': 6, 'SIGFPE': 8, 'SIGKILL': 9, 'SIGSEGV': 11,
                   'SIGPIPE': 13, 'SIGALRM': 14, 'SIGTERM': 15}[node.member]
            t = gen._new_val('int64_t', str(val))
            return 'int64_t', t

        # Class attribute access: ClassName.ATTR
        # Check if module_name is a known struct/class (not an instance variable)
        if module_name in gen.struct_field_types and module_name not in gen.var_types:
            # `comptime NAME: Type = value` struct member (e.g. IfStmt.KIND)
            # accessed directly on the type name, not through an instance —
            # expand to its defining expression, same mechanism
            # _lower_MemberExpr's instance-typed path already uses below
            # (see the `aliases = self._struct_comptime_aliases.get(...)`
            # branch a few lines down, reached only when node.obj is an
            # INSTANCE, not a bare type-name IdentExpr). This bare-name
            # case used to fall through to a dummy "class attr" stub that
            # always emitted the literal 0 regardless of the alias's real
            # value — e.g. `IfStmt.KIND` printed 0 under --jit/--dump
            # instead of its declared value under `mojo run`.
            aliases = gen._struct_comptime_aliases.get(module_name)
            if aliases and node.member in aliases:
                return gen.lower_expr(aliases[node.member])
            # Not a comptime alias — a genuine class-level access this
            # compiler doesn't yet resolve statically (unimplemented,
            # not merely unreached); stub with a clearly-marked value.
            t = gen._new_temp('int')
            gen._emit(f"  {t} = 0;  /* class attr {module_name}.{node.member} — UNRESOLVED, not a comptime alias */")
            return 'int', t

        # Class name accessed as an attribute base before its real
        # struct layout is known yet (e.g. `Parameter.VAR_POSITIONAL`
        # inside enum.py's `__signature__`, where `from inspect import
        # Parameter` is a FUNCTION-SCOPED import lowered generically by
        # `_gen_stmt_FromImportStmt` — it registers `Parameter` into
        # `self.imported_symbols`/`self.func_return_types` as if it
        # were an ordinary callable, since that generic path has no way
        # to know the imported name is actually a class). Without this
        # check, the "zero-arg function used in member-access context"
        # fallback just below (meant for real accessor functions like
        # `block_idx.x`) fires instead: it emits `Parameter ()` — a
        # bare call to `Parameter`, colliding with the SAME identifier
        # already `typedef`'d as `struct Parameter` elsewhere in this
        # translation unit once the real class genuinely does get
        # inlined (e.g. via some OTHER file's top-level `from inspect
        # import Parameter`) — a hard "expected expression before
        # 'Parameter'" GCC syntax error (a typedef name can't be reused
        # as a function/call identifier in C). Route the same way as
        # the already-known-struct case just above: emit the same
        # "class attr ... UNRESOLVED" stub. Guarded narrowly (a
        # PascalCase identifier that came from an import, per Python's
        # own class-naming convention — real accessor functions this
        # fallback exists for, like `block_idx`/`thread_idx`/`grid_dim`,
        # are always lowercase) so it can't affect any function this
        # fallback already legitimately handles.
        if (module_name in gen.imported_symbols
                and module_name not in gen.var_types
                and module_name not in gen.struct_field_types
                and module_name not in gen.BUILTIN_VALUE_MAP
                and module_name[:1].isupper()):
            t = gen._new_temp('int')
            gen._emit(f"  {t} = 0;  /* class attr {module_name}.{node.member} — UNRESOLVED import, not yet inlined as a struct */")
            return 'int', t

        # A real module alias's attribute names a known STRUCT/CLASS —
        # `lx.Token` where `import lexer as lx` and `class Token` is a
        # real, already-inlined class (`node.member in gen.
        # struct_field_types`). Mirrors the `module_name[:1].isupper()`
        # branch just above (which covers a class NAME used as the
        # attribute base, e.g. `Parameter.VAR_POSITIONAL`) for the
        # opposite shape: a class name used as the attribute VALUE off a
        # real module marker, e.g. Tools/cases_generator/plexer.py's
        # top-level `Token = lx.Token` (re-exporting a sibling module's
        # class under a local alias — real Python has no distinct
        # "class value" representation, it's just the class object
        # itself). Without this check, `module_name in gen.imported_
        # symbols` is true (a real module alias) but none of the
        # earlier branches match (`node.member` isn't a function, not a
        # `sys`/`os` special-case, not a matching-owner global) and
        # `node.member[:1].isupper()` is irrelevant here since this
        # checks `module_name`, not `node.member` — so it fell all the
        # way through to the generic dynamic-dispatch fallback further
        # below, which calls the real RUNTIME `mojo_obj_getattr` on the
        # module marker's placeholder `(int64_t)0` value, unconditionally
        # raising a genuine (uncaught) `AttributeError: Token` the
        # instant this assignment executes — not merely an unresolved
        # stub value, an actual fatal exception. See
        # bugs/COMPILE_FAIL_Tools_cases_generator_parser.md's runtime
        # `AttributeError: Token` gap (parser.py -> parsing.py -> `from
        # plexer import PLexer` -> plexer.py's `Token = lx.Token`).
        # Same "class access unimplemented, stub rather than crash"
        # treatment as the two branches above, not a real fix for
        # class-as-value support in general (still a real, documented
        # feature gap — just no longer a hard runtime crash for it).
        if (module_name in gen.imported_symbols
                and module_name not in gen.struct_field_types
                and node.member in gen.struct_field_types
                and node.member not in gen.var_types):
            t = gen._new_temp('int')
            gen._emit(f"  {t} = 0;  /* class value {module_name}.{node.member} — UNRESOLVED, class-as-value not modeled */")
            return 'int', t

    # If the object is a zero-arg function used in member-access context (e.g. block_idx.x),
    # call it first so we get the struct return value, not a void* funcptr.
    #
    # Excludes dunder members (`__code__`, `__name__`, `__doc__`, ...):
    # those are real Python attributes of the FUNCTION OBJECT ITSELF
    # (`f.__code__` always means "introspect f", never "call f() and
    # read .__code__ off its result", regardless of f's own arity or
    # return type) — but this heuristic can't tell that apart from the
    # block_idx.x/thread_idx.x/grid_dim.x GPU-intrinsic shape it exists
    # for by construction alone, since both are "bare function name
    # immediately followed by a MemberExpr". Without the exclusion,
    # `_write_atomic.__code__` (Lib/importlib/_bootstrap_external.py,
    # `_code_type = type(_write_atomic.__code__)`) emitted a bare
    # `_write_atomic ()` zero-arg call to a real 3-parameter function —
    # "implicit declaration of function '_write_atomic'" (GCC can't
    # find a zero-arg overload, only the real mangled one). Dunder
    # member names are never legitimate GPU-intrinsic accessor fields
    # (always lowercase x/y/z), so excluding them can't affect that
    # case. Falling through to the `else` branch instead lowers
    # node.obj as an ordinary identifier — `_lower_IdentExpr`'s own
    # "C function name used as a value" branch already produces a
    # valid `_funcptr_*` void* value for a bare, uncalled function
    # name, which the generic dynamic-dispatch fallback further below
    # (the `ot in ('int', 'int64_t', 'void *', ...)` case) then handles
    # like any other opaque-pointer member read.
    # Excludes a real MODULE/NAMESPACE alias whose bare name also happens
    # to collide with a same-named top-level function pulled in from some
    # OTHER transitively-compiled module (`self.func_return_types` is a
    # single whole-program-shared, bare-name-keyed dict — see the same
    # caveat already documented a few branches up for `_global_var_types`).
    # E.g. `subprocess.py`'s `import signal` + `signal.SIGTERM`: `signal`
    # the MODULE MARKER is also, coincidentally, the bare name of `Lib/
    # signal.py`'s own top-level `def signal(signalnum, handler):` once
    # that module is transitively inlined into the same translation unit
    # (plus, independently, a real libc function of the same name) — so
    # this zero-arg-function fallback (meant for real accessor functions
    # like `block_idx.x`) misread `signal.SIGTERM` as "call the zero-arg
    # function `signal()`, then read `.SIGTERM` off the result", emitting
    # an invalid `mojo_signal ()`/bare `signal ()` call.
    #
    # Gated on `gen._module_alias_names`, NOT plain `gen.imported_symbols`
    # membership — a first fix attempt used `imported_symbols` and had to
    # be reverted: `imported_symbols` also holds every ordinary `from X
    # import name` VALUE/function binding (not just genuine `import X`
    # namespace markers), and an UNRESOLVED such binding (no real
    # signature found) registers with the exact same `{'module': ...,
    # 'return_type': ...}` shape a genuine namespace marker uses — see
    # `_module_alias_names`'s own docstring (gimple_codegen.py). Confirmed
    # via a real regression this broader check caused: `std/gpu/
    # primitives/id.mojo`'s `block_idx`/`thread_idx` (real zero-arg
    # accessor functions, imported into the always-present builtin
    # prelude but never resolved to a real signature) collided with
    # `imported_symbols` the same way `signal` does, wrongly excluding
    # the GENUINE `block_idx.x`/`thread_idx.x` GPU-intrinsic accessor
    # shape this fallback exists for in the first place — silently
    # breaking it (confirmed via `test_module_cache.py`'s SB-1 per-scope-
    # import CLI tests, which transitively pull this same builtin prelude
    # into every `mojo.py build`: 2 tests regressed with a `dyld: symbol
    # not found ... '_block_idx'` runtime crash). `_module_alias_names`
    # is populated ONLY by the two real `import`-statement sites, never by
    # an ordinary `from X import name` binding, so it doesn't have this
    # ambiguity. Mirrors the `module_name in gen.imported_symbols` guard
    # already used a few branches up in this same function's
    # `isinstance(node.obj, IdentExpr)` block — moved to cover this
    # SEPARATE, later fallback that re-checks `isinstance(node.obj,
    # IdentExpr)` on its own, since a real module marker can reach here
    # whenever none of that earlier block's more specific attribute cases
    # matched (e.g. an unresolved/unknown module attribute like `signal.
    # SIGTERM`, which comes from the unloadable C extension `_signal` and
    # so is never registered as a known global).
    _dunder_member = node.member.startswith('__') and node.member.endswith('__')
    if (isinstance(node.obj, gimple_ctypes.IdentExpr)
            and node.obj.name in gen.func_return_types
            and node.obj.name not in gen.var_types
            and node.obj.name not in gen.struct_field_types
            and node.obj.name not in gen.BUILTIN_VALUE_MAP
            and node.obj.name not in gen._module_alias_names
            and not _dunder_member):
        _fn_name = node.obj.name
        _c_fn = gen._c_names.get(_fn_name, gimple_ctypes._safe_name(_fn_name))
        # Resolve through _resolve_type: some imports register a bare
        # 'int' sentinel (unknown-signature placeholder, see
        # _gen_stmt_FromImportStmt) rather than a real C type. Declaring
        # this temp as a genuine 4-byte int when the value later gets
        # boxed via `(void *)` for mojo_obj_getattr is a real
        # -Wint-to-pointer-cast size mismatch; resolving narrows the fix
        # to this call-result temp without touching the shared dict (a
        # wider fix there previously broke unrelated bare-`0`-literal
        # class-ref temps expecting the raw, unresolved type).
        _ret = gen._resolve_type(gen.func_return_types.get(_fn_name, 'int64_t'))
        ot = _ret
        ov = gen._new_val(_ret, f'{_c_fn} ()')
    else:
        ot, ov = gen.lower_expr(node.obj)
        # `self.prop.attr` where `prop` is a 0-arg property/method
        # accessed without call syntax (`self.prop`, no `()`) lowers to
        # a deferred, uncalled `MojoBoundMethod *` value (see
        # _lower_bound_method_value) — correct when `self.prop` is
        # itself being called (`self.prop()`) or passed around as a
        # first-class callable, but chaining a MEMBER ACCESS directly
        # off it is never that: real Python (and, for a `@property`
        # specifically, the entire point of the decorator) auto-
        # invokes the getter/method FIRST and only then looks up
        # `.attr` on the RESULT. This codegen has no notion of
        # `@property` vs. an ordinary bound method at this
        # representation level (both lower identically via
        # _lower_bound_method_value) — but a real, intentional
        # "read a member off the bound-method OBJECT itself" (e.g.
        # `self.method.__name__`) isn't supported by this codegen
        # either way (the dynamic-dispatch fallback further below has
        # no such fields registered for MojoBoundMethod), so auto-
        # invoking here is a strict improvement with no realistic
        # regression case. Mirrors _lower_subscript's identical fix
        # for `self.prop[key]` (see that method's own comment for the
        # original bug/fix history). Confirmed via Lib/zipfile/_path/
        # __init__.py's `filename` @property: `self.filename.parent`
        # previously ran `_mojo_dispatch_getattr` on the bound-method
        # object itself, which has no `.parent` — silent wrong
        # runtime behavior (AttributeError) rather than a compile
        # error, since the struct-name fallback further below (Step
        # 4, bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md)
        # already routes unknown MojoBoundMethod fields through
        # runtime dispatch instead of a hard GCC error. See bugs/
        # COMPILE_FAIL_zipfile__path___init__.md.
        #
        # REGRESSION (found+fixed 2026-08-18, see bugs/hard/CODEGEN_
        # dynamic_attribute_on_generic_object.md's dated status
        # section): the "isn't supported either way" claim above was
        # wrong the moment it was written — Sub-case C (this same
        # doc, landed HOURS earlier the same day) already made
        # `f.__name__`/arbitrary dynamic attributes on a MojoBoundMethod
        # a real, working feature. This auto-invoke fired unconditionally
        # on ANY `X.member` where `X` lowers to a MojoBoundMethod *,
        # including a plain closure VARIABLE (`f = make_closure(); f.
        # __name__ = ...; print(f.__name__)`) — silently calling the
        # closure (`mojo_bound_method_call_0`) instead of ever reaching
        # the `__name__` special case or the `_FIXED_RUNTIME_STRUCT_
        # NAMES` dispatch further down, both now permanently dead code
        # for this shape. Fixed by scoping the auto-invoke to its own
        # actual target shape — chaining a member access directly off a
        # FRESH property/method lookup (`self.prop.attr`: `node.obj` is
        # itself a `MemberExpr`) — which is exactly what this fix's own
        # confirmed repro (`self.filename.parent`) and every real-world
        # instance in its commit message look like. A bound-method value
        # already sitting in a plain variable (`node.obj` an `IdentExpr`
        # or anything else) is left alone, so attribute access directly
        # on a closure/bound-method OBJECT itself reaches the existing
        # dynamic-attribute machinery instead of being auto-invoked.
        if ot == 'MojoBoundMethod *' and isinstance(node.obj, gimple_ctypes.MemberExpr):
            ot, ov = gmp._auto_invoke_bound_method_value(gen, ov)
        # Resolve an int64_t-boxed pointer to its real struct type (e.g.
        # `t = self._peek()` boxes a `Token *` as int64_t) — without this,
        # `t.line` never found a real struct field and fell through to the
        # generic dynamic-getattr path. Mirrors the same resolution (and
        # the GIMPLE-required intermediate-cast dance) `_lower_method_call`
        # already does for `obj.method(...)`.
        ot_orig = ot
        ot = gen._get_actual_type(ot, ov)
        if ot != ot_orig and ot.endswith(' *') and ot_orig == 'int64_t':
            ov_local = gen._ensure_local('int64_t', ov)
            ip_cast = gen._new_temp('int64_t')
            np_cast = gen._new_temp(ot)
            gen._emit(f"  {ip_cast} = (int64_t){ov_local};")
            gen._emit(f"  {np_cast} = ({ot}){ip_cast};")
            ov = np_cast

    # A struct-typed PARAMETER whose Mojo annotation names a known struct
    # (e.g. `downgrade: ArcPointer[Self.T]`) is ABI-boxed to a generic
    # scalar in the C signature (`int64_t downgrade`), and the
    # `_actual_types` entry for it may even claim a boxed generic pointer
    # (`int64_t *`) that has lost the struct identity entirely. Member
    # access must therefore cast through the REAL struct pointer type
    # recovered from the annotation — casting to `int64_t *` and emitting
    # `(int64_t *)_t3->_inner` is a hard GCC error ("request for member
    # '_inner' in something not a structure or union"); see
    # std/memory/arc_pointer.mojo's Weak.__init__(downgrade: ...).
    if (isinstance(node.obj, gimple_ctypes.IdentExpr)
            and node.obj.name in gen._param_struct_types
            and node.member in gen.struct_field_types.get(gen._param_struct_types[node.obj.name], {})):
        _pst = gen._param_struct_types[node.obj.name]
        _pt = f"{_pst} *"
        if ot != _pt:
            _ov_local = gen._ensure_local(ot, ov)
            _ip = gen._new_temp('int64_t')
            _np = gen._new_temp(_pt)
            gen._emit(f"  {_ip} = (int64_t){_ov_local};")
            gen._emit(f"  {_np} = ({_pt}){_ip};")
            ov = _np
            ot = _pt
        field_type = gen.struct_field_types[_pst][node.member]
        t = gen._new_val(field_type, f"{ov}->{gimple_ctypes._safe_field(node.member)}")
        # Propagate container element/value types onto the field-read temp,
        # exactly like the generic instance-field branch further below (its
        # `_field_elem_types`/`_field_dict_val_types` seeding at the
        # field_map hit). This early param-struct branch used to return
        # WITHOUT any propagation, so reading a List[String] field off a
        # struct-typed PARAMETER (`c.variables[i]` inside
        # `def set_variable(c: ComputerCase, ...)`) left _elem_types empty,
        # the subscript fell back to int64_t, and string elements came back
        # as raw boxed handles — box.3d/game's "set_variable then
        # get_variable returns 0" failures (BUG-2026-023 residual).
        if field_type == 'MojoList *':
            stored = gen._field_elem_types.get(_pst, {}).get(node.member)
            if stored:
                gen._elem_types[t] = stored
            dict_stored = gen._field_dict_val_types.get(_pst, {}).get(node.member)
            if dict_stored:
                gen._dict_val_types[t] = dict_stored
        elif field_type == 'MojoDict *':
            dict_stored = gen._field_dict_val_types.get(_pst, {}).get(node.member)
            if dict_stored:
                gen._dict_val_types[t] = dict_stored
        return field_type, t

    # If the object lowered to a C type name (class used as cls argument),
    # treat it as NULL — the method shouldn't use cls for value access
    if ov in gen.struct_field_types and ot == 'int64_t':
        null_tmp = gen._new_temp('int64_t')
        gen._emit(f"  {null_tmp} = (int64_t)0;  /* class ref {ov} as NULL */")
        ov = null_tmp


    # MojoList field name remapping: Mojo List uses _len/_capacity/elems; C MojoList uses len/cap/data
    _sn = gimple_exprtypes._struct_name_of(ot)
    if _sn == 'MojoList':
        _mojo_to_c = {'_len': 'len', '_capacity': 'cap', '_size': 'len', 'elems': 'data', '_data': 'data', 'cap': 'cap', 'len': 'len', 'data': 'data'}
        if node.member in _mojo_to_c:
            _c_field = _mojo_to_c[node.member]
            _ftype = 'int64_t' if _c_field in ('len', 'cap') else 'int64_t *'
            t = gen._new_val(_ftype, f"{ov}->{_c_field}")
            return _ftype, t

    # .address on any pointer type: UnsafePointer.address → the raw integer address
    if node.member == 'address' and ot.endswith(' *'):
        t = gen._new_val('int64_t', f"(int64_t){ov}")
        return 'int64_t', t

    # `x._mlir_value` unwraps a scalar newtype (Int/UInt over an __mlir_type)
    # to its underlying MLIR value — at the C level that is the scalar itself,
    # so pass the operand through unchanged. Only for already-scalar operands:
    # struct-typed values (Bool*, SIMD*) keep their existing member handling.
    if node.member == '_mlir_value' and not (ot.endswith(' *') and gimple_exprtypes._struct_name_of(ot) in gen.struct_field_types):
        return ot, ov

    # .value on char * (StringLiteral.value, kgen.string.value) → identity, the string itself
    if node.member == 'value' and ot == 'char *':
        t = gen._new_val('char *', f"{ov}")
        return 'char *', t

    # .value on void * or function pointer (DType/bracket-param typed as builtin 'type')
    # → extract the integer value. This handles e.g. `type.value` where `type` is a
    # bracket param of type `TraceCategory` that got lowered to a function pointer.
    # IMPORTANT (A5 part 2): a boxed AST-node handle's `.value` (IntLiteral.value,
    # Token.value, ReturnStmt.value, ...) is a REAL struct field, not an identity —
    # reading it as identity here returned the node handle itself (self-host bug:
    # `_lower_IntLiteral` compared `node` against INT64_MAX and formatted the handle
    # as the literal value). Only take the identity shortcut when the receiver
    # really IS the value (a void*/function-pointer-typed type/bracket param, or a
    # receiver whose `.value` is a field of no known struct); otherwise fall through
    # to the runtime tag dispatch below, which reads the field directly.
    if node.member == 'value' and ot in ('void *', 'int64_t', 'int'):
        if ot == 'void *' or not gen._is_known_field('value'):
            t = gen._new_temp('int64_t')
            if ot == 'void *':
                vt = gen._new_val('int64_t', f"(int64_t){ov}")
                gen._emit(f"  {t} = {vt};")
            else:
                gen._emit(f"  {t} = (int64_t){ov};")
            return 'int64_t', t

    # Special handling for .__name__ on type objects
    if node.member == '__name__':
        # `type(node).__name__` — the type()-call receiver. This is the
        # dispatch chokepoint for every compiled AST walker
        # (gimple_codegen's gen_stmt/_EXPR_DISPATCH and the interpreter's
        # execute_{TypeName}) — the OLD stub returned the literal "<type>"
        # for every node, so `_STMT_DISPATCH.get("<type>")` found no
        # handler and the compiled binary emitted `/* TODO: <type> */` for
        # EVERY statement: no function body could ever be codegen'd by the
        # self-hosted backend. Resolve the real struct name from the
        # runtime type tag instead (type() below lowers to
        # mojo_read_type_tag_safe; _mojo_type_name maps tag → struct name
        # using the same _struct_type_id hash as the alloc sites).
        if isinstance(node.obj, gimple_ctypes.CallExpr) and isinstance(node.obj.func, gimple_ctypes.IdentExpr) \
                and node.obj.func.name == 'type' and node.obj.args:
            # node.obj (`type(x)`) was already lowered above to ov = the
            # runtime type tag; map it to the struct name.
            ov64 = gen._new_val('int64_t', f"(int64_t){ov}")
            t = gen._new_val('char *', f"_mojo_type_name ({ov64})")
            gen._needs_type_name_table = True
            return 'char *', t
        struct_name_check = gimple_exprtypes._struct_name_of(ot)
        if struct_name_check not in gen.struct_field_types:
            # `f.__name__` on an opaque value (Sub-case A/B) or one of
            # this codegen's own fixed-layout runtime structs (Sub-case
            # C — MojoBoundMethod is the confirmed real case: a closure
            # value with a dynamically-set `__name__`, see bugs/hard/
            # CODEGEN_dynamic_attribute_on_generic_object.md) — route
            # through the same dynamic-attribute dispatch used for any
            # other not-a-real-field member, instead of the unconditional
            # "<type>" placeholder below (which would silently discard
            # whatever `__name__` was actually, explicitly set to via
            # `inner.__name__ = "..."` — confirmed via Tools/scripts/
            # var_access_benchmark.py). The "<type>" stub is preserved
            # for every OTHER not-in-struct_field_types case (its
            # original purpose: the `type(x).__name__`-shaped AST-walker
            # dispatch chokepoint documented just above).
            if ot in ('int', 'int64_t', 'void *') or struct_name_check in gimple_ctypes._FIXED_RUNTIME_STRUCT_NAMES:
                vp = gen._new_val('void *', f'(void *){ov}' if ot != 'void *' else ov)
                raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                                [('void *', vp), ('char *', '"__name__"')])
                # `__name__` is always conceptually a string — cast the
                # generic boxed-int64_t dispatch result back to char *
                # (mirrors the `_boxed_ft` cast-back pattern the plain
                # opaque-getattr call sites use just below in this same
                # function), so `print(f.__name__)` sees the real string
                # rather than its raw pointer bits as a number.
                t = gen._new_val('char *', f'(char *){raw}')
                return 'char *', t
            t = gen._new_temp('char *')
            gen._emit(f'  {t} = {gen._intern_string("<type>")};  /* {ot}.__name__ stubbed */')
            return 'char *', t

    # Special handling for .__dict__ on int objects (node variable)
    if node.member == '__dict__' and ot == 'int':
        return gen._stub_result('int', '0', '__dict__ stub')

    # `x.__class__` used as a plain value (not the `is`/`is not` pattern
    # `_lower_binary` special-cases before ever reaching here — see there
    # for why that pattern needs its own early intercept). E.g.
    # `_pyrepl/completing_reader.py`'s `r.last_command_is(self.__class__)`
    # passes it as a normal argument. `__class__` isn't a real field —
    # falling through to the generic struct-field lookup below would
    # either register a bogus phantom field or hit the "unknown field"
    # fallback and emit an invalid raw `->__class__` C access. Lower it
    # to the object's runtime type tag (see mojo_read_type_tag in
    # runtime/mojo_runtime.c and _struct_type_id above) — the same
    # value identity comparisons against a class name already use, so
    # code that stores/compares `__class__` values (not just `is`
    # against a literal class name) keeps working.
    if node.member == '__class__':
        if ot == 'int64_t':
            addr = ov
        else:
            addr = gen._new_val('int64_t', f'(int64_t){ov}')
        tag = gen._call_expr('int64_t', 'mojo_read_type_tag', [('int64_t', addr)])
        return 'int64_t', tag

    op = '->' if '*' in ot else '.'
    struct_name = gimple_exprtypes._struct_name_of(ot)
    # `obj.__dict__` on a value whose struct type is statically known
    # (Step 0 of bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md)
    # — a real MojoDict* view of the struct's OWN already-known fields,
    # matching Python's `obj.__dict__` semantics (distinct from the
    # Sub-cases A-C dynamic-storage problem that same doc's later steps
    # cover: those are for attributes that DON'T exist as real fields at
    # all; `__dict__` here is a read-out of fields that already do).
    # Scoped to `struct_name in self.struct_field_types` — a genuinely
    # known struct — so an opaque/generic receiver (int64_t, void *,
    # no known layout) falls through to whatever this expression would
    # otherwise resolve to instead of emitting a call for a struct type
    # `_mojo_dispatch_asdict` (only defined for reflect-eligible known
    # structs — see gen_module's "Generic reflection dispatch" block)
    # has no real per-field case for. Real-world instances: Tools/build/
    # umarshal.py and Tools/build/deepfreeze.py's `retval.__dict__`
    # where `retval: Code`.
    if node.member == '__dict__' and struct_name in gen.struct_field_types:
        gen._asdict_dispatch_needed.add(1)
        return 'MojoDict *', gen._call_expr(
            'MojoDict *', '_mojo_dispatch_asdict', [(ot, ov)])
    # Span/StringSlice's `mut` bracket-parameter isn't a real field of the
    # erased fat-pointer struct (see struct_field_types['Span'] and
    # _param_ctype's _span_mut_params bookkeeping) — resolve it from the
    # literal recorded at the binding site instead of falling through to
    # the generic "unknown struct field" fallback below, which would
    # otherwise emit an invalid `->mut` access.
    if node.member == 'mut' and struct_name == 'Span' and isinstance(node.obj, gimple_ctypes.IdentExpr):
        mv = gen._span_mut_params.get(node.obj.name)
        if mv is not None:
            # GIMPLE strict mode: a bare nonzero integer constant is typed
            # 'int', and assigning it to a _Bool without an explicit cast
            # is a 'non-trivial conversion in integer_cst' error (same
            # reason _new_val special-cases int64_t constants).
            return '_Bool', gen._new_val('_Bool', '(_Bool)1' if mv else '(_Bool)0')
    field_map = gen.struct_field_types.get(struct_name, {})
    # pathlib.Path attribute reads on a value this codegen represents as
    # its char* path string. A Path-representing value reaches here as a
    # plain `char *` (the single-string-argument opaque-constructor
    # passthrough — see _lower_opaque_ctor's char*-identity case, the same
    # strings-as-path-values convention that already lowers `/` on char*
    # receivers to mojo_path_join). `.name` is os.path.basename and
    # `.parent` is os.path.dirname — both real runtime helpers this table
    # already shares with the os.path call sites (int64_t_basename/
    # int_dirname). Scoped to EXACTLY ot == 'char *' so a boxed struct
    # handle (int64_t/void *) reading its genuine `.name` FIELD still goes
    # through the struct-handle-aware paths below (_resolved_field /
    # _known_field_type / runtime tag dispatch) unchanged; those never
    # have a static 'char *' type. Before these cases, both reads fell to
    # the generic dynamic-getattr dispatch, which has no string-attribute
    # model and raised a fatal `AttributeError: name` at runtime (real:
    # Apple/__main__.py's module level `SCRIPT_NAME = Path(__file__).name`,
    # which crashed the whole program before main() ran).
    if ot == 'char *' and node.member in ('name', 'parent'):
        if node.member == 'name':
            return 'char *', gen._call_expr('char *', 'int64_t_basename',
                                            [('char *', ov)])
        dn = gen._call_expr('int64_t', 'int_dirname',
                            [('int64_t', '0'), ('char *', ov)])
        return 'char *', gen._new_val('char *', f"(char *){dn}")
    if node.member in field_map:
        field_type = field_map[node.member]
        t = gen._new_val(field_type, f'{ov}{op}{gimple_ctypes._safe_field(node.member)}')
        # Propagate element/dict-val type from stored field metadata so
        # subscript/iteration later recovers the right element type instead
        # of defaulting to int64_t (see BUG-2026-044).
        if field_type == 'MojoList *':
            stored = gen._field_elem_types.get(struct_name, {}).get(node.member)
            if stored:
                gen._elem_types[t] = stored
            # Also propagate dict value type for list-of-dicts fields
            dict_stored = gen._field_dict_val_types.get(struct_name, {}).get(node.member)
            if dict_stored:
                gen._dict_val_types[t] = dict_stored
        elif field_type == 'MojoDict *':
            stored = gen._field_dict_val_types.get(struct_name, {}).get(node.member)
            if stored:
                gen._dict_val_types[t] = stored
            elif node.member in gen._dict_val_types:
                # Annotation-seeded value type (e.g. `self._str_pool:
                # dict[str, str]`) — carry it onto the field-read temp so
                # `.items()`/`d[k]` on the field pick the right accessor.
                gen._dict_val_types[t] = gen._dict_val_types[node.member]
        # Track struct field owner for container-type fields so that append
        # operations can propagate element type info back to _field_elem_types.
        if field_type in ('MojoList *', 'MojoDict *', 'MojoSet *') and isinstance(node.obj, gimple_ctypes.IdentExpr) \
                and node.obj.name == 'self' and struct_name in gen.struct_field_types:
            if t not in gen._struct_field_owners:
                gen._struct_field_owners[t] = []
            gen._struct_field_owners[t].append((struct_name, node.member))
        return field_type, t
    # A method referenced as a plain VALUE (not called here) — `f =
    # self.b`, `readline.set_completer(self.complete)` — rather than a
    # data field. _lower_struct_method_call already resolves `node.member`
    # fine when it's the callee of a CallExpr (`self.b(...)`); reaching
    # here means this MemberExpr is being lowered as an ordinary
    # expression VALUE instead, and `node.member` genuinely isn't a
    # field — falling through to the generic "unknown struct field"
    # handling below used to blindly emit an invalid `{ov}->{member}`
    # access (`'C' has no member named 'b'` from the C compiler; see
    # bugs/CODEGEN_bound_method_as_value_not_resolved.md). Recognize the
    # method case first and produce a real bound-method value instead.
    if struct_name in gen.struct_field_types and (
            f"{struct_name}_{node.member}" in gen.func_return_types
            or (struct_name, node.member) in gen._struct_method_signatures):
        return gen._lower_bound_method_value(struct_name, node.member, ot, ov)
    # A BUILTIN-container method referenced as a plain VALUE (`append =
    # l.append`) — the container twin of the user-struct case just above.
    # MojoList*/MojoDict*/MojoSet* have no per-method C symbol for a
    # MojoBoundMethod*'s fn pointer to point at (their methods are
    # lowered inline per call site), so the binding is recorded instead
    # and calls through it lower as direct container-method calls — see
    # _lower_builtin_method_value. Without this, the read fell through
    # to the generic runtime getattr below (_mojo_dispatch_getattr),
    # which raises AttributeError at runtime for every registered
    # container (gencodec.py's python_mapdef_code/python_tabledef_code
    # never produced any output).
    if ot in ('MojoList *', 'MojoDict *', 'MojoSet *'):
        return gen._lower_builtin_method_value(ot, ov, node.member)
    # Struct-level comptime alias (e.g. BitSet._words_size): not a physical
    # field — expand its defining expression with `Self`/the struct name
    # rebound to the accessed object, then lower that.
    aliases = gen._struct_comptime_aliases.get(struct_name)
    if aliases and node.member in aliases:
        val_ast = gen._subst_idents(aliases[node.member],
                                     {'Self': node.obj, struct_name: node.obj})
        return gen.lower_expr(val_ast)
    # Class-level attribute (not an instance field) — redirect to global variable
    class_attrs = gen._class_attrs
    if struct_name in class_attrs and node.member in class_attrs[struct_name]:
        gname = class_attrs[struct_name][node.member]
        # Use the actual declared type of the global (stored in _global_var_types)
        gtype = gen._global_var_types.get(gname, 'int64_t')
        t = gen._new_val(gtype, f'{gname}')
        return gtype, t
    elif struct_name in gen.struct_field_types and ot.endswith(' *'):
        # The struct defines its own `__getattr__` (compiled body ⇒ bare
        # `{Struct}___getattr__` key in func_return_types, or an overload
        # registered under the (struct, method) signature table): real
        # Python semantics route ANY attribute miss through it — this is
        # the whole point of ctypes's LibraryLoader (`cdll.msvcrt` = load
        # that DLL; any attribute is meaningful precisely because
        # __getattr__ says so), typing's _LazyAnnotationLib, and every
        # other delegation idiom. Call the compiled method directly with
        # (receiver, attr-name) and return its boxed int64_t — the same
        # value shape _mojo_dispatch_getattr below would produce, so all
        # downstream consumers behave identically. Only fires on a genuine
        # COMPILED `__getattr__`; structs without one keep the existing
        # runtime-dispatch behavior unchanged, and dunder reads
        # (`obj.__class__`-style) are excluded — Python only consults
        # __getattr__ after normal lookup fails, and dunder lookups hit
        # the type first, so intercepting them here would change more
        # existing behavior than it fixes. Scope note: this covers MEMBER
        # READS as values; a CALL through a dynamically-resolved attribute
        # (`cdll.some_factory(args)`) where `some_factory` is not itself a
        # compiled method still routes to the runtime dispatch paths.
        if (not (node.member.startswith('__') and node.member.endswith('__'))
                and ((f"{struct_name}_{gimple_ctypes._safe_name('__getattr__')}"
                      in gen.func_return_types)
                     or (struct_name, '__getattr__') in gen._struct_method_signatures)):
            _ga_csym = gen._struct_method_csym(struct_name, '__getattr__', '')
            # The method's own Pass-2a-inferred return type (the bare
            # `{Struct}___getattr__` key) — NOT a hardcoded boxed int64_t.
            # LibraryLoader.__getattr__ returns whatever `self._dlltype
            # (name)` yields (a char * here), and hardcoding int64_t made
            # print() pick its integer formatting for what is really a C
            # string ("4370922960" instead of the loaded library's name).
            _ga_ret = gen.func_return_types.get(
                f"{struct_name}_{gimple_ctypes._safe_name('__getattr__')}",
                'int64_t')
            _ga_attr = gen._new_val('char *', f'"{node.member}"')
            raw = gen._call_expr(_ga_ret, _ga_csym,
                                  [(ot, ov), ('char *', _ga_attr)])
            return _ga_ret, raw
        # Known struct type but unknown field. `ot` here can be WRONG:
        # whole-function return-type inference unifies to ONE dominant
        # concrete type even for a variable that legitimately holds many
        # different AST-node subtypes across its callers (e.g. `expr =
        # self._parse_expr_or_yield()` infers `YieldExpr *`, even though
        # `_parse_expr_or_yield` can return ANY expression kind — real,
        # in mojo_compiler.py's own `Parser._parse_stmt`). The OLD
        # fallback here guessed "the first OTHER struct that happens to
        # have a field with this name" and blindly cast to it — UNSOUND,
        # since different structs' shared field names sit at DIFFERENT
        # offsets (VarDecl/IdentExpr have `name` at 0x18, MojoClass at
        # 0x30, FunctionDef at 0x48): a genuinely-IdentExpr object read
        # through a MojoClass-shaped cast reads memory that isn't even
        # part of this object's own allocation. Root-caused via
        # A5-BUG.md's VarDecl.name corruption hunt — `if isinstance(expr,
        # IdentExpr): name = expr.name` produced a small integer instead
        # of a string, nondeterministically (nothing about WHICH wrong
        # struct got picked depends on the actual runtime object, only on
        # dict-iteration order over every struct this compile has ever
        # seen). Use the same RUNTIME type-tag dispatch the ambiguous-
        # boxed-int64_t case below already relies on instead of a
        # compile-time guess — it doesn't need `ot` to be right at all,
        # only the object's own tag to be one of the registered structs.
        vp = gen._new_val('void *', f'(void *){ov}')
        _boxed_ft = gen._known_field_type(node.member)
        raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                              [('void *', vp), ('char *', f'"{node.member}"')])
        if _boxed_ft is not None and _boxed_ft != 'int64_t':
            if _boxed_ft.endswith(' *'):
                t = gen._new_val(_boxed_ft, f'({_boxed_ft}){raw}')
            else:
                t = gen._new_temp(_boxed_ft)
                gen._emit(f"  {t} = ({_boxed_ft}){raw};")
            return _boxed_ft, t
        return 'int64_t', raw
    elif ot in ('int', 'int64_t', 'void *', 'char *') or ot in ('MojoList *', 'MojoDict *', 'MojoSet *', 'MojoStr *'):
        # Opaque Python object typed as int, void *, or built-in container — use runtime attribute accessor
        # GIMPLE requires function args to be simple vars, not cast expressions
        # A genuine 4-byte 'int' (as opposed to the 8-byte int64_t most
        # producers actually emit under this same 'int' type tag) is a
        # real -Wint-to-pointer-cast size mismatch when boxed directly —
        # widen through int64_t first, same as every other narrow-source
        # pointer cast in this file.
        # Try to resolve the actual struct type first: if ov is known to
        # hold a struct pointer (from _actual_types) and the struct has
        # this field in struct_field_types, use direct field access instead
        # of the runtime dispatch (which loses type info and forces int64_t
        # return, breaking string comparisons downstream).
        _resolved_field = None
        if ov in gen._actual_types:
            _actual_sn = gimple_exprtypes._struct_name_of(gen._actual_types[ov])
            if _actual_sn in gen.struct_field_types and node.member in gen.struct_field_types[_actual_sn]:
                _resolved_field = gen.struct_field_types[_actual_sn][node.member]
        if _resolved_field is not None:
            _ptr = gen._new_val(gen._actual_types[ov], f'({gen._actual_types[ov]}){ov}')
            t = gen._new_val(_resolved_field, f'{_ptr}->{gimple_ctypes._safe_field(node.member)}')
            return _resolved_field, t
        # A5 part 2: boxed handle to a known AST/compiler struct — `node.member`
        # is a REAL field of at least one struct in struct_field_types (IfStmt.
        # condition, BinaryOp.left, IntLiteral.value, IfStmt.then_body, ...).
        # The runtime _mojo_dispatch_getattr reads the field directly through the
        # struct's typedef (`((IfStmt*)obj)->condition`), but returns it boxed as
        # int64_t, which loses the field's static C type — downstream code then
        # mis-handles it (e.g. `for s in node.then_body` saw an opaque int64_t and
        # fell to mojo_unsupported_iter, so the if/else body never emitted; and a
        # char*-typed field (Token.value) stayed boxed). Resolve the field's C
        # type from struct_field_types and cast the dispatch result back through
        # it, so member access on a boxed AST handle carries the real type. When
        # the field's type is ambiguous across structs (e.g. `value`: int64_t in
        # ReturnStmt/ExprStmt but char* in Token, double in FloatLiteral), the
        # boxed int64_t default is kept (correct for the overwhelmingly common
        # boxed-expression/IntLiteral use).
        _boxed_ft = gen._known_field_type(node.member)
        if (_boxed_ft is None and gen._is_except_as_member_target(node.obj)
                and node.member in gen._except_attr_str_fields):
            # `err.filename` (a caught exception object's dynamically-set
            # attribute) — `_known_field_type` has no notion of dynamic
            # attributes, only real declared struct fields, so it's
            # always None here. `self._except_attr_str_fields` (populated
            # at the matching write site, `_emit_dynattr_setattr_
            # dispatch`) records which attribute names were actually
            # written as a string on SOME except-as-bound object; casting
            # the boxed result back to char * here is what makes
            # `print(err.filename)` show the real string instead of raw
            # pointer bits as a number. See `_is_except_as_member_target`
            # /bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
            # "Residual gap: caught exception objects" section.
            _boxed_ft = 'char *'
        if _boxed_ft is not None and _boxed_ft != 'int64_t':
            if ot in ('int', 'char'):
                ov = gen._new_val('int64_t', f'(int64_t){ov}')
            vp = gen._new_val('void *', f'(void *){ov}')
            # _call_expr (not a bare _emit of `"member"`) so the member-name
            # string literal goes through _emit_call's _slit conversion —
            # an inline `"kind"` C literal in a __GIMPLE body is lowered by
            # gcc to a plain INTEGER constant (the packed 4 bytes), not a
            # `const char *` to the string, so the dispatch would strcmp the
            # attribute against 0x646e696b ("kind" as an int) and crash.
            raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                                  [('void *', vp), ('char *', f'"{node.member}"')])
            if _boxed_ft.endswith(' *'):
                t = gen._new_val(_boxed_ft, f'({_boxed_ft}){raw}')
            else:
                t = gen._new_temp(_boxed_ft)
                gen._emit(f"  {t} = ({_boxed_ft}){raw};")
            return _boxed_ft, t
        if ot in ('int', 'char'):
            ov = gen._new_val('int64_t', f'(int64_t){ov}')
        vp = gen._new_val('void *', f'(void *){ov}')
        return 'int64_t', gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                        [('void *', vp), ('char *', f'"{node.member}"')])
    elif struct_name in gimple_ctypes._FIXED_RUNTIME_STRUCT_NAMES:
        # Step 4 (bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md):
        # `ot` resolved to one of THIS codegen's own fixed-layout runtime
        # structs (MojoBoundMethod, ...), and `node.member` isn't one of
        # its real, hardcoded C fields — the generic "Unknown struct
        # field" fallback just below would blindly emit `ov->member`,
        # which GCC rejects outright for a struct with no such member
        # ("'MojoBoundMethod' has no member named 'X'", the exact
        # confirmed failure this branch fixes). Route through the same
        # tag-dispatched runtime accessor the fully-opaque case above
        # uses instead — real per-object dynamic-attribute storage
        # (mojo_obj_getattr), not a direct field access.
        vp = gen._new_val('void *', f'(void *){ov}')
        return 'int64_t', gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                        [('void *', vp), ('char *', f'"{node.member}"')])
    else:
        # Unknown struct field — fall back to opaque int64_t.
        # This avoids StructName_field(...) dispatch for untracked fields
        # (e.g. errs.append(X) → TranspilerResult_append linker error).
        # int64_t enables the mojo_obj_call1 runtime-dispatch path.
        field_type = 'int64_t'
        if op == '->':
            # GIMPLE: declare separate temp to avoid inline cast in rvalue
            field_tmp = gen._new_temp('int64_t')
            gen._emit(f"  {field_tmp} = (int64_t){ov}{op}{gimple_ctypes._safe_field(node.member)};")
            t = field_tmp
        else:
            t = gen._new_val(field_type, f'{ov}{op}{gimple_ctypes._safe_field(node.member)}')
        return field_type, t


def _lower_binary(gen, node: gimple_ctypes.BinaryOp) -> tuple[str, str]:
    if node.op == ':=':
        vtype, vv = gen.lower_expr(node.right)
        if isinstance(node.left, gimple_ctypes.IdentExpr):
            nm = node.left.name
            if nm not in gen.var_types:
                gen._declare_var(nm, vtype)
                # Track that this variable holds this type for concatenation detection
                if vtype == 'char *':
                    gen._actual_types[nm] = 'char *'
            dst = gen.var_types[nm]
            gen._safe_coerce_emit(vtype, dst, vv, nm)
            # Update actual type tracking for string types
            if dst == 'int' and vtype == 'char *':
                gen._actual_types[nm] = 'char *'
            return dst, nm
        if isinstance(node.left, gimple_ctypes.MemberExpr):
            ot, ov = gen.lower_expr(node.left.obj)
            op = '->' if '*' in ot else '.'
            sn = gimple_exprtypes._struct_name_of(ot)
            field_type = gen.struct_field_types.get(sn, {}).get(node.left.member, vtype)
            gen._safe_coerce_emit(vtype, field_type, vv, f"{ov}{op}{node.left.member}")
            return field_type, vv
        if isinstance(node.left, gimple_ctypes.SubscriptExpr):
            ot, obj_v = gen.lower_expr(node.left.obj)
            _, idx_v = gen.lower_expr(node.left.index)
            if ot == 'MojoList *':
                elem = gen._elem_of(obj_v)
                suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
                idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                ev_cast = gen._cast_for_list(vtype, vv, suf)
                gen._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
            else:
                if not gen._emit_struct_subscript_write(obj_v, ot, idx_v, vv, vtype):
                    gen._emit(f"  {obj_v}[{idx_v}] = {vv};")
            return vtype, vv
        # Skip emitting comment to avoid GIMPLE global-passing issues
        return vtype, vv

    # `x.__class__ is SomeClass` / `is not` (e.g. _markupbase.ParserBase's
    # `if self.__class__ is ParserBase: raise ...` abstract-base guard).
    # `__class__` isn't a real field — evaluating it as one would either
    # register a bogus struct field or hit the generic "unknown field"
    # fallback and emit an invalid raw `->__class__` C access. Recognize
    # the pattern here, before either operand is lowered normally, and
    # rewrite it to the runtime type-tag comparison _isinstance_one_type
    # already uses for `isinstance()` — exact-type equality (not a
    # subclass-inclusive check), which is exactly `is`/`is not` semantics
    # on `__class__`.
    if node.op in ('is', 'is not'):
        def _class_member_and_name(a, b):
            if (isinstance(a, gimple_ctypes.MemberExpr) and a.member == '__class__'
                    and isinstance(b, gimple_ctypes.IdentExpr) and b.name in gen.struct_field_types):
                return a.obj, b.name
            return None
        pair = (_class_member_and_name(node.left, node.right)
                or _class_member_and_name(node.right, node.left))
        if pair is not None:
            obj_expr, type_name = pair
            obj_type, obj_val = gen.lower_expr(obj_expr)
            eq = gen._isinstance_one_type(obj_type, obj_val, type_name)
            if node.op == 'is not':
                neg = gen._new_val('_Bool', f'!{eq}')
                return '_Bool', neg
            return '_Bool', eq

    if node.op == '//':
        return gen._lower_floordiv(node)
    if node.op == '**':
        return gen._lower_pow(node)
    if node.op == '%':
        _pct = gen._lower_percent(node)
        if _pct is not None:
            return _pct
        # else: not a statically-known string format -- ordinary
        # numeric modulo; fall through to the generic path below,
        # which already emits GIMPLE `%` for int/float operands.
    if node.op == '@':
        return gen._lower_matmul(node)
    if node.op == 'in':
        return gen._lower_in_impl(node, negate=False)
    if node.op == 'not in':
        return gen._lower_in_impl(node, negate=True)

    if node.op in ('and', 'or'):
        # Real Python `and`/`or` return whichever OPERAND was selected, not
        # a bool — e.g. `x = os.environ.get('K') or os.path.expanduser('~/.gmojo')`
        # must yield the string, not True/False.
        #
        # Real branching, not a C `?:` built from two already-evaluated
        # operands: the previous lowering unconditionally evaluated BOTH
        # operands before selecting between the results — the same
        # eager-both-branches shape the ternary-expression fix addressed
        # (BACKLOG-CODEGEN.md §4d) — so `x = f() or g()` called g() even
        # when f() was truthy and any side effect (I/O, a function call)
        # in the untaken branch still happened; a real correctness bug,
        # not just wasted work. Mirrors _lower_TernaryExpr: the left
        # operand is always evaluated (needed to decide which branch to
        # take), but the right operand only gets evaluated in its own
        # basic block, reached only when actually needed. _quick_type
        # gives the right operand's C type without evaluating it, so the
        # merged result type is fixed before either branch runs.
        ltype, lval = gen.lower_expr(node.left)
        cond = gen._ensure_bool_cond(ltype, lval)
        res_type = gimple_ctypes.TypeLattice.join(ltype, gen._quick_type(node.right))
        result = gen._new_temp(res_type)
        bb_short = gen._new_bb()
        bb_eval_right = gen._new_bb()
        bb_merge = gen._new_bb()
        if node.op == 'and':
            # Left truthy -> right decides; left falsy -> short-circuit on left.
            gen._emit(f"  if ({cond}) goto {bb_eval_right}; else goto {bb_short};")
        else:
            # Left truthy -> short-circuit on left; left falsy -> right decides.
            gen._emit(f"  if ({cond}) goto {bb_short}; else goto {bb_eval_right};")
        gen._emit_label(bb_short)
        gen._safe_coerce_emit(ltype, res_type, lval, result)
        gen._emit(f"  goto {bb_merge};")
        gen._emit_label(bb_eval_right)
        rtype, rval = gen.lower_expr(node.right)
        gen._safe_coerce_emit(rtype, res_type, rval, result)
        gen._emit(f"  goto {bb_merge};")
        gen._emit_label(bb_merge)
        return res_type, result

    # `s[a:b] == needle` / `!= needle` (either operand order): call
    # mojo_cstr_region_eq directly instead of the generic
    # slice-then-compare lowering, which would materialize the slice via
    # mojo_cstr_slice (malloc + memcpy) just to immediately strcmp it
    # away. Profiled as ~90% of ALL runtime in the exact scanning-loop
    # shape (`while ... src[j:j+3] != quote3:`) that motivated this -
    # see mojo_cstr_region_eq's comment in runtime/mojo_runtime.c.
    # Scoped tightly (plain char* slice target, no step, other operand a
    # plain char*) so it only ever fires for the shape it was measured
    # against, not a broad speculative rewrite of slice comparisons.
    if node.op in ('==', '!=') and isinstance(node.left, gimple_ctypes.SliceExpr) and node.left.step is None:
        fast = gen._try_lower_slice_region_eq(node.left, node.right, negate=(node.op == '!='))
        if fast is not None:
            return fast
    if node.op in ('==', '!=') and isinstance(node.right, gimple_ctypes.SliceExpr) and node.right.step is None:
        fast = gen._try_lower_slice_region_eq(node.right, node.left, negate=(node.op == '!='))
        if fast is not None:
            return fast

    lt, lv = gen.lower_expr(node.left)
    rt, rv = gen.lower_expr(node.right)

    # `x.prop OP y` (or `y OP x.prop`) where `prop` is a 0-arg
    # property/method accessed without call syntax lowers to a
    # deferred, uncalled `MojoBoundMethod *` value (see
    # _lower_bound_method_value) — correct when the consuming context
    # is itself a call (`self.prop()`) or the value is being passed
    # around as a first-class callable, but a BINARY OPERATOR is
    # never that: real Python (and, for a `@property` specifically,
    # the entire point of the decorator) auto-invokes the getter
    # FIRST and only then applies the operator to its return value.
    # Left unhandled, arithmetic ops (`+`/`-`) fell into the generic
    # raw-pointer-arithmetic fallback further below (treating the
    # bound-method pointer as an array base pointer via the
    # `_mojo_at_<T>` scaled-offset helper — a genuine GCC `-fgimple`
    # frontend internal compiler error, "internal compiler error: in
    # build2", since a `MojoBoundMethod *` has no such element shape)
    # and comparison ops just cast the raw bound-method POINTER to
    # int64_t and compared THAT — silently wrong runtime values, no
    # compile error. `is`/`is not` are deliberately excluded: those
    # are the one case where comparing the callable's IDENTITY (not
    # its invoked value) is the plausible intended semantics (e.g.
    # `self.callback is None`), mirroring how this representation
    # already has no notion of `@property` vs. an ordinary bound
    # method to disambiguate the two intents. Mirrors the identical
    # fix already applied to _lower_subscript's `self.prop[key]` and
    # the MemberExpr chain's `self.prop.attr` (see those comments /
    # bugs/COMPILE_FAIL_zipfile__path___init__.md) — this is the
    # third and, with `is`/`is not` excluded, final direct-consumer
    # context that had no such handling. Found via Tools/
    # cases_generator/cwriter.py's CWriter.set_position: `gap =
    # tkn.column - self.last_token.end_column` (both `Token`
    # `@property`s, `tkn`'s static type only resolvable once the
    # full `lexer.py` import closure is compiled alongside it — the
    # standalone single-file build never hit this since `tkn` fell
    # back to an opaque type there instead).
    if node.op not in ('is', 'is not'):
        if lt == 'MojoBoundMethod *':
            lt, lv = gmp._auto_invoke_bound_method_value(gen, lv)
        if rt == 'MojoBoundMethod *':
            rt, rv = gmp._auto_invoke_bound_method_value(gen, rv)

    return gen._lower_binary_tail(node.op, node.left, lt, lv, node.right, rt, rv)


def _lower_binary_tail(gen, op: str, left_node, lt: str, lv: str,
                        right_node, rt: str, rv: str) -> tuple[str, str]:
    """The rest of BinaryOp lowering once both operands are already
    evaluated (lt/lv, rt/rv). Every case below dispatches purely on
    `op` and the two operand (type, value) pairs — left_node/right_node
    are used only for isinstance() shape-sniffing (e.g. "is this
    operand a string literal"), never to re-evaluate them. Split out of
    _lower_binary so _lower_compare_chain (Python chained comparisons,
    `a < b < c`) can reuse this exact per-link comparison logic while
    still guaranteeing each shared operand is evaluated exactly once —
    re-lowering left_node/right_node here would break that guarantee
    for a side-effecting comparand shared between two links."""
    # A list local may be boxed as int64_t (the slice pre-pass hint is the
    # machine word when the sliced object's type isn't yet known); _actual_types
    # records the real MojoList*. Resolve through it so list+list still concats.
    alt = gen._actual_types.get(lv, gen.var_types.get(lv, lt))
    art = gen._actual_types.get(rv, gen.var_types.get(rv, rt))
    if op == '+' and alt == 'MojoList *' and art == 'MojoList *':
        lcast = lv if lt == 'MojoList *' else gen._new_temp('MojoList *')
        if lt != 'MojoList *': gen._emit(f"  {lcast} = (MojoList *){lv};")
        rcast = rv if rt == 'MojoList *' else gen._new_temp('MojoList *')
        if rt != 'MojoList *': gen._emit(f"  {rcast} = (MojoList *){rv};")
        t = gen._new_val('MojoList *', f"mojo_list_concat ({lcast}, {rcast})")
        if lcast in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[lcast]
        return 'MojoList *', t

    # MojoList + MojoList → mojo_list_concat
    if op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
        t = gen._new_val('MojoList *', f"mojo_list_concat ({lv}, {rv})")
        if lv in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[lv]
        return 'MojoList *', t

    # MojoList * + int/int64_t → identity (DynamicVector not supported; treat as no-op)
    if op == '+' and lt == 'MojoList *' and rt in ('int', 'int64_t'):
        return 'MojoList *', lv

    # MojoList * + <pointer-ish> → mojo_list_concat after casting the RHS to
    # MojoList *. Covers polymorphic locals: a name (e.g. `body`) that is a
    # list in one branch but declared `char *` because another branch assigns
    # it a string. At a list-concat site the runtime value *is* a list, so
    # concat is the correct lowering; without this we emit `MojoList * + char *`,
    # which gcc rejects. (Salvaged from the bootstrap bug-hunt; it advances the
    # self-host build past mojo_compiler.py's emit().)
    if op == '+' and lt == 'MojoList *' and rt.endswith(' *'):
        rcast = rv
        if rt != 'MojoList *':
            rcast = gen._new_val('MojoList *', f"(MojoList *){rv}")
        t = gen._new_val('MojoList *', f"mojo_list_concat ({lv}, {rcast})")
        if lv in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[lv]
        return 'MojoList *', t

    # <opaque int64_t> + MojoList * → mojo_list_concat. The MIRROR of the
    # two cases above, for when it's the LEFT side whose type was lost:
    # `path + [fname]` in ast_rewriter.py, where `path` is an untyped
    # (boxed int64_t) parameter and the right side is a list literal.
    # Adding a list to an integer is never meaningful arithmetic, so a
    # MojoList* on either side makes this unambiguously a concat — without
    # it we emitted a literal `path + _t38`, i.e. pointer arithmetic on a
    # boxed handle, producing a garbage list that faulted later in
    # mojo_str_join (A5-BUG.md section 1's bootstrap failure).
    if op == '+' and rt == 'MojoList *' and lt in ('int', 'int64_t', 'void *'):
        lcast = gen._new_val('MojoList *', f"(MojoList *){lv}")
        t = gen._new_val('MojoList *', f"mojo_list_concat ({lcast}, {rv})")
        if rv in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[rv]
        return 'MojoList *', t

    # MojoStr + MojoStr → mojo_str_concat
    if op == '+' and lt == 'MojoStr *' and rt == 'MojoStr *':
        t = gen._new_val('MojoStr *', f"mojo_str_concat ({lv}, {rv})")
        return 'MojoStr *', t

    # char * + char * → mojo_str_cat (including int64_t holding char* via actual_types)
    # Also handle int + char * when int is likely a string pointer
    def _as_charptr(typ, val, is_string_literal=False):
        if typ == 'char *':
            return 'char *', val
        # Check if actual type is char*
        actual = gen._actual_types.get(val)
        if actual == 'char *':
            cp = gen._new_temp('char *')
            ip = gen._new_val('int64_t', f"(int64_t){val}")
            gen._emit(f"  {cp} = (char *){ip};")
            return 'char *', cp
        # If one operand is definitely a string literal, treat int as potential string
        if is_string_literal and typ in ('int', 'int64_t') and val.startswith('_slit_'):
            cp = gen._new_temp('char *')
            ip = gen._new_val('int64_t', f"(int64_t){val}")
            gen._emit(f"  {cp} = (char *){ip};")
            return 'char *', cp
        return typ, val
    if op == '+':
        # Check if the OTHER operand is a string literal - helps identify string concatenation
        right_is_lit = isinstance(right_node, gimple_ctypes.StringLiteral)
        left_is_lit = isinstance(left_node, gimple_ctypes.StringLiteral)
        lt2, lv2 = _as_charptr(lt, lv, is_string_literal=right_is_lit)
        rt2, rv2 = _as_charptr(rt, rv, is_string_literal=left_is_lit)
        if lt2 == 'char *' and rt2 == 'char *':
            t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv2), ('char *', rv2)])
            return 'char *', t
        # int/int64_t + char* or char* + int/int64_t when one side is a string literal
        # → this is Python string concatenation where one operand is a string stored as int
        if right_is_lit and rt == 'char *' and lt in ('int', 'int64_t'):
            ip = gen._new_temp('int64_t')
            cp = gen._new_temp('char *')
            gen._emit(f'  {ip} = (int64_t){lv};')
            gen._emit(f'  {cp} = (char *){ip};')
            t = gen._call_expr('char *', 'mojo_str_cat', [('char *', cp), ('char *', rv)])
            return 'char *', t
        if left_is_lit and lt == 'char *' and rt in ('int', 'int64_t'):
            ip = gen._new_temp('int64_t')
            cp = gen._new_temp('char *')
            gen._emit(f'  {ip} = (int64_t){rv};')
            gen._emit(f'  {cp} = (char *){ip};')
            t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', cp)])
            return 'char *', t
        # String + numeric (or numeric + String) where the numeric is a real
        # value, not a string-stored-as-int. This is String concatenation with
        # an Int; emitting `char* + int` as C arithmetic is invalid and ICEs
        # gcc's build2. Stringify the numeric operand and concatenate.
        # EXCEPTION: an operand whose _actual_types says 'char' came from
        # string indexing (`ch = text[i]`) with its storage widened to
        # int64_t by Pass 1.3b joining — that is a 1-CHARACTER STRING by
        # dialect semantics (see _lower_list_method append's identical
        # recovery), so concatenate via mojo_char_to_str, NOT
        # mojo_str_from_int (which appended the decimal BYTE CODE:
        # box.3d/game's ComputerMonitor.print_text turned "Hello, World!"
        # into "72101108111144...").
        if lt2 == 'char *' and rt2 in ('int', 'int64_t', '_Bool'):
            if gen._actual_types.get(rv2) == 'char':
                sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', rv2)])
            else:
                nv = gen._to_int64(rt2, rv2)
                sv = gen._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
            return 'char *', gen._call_expr('char *', 'mojo_str_cat', [('char *', lv2), ('char *', sv)])
        if rt2 == 'char *' and lt2 in ('int', 'int64_t', '_Bool'):
            if gen._actual_types.get(lv2) == 'char':
                sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', lv2)])
            else:
                nv = gen._to_int64(lt2, lv2)
                sv = gen._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
            return 'char *', gen._call_expr('char *', 'mojo_str_cat', [('char *', sv), ('char *', rv2)])

    # char * * int → string repetition (e.g., "  " * 3). Also accepts a
    # _Bool RHS ('s' * (n != 1), Python's common boolean-as-0/1
    # pluralization idiom — err_count != 1 IS a real bool operand, not
    # an int literal, so it previously missed this dispatch entirely
    # and fell through to plain numeric `*`, "invalid operands to
    # binary * (have 'char *' and 'int')" — found via Doc/tools/
    # check-epub.py's `s = 's' * (err_count != 1)`).
    if op == '*' and lt == 'char *' and rt in ('int', 'int64_t', 'uint64_t', '_Bool'):
        t = gen._new_temp('char *')
        lv_local = gen._ensure_local(lt, lv)
        rv64 = gen._to_int64(rt, rv)
        gen._emit(f"  {t} = mojo_cstr_repeat ({lv_local}, {rv64});")
        return 'char *', t

    # int * char * → string repetition (flipped order)
    if op == '*' and lt in ('int', 'int64_t', 'uint64_t', '_Bool') and rt == 'char *':
        t = gen._new_temp('char *')
        rv_local = gen._ensure_local(rt, rv)
        lv64 = gen._to_int64(lt, lv)
        gen._emit(f"  {t} = mojo_cstr_repeat ({rv_local}, {lv64});")
        return 'char *', t

    # bare `char` * int → string repetition, e.g. `c * 3` where c is a
    # single Python character (str of length 1, represented as a raw C
    # `char` rather than `char *` for cheap comparisons elsewhere).
    # Python has no numeric-char type distinct from a length-1 str, so
    # every `char` here originates from string indexing/slicing and
    # `char * int` always means repetition, never arithmetic - without
    # this case it silently fell through to plain numeric multiplication
    # (treating the char as its byte value), producing a nonsense result
    # (confirmed: mojo_compiler.py's own py_tokenize's
    # replace_multiline_strings does `quote3 = c * 3` to build '"""'/
    # "'''" for triple-quote detection; miscompiling this as arithmetic
    # meant triple-quoted strings/docstrings were never recognized at
    # all when this file compiles itself, cascading into a severe
    # performance blowup during self-hosted `--dump-full` of mojo.py).
    if op == '*' and lt == 'char' and rt in ('int', 'int64_t', 'uint64_t', '_Bool'):
        sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', lv)])
        t = gen._new_temp('char *')
        rv64 = gen._to_int64(rt, rv)
        gen._emit(f"  {t} = mojo_cstr_repeat ({sv}, {rv64});")
        return 'char *', t

    # int * bare `char` → string repetition (flipped order)
    if op == '*' and lt in ('int', 'int64_t', 'uint64_t', '_Bool') and rt == 'char':
        sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', rv)])
        t = gen._new_temp('char *')
        lv64 = gen._to_int64(lt, lv)
        gen._emit(f"  {t} = mojo_cstr_repeat ({sv}, {lv64});")
        return 'char *', t

    # MojoList * * int → list repetition (e.g., [0] * n)
    if op == '*' and lt == 'MojoList *' and rt in ('int', 'int64_t', 'uint64_t'):
        cnt = gen._new_val('int64_t', f"(int64_t){rv}")
        t = gen._call_expr('MojoList *', 'mojo_list_repeat', [('MojoList *', lv), ('int64_t', cnt)])
        return 'MojoList *', t

    # MojoStr == / != → mojo_str_eq
    if op in ('==', '!=') and lt == 'MojoStr *' and rt == 'MojoStr *':
        eq_t = gen._new_val('int', f"mojo_str_eq ({lv}, {rv})")
        t = gen._new_temp('_Bool')
        cmp = '!= 0' if op == '==' else '== 0'
        gen._emit(f"  {t} = {eq_t} {cmp};")
        return '_Bool', t

    # String equality: char*, int64_t-stored-char*, or string literals → strcmp
    rv_is_str_lit = isinstance(right_node, gimple_ctypes.StringLiteral)
    lv_is_str_lit = isinstance(left_node, gimple_ctypes.StringLiteral)
    if op in ('==', '!='):
        uses_str = (lt == 'char *' or rt == 'char *' or rv_is_str_lit or lv_is_str_lit or
                    (lt == 'int64_t' and (rv_is_str_lit or rt == 'char *')) or
                    (rt == 'int64_t' and (lv_is_str_lit or lt == 'char *')))
        if uses_str:
            def _to_char_star(typ, var, is_other_str_lit=False):
                if typ == 'char *':
                    t2 = gen._new_temp('char *'); gen._emit(f'  {t2} = {var};'); return t2
                # A raw single character (real C 'char', or an 'int'/'int64_t'
                # holding a small ASCII code with no tracked pointer identity)
                # is a distinct representation from a char*-boxed-as-int64_t
                # pointer — reinterpreting its numeric byte value as a
                # pointer produces a garbage address (e.g. 0x22 for '"').
                # Build a real 1-char string instead, mirroring the same fix
                # in _cast_for_list ('in' lowering). Found via
                # mojo_compiler.py's own `c == "\\"` (c from `s[i]`).
                # BUT: when the OTHER operand is a string literal (detected
                # by the caller via _is_str_lit), an UNTRACKED int64_t is
                # assumed to be a char*-boxed pointer, not a character
                # code — use direct pointer cast instead of the
                # character-to-string path (BUG-2026-048). That's only a
                # fallback guess for when nothing is actually known,
                # though — if _actual_types explicitly tracked this
                # variable as 'char' (see _track_pointer_actual_type),
                # that's direct evidence, not a guess, and must win
                # regardless of is_other_str_lit: mojo_compiler.py's own
                # `first = rest[0]; ... if first == '"' or first == "'":`
                # in _strip_string_prefix_and_quotes has `first` declared
                # int64_t (widened joining another assignment site) but
                # explicitly _actual_types-tracked as 'char' — the old
                # blanket "is_other_str_lit means pointer" skipped that
                # tracked evidence entirely, reinterpreting the quote
                # character's byte value as a garbage pointer and calling
                # mojo_cstr_cmp on it — corrupting every self-hosted
                # string literal whose content starts/ends with a quote
                # (found chasing make bootstrap's verify byte-identity
                # failures back to their real, non-cosmetic root cause).
                actual = gen._actual_types.get(var)
                is_tracked_char = (actual == 'char')
                if typ == 'char' or is_tracked_char or (
                        not is_other_str_lit and typ in ('int', 'int64_t')
                        and not (actual and actual.endswith(' *'))):
                    cv = var if typ == 'char' else gen._new_val('char', f'(char){var}')
                    return gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
                ip = gen._new_val('int64_t', f'(int64_t){var}')
                cp = gen._new_val('char *', f'(char *){ip}')
                return cp
            ls = _to_char_star(lt, lv, rv_is_str_lit)
            rs = _to_char_star(rt, rv, lv_is_str_lit)
            eq_t = gen._call_expr('int', 'mojo_cstr_cmp', [('char *', ls), ('char *', rs)])
            t = gen._new_temp('_Bool')
            cmp = '== 0' if op == '==' else '!= 0'
            gen._emit(f'  {t} = {eq_t} {cmp};')
            return '_Bool', t


    # String ORDERING comparisons (`c >= "A"`, `name < "M"`, ...). Only
    # ==/!= had strcmp-based handling; <,>,<=,>= fell through to the
    # generic numeric-compare tail, which pointer-cast both char* operands
    # to int64_t and compared ADDRESSES — so box.3d/game's tokenizer
    # helpers (is_alpha_char: `c >= "A" and c <= "Z"`) always returned
    # garbage and no identifier ever tokenized. Lexicographic byte order
    # via mojo_cstr_cmp matches both C strncmp and the interpreter's
    # str ordering for ASCII.
    if op in ('<', '>', '<=', '>=') and (
            lt == 'char *' or rt == 'char *'
            or gen._actual_types.get(lv) == 'char'
            or gen._actual_types.get(rv) == 'char'):
        ls = lv if lt == 'char *' else gen._char_to_cstr(lt, lv)[1]
        rs = rv if rt == 'char *' else gen._char_to_cstr(rt, rv)[1]
        cmp_t = gen._call_expr('int', 'mojo_cstr_cmp', [('char *', ls), ('char *', rs)])
        t = gen._new_temp('_Bool')
        gen._emit(f'  {t} = {cmp_t} {op} 0;')
        return '_Bool', t

    # is / is not → pointer identity
    if op in ('is', 'is not'):
        c_op = '==' if op == 'is' else '!='
        t = gen._new_temp('_Bool')
        if '*' in lt or '*' in rt:
            p1 = gen._new_temp('int64_t')
            p2 = gen._new_temp('int64_t')
            gen._emit(f"  {p1} = (int64_t) {lv};")
            gen._emit(f"  {p2} = (int64_t) {rv};")
            gen._emit(f"  {t} = {p1} {c_op} {p2};")
        elif lt != rt:
            # GIMPLE requires identical types in comparisons; coerce to int64_t
            cmp_type = gimple_ctypes.TypeLattice.join(lt, rt)
            p1 = gen._new_temp(cmp_type)
            p2 = gen._new_temp(cmp_type)
            gen._emit(f"  {p1} = ({cmp_type}){lv};")
            gen._emit(f"  {p2} = ({cmp_type}){rv};")
            gen._emit(f"  {t} = {p1} {c_op} {p2};")
        else:
            gen._emit(f"  {t} = {lv} {c_op} {rv};")
        return '_Bool', t

    # Fallback: catch string concatenation that wasn't handled above
    if op == '+' and lt == 'char *' and rt == 'char *':
        t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', rv)])
        return 'char *', t
    # `<string> + <single char>` (or the reverse) — e.g. `prefix += val[0]`
    # where `val[0]` (indexing a char* string) lowers to a bare C `char`,
    # not `char *`. Neither this is `char* + char*` (mojo_str_cat above)
    # nor is `char *` treated as a "raw pointer" by _is_raw_ptr below (it's
    # in _KNOWN_PTRS), so without this branch execution fell through to the
    # fully generic arithmetic emit further down, which emitted a bare
    # `ptr + char` C expression — raw pointer arithmetic on a `char *`,
    # which GIMPLE's frontend rejects outright ("internal compiler error
    # in build2"). Route the char through mojo_char_to_str first so this
    # becomes ordinary string concatenation. Found via mojo_compiler.py's
    # own `_decode_str_literal_text`'s `prefix += val[0]` failing to
    # self-compile with exactly that ICE.
    #
    # The char operand may also arrive typed int64_t: an unannotated local
    # holding `text[i]` gets its declared storage WIDENED to int64_t by
    # Pass 1.3b's assignment-type joining (the same widening
    # _lower_list_method's append already recovers from via _actual_types).
    # Without recovering here, `current_line = current_line + ch` emitted
    # mojo_str_from_int(ch) — appending the DECIMAL BYTE CODES instead of
    # the character ("Hello, World!" became "72101108111144..." in
    # box.3d/game's ComputerMonitor.print_text). Mirror append's recovery.
    if op == '+' and lt == 'char *' and rt in ('char', 'int', 'int64_t') \
            and (rt == 'char' or gen._actual_types.get(rv) == 'char'):
        rv_s = gen._call_expr('char *', 'mojo_char_to_str', [('char', rv)])
        t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', rv_s)])
        return 'char *', t
    if op == '+' and rt == 'char *' and lt in ('char', 'int', 'int64_t') \
            and (lt == 'char' or gen._actual_types.get(lv) == 'char'):
        lv_s = gen._call_expr('char *', 'mojo_char_to_str', [('char', lv)])
        t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv_s), ('char *', rv)])
        return 'char *', t
    # Fallback: catch list concatenation that wasn't handled above
    if op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
        t = gen._new_val('MojoList *', f"mojo_list_concat ({lv}, {rv})")
        if lv in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[lv]
        return 'MojoList *', t

    # Path joining: Mojo uses `/` as the path-join operator (Path.__truediv__).
    # When we see int64_t/char* or char*/char* with op='/', dispatch to mojo_path_join.
    # A char*-LHS with an int/int64_t RHS is the same join with the right
    # operand still boxed (dynamic-getattr results, dict-unpacked loop
    # keys, ...): real Python `str / <non-path>` raises TypeError, so a
    # char*-LHS `/` can only ever be a join — coercing the boxed RHS
    # through its int64_t bits is semantics-preserving, unlike numeric
    # division (which always has a non-char* LHS and never reaches this).
    # Real: Apple/__main__.py's `CROSS_BUILD_DIR / context.platform` /
    # `CROSS_BUILD_DIR / host_triple`, whose RHS lowers via
    # _mojo_dispatch_getattr to an untracked int64_t.
    if op == '/' and (rt == 'char *'
                      or (lt == 'char *' and rt in ('int', 'int64_t'))):
        t = gen._new_temp('char *')
        lv_str = lv
        if lt != 'char *':
            lv_str = gen._new_temp('char *')
            lv_i64 = gen._new_temp('int64_t') if lt != 'int64_t' else lv
            if lt != 'int64_t':
                gen._emit(f'  {lv_i64} = (int64_t){lv};')
            gen._emit(f'  {lv_str} = (char *){lv_i64};')
        rv_str = rv
        if rt != 'char *':
            rv_str = gen._new_temp('char *')
            rv_i64 = gen._new_temp('int64_t') if rt != 'int64_t' else rv
            if rt != 'int64_t':
                gen._emit(f'  {rv_i64} = (int64_t){rv};')
            gen._emit(f'  {rv_str} = (char *){rv_i64};')
        gen._emit_call('char *', t, 'mojo_path_join', [('char *', lv_str), ('char *', rv_str)])
        return 'char *', t

    # Raw pointer arithmetic: `ptr + n` / `ptr - n` for a genuine buffer
    # pointer (UnsafePointer et al., lowered by _mojo_type to `<elem> *`).
    # This must be distinguished from a *boxed scalar* pointer like the
    # `self: Int *` receiver inside Int.__neg__ (`self * -1`) — both are
    # spelled `<name> *`, but a real Mojo struct's boxed self-pointer uses
    # the struct's own name (`Int *`) and IS registered in
    # struct_field_types (from parsing `struct Int(...)`), whereas a raw
    # buffer pointer's element type is a plain C scalar (`int64_t *`,
    # `double *`, ...) that never is. GIMPLE forbids raw `p + n` pointer
    # arithmetic directly, so route through the same _mojo_at_<elem>
    # scaled-offset helper already used for subscripting/`.offset()`, and
    # keep the pointer's own type as the result (real Mojo semantics)
    # instead of falling into the boxed-scalar collapse below, which would
    # otherwise silently degrade the pointer to a bare address integer.
    _KNOWN_PTRS = frozenset({
        'void *', 'char *', 'MojoList *', 'MojoDict *', 'MojoSet *', 'MojoStr *',
    })
    def _is_raw_ptr(t: str) -> bool:
        return (t.endswith(' *') and t not in _KNOWN_PTRS
                and gimple_exprtypes._struct_name_of(t) not in gen.struct_field_types)
    if op in ('+', '-'):
        if _is_raw_ptr(lt) and not rt.endswith(' *'):
            elem = gimple_ctypes._elem_type(lt)
            cn = gimple_ctypes._c_id(elem)
            gen._ptr_helpers_needed.add(elem)
            rv64 = rv if rt == 'int64_t' else gen._new_val('int64_t', f"(int64_t){rv}")
            off = rv64 if op == '+' else gen._new_val('int64_t', f"-{rv64}")
            pt = gen._new_val(lt, f"_mojo_at_{cn} ({lv}, {off})")
            return lt, pt
        if op == '+' and _is_raw_ptr(rt) and not lt.endswith(' *'):
            elem = gimple_ctypes._elem_type(rt)
            cn = gimple_ctypes._c_id(elem)
            gen._ptr_helpers_needed.add(elem)
            lv64 = lv if lt == 'int64_t' else gen._new_val('int64_t', f"(int64_t){lv}")
            pt = gen._new_val(rt, f"_mojo_at_{cn} ({rv}, {lv64})")
            return rt, pt

    # Cast struct pointer operands through int64_t so C arithmetic is valid.
    # e.g., `self * -1` inside Int.__neg__ where self: Int * → (int64_t)self * -1.
    # Must happen before res_type is computed to avoid declaring result as struct ptr.
    if lt.endswith(' *') and lt not in _KNOWN_PTRS and op not in ('==', '!=', 'is', 'is not'):
        ip = gen._new_val('int64_t', f'(int64_t){lv}')
        lt = 'int64_t'; lv = ip
    if rt.endswith(' *') and rt not in _KNOWN_PTRS and op not in ('==', '!=', 'is', 'is not'):
        ip = gen._new_val('int64_t', f'(int64_t){rv}')
        rt = 'int64_t'; rv = ip

    # A `char *` operand reaching a genuinely BITWISE operator (&, |, ^,
    # <<, >>) is never a real Python string use — Python's str has no
    # bitwise operators, so this can only be a mis-declared boxed scalar,
    # not an actual string. This arises from the boxed dict/list runtime-
    # dispatch tuple-unpack fallback (`_gen_for_iter`'s "boxed int64_t
    # iterable, unknown container" branch): its dict-shaped sibling
    # (`for k, v in <boxed>.items():`) and list-shaped sibling (`for a, b
    # in <boxed list of (int, str) tuples>:`) unpack into the SAME
    # source-level loop-variable names, and `_declare_var`'s documented
    # first-decl-wins convention means whichever branch is emitted FIRST
    # (always the dict branch, which types its key slot `char *`)
    # permanently fixes the C-level declaration for BOTH branches — even
    # when the list branch's real per-slot type is a genuine int64_t
    # (`_safe_coerce_emit` then value-preservingly reinterpret-casts the
    # int64_t into the shared `char *` variable, so the VALUE survives
    # but the C TYPE is wrong at this use site). Coercing the char*
    # operand back to int64_t here recovers a correctly-typed bitwise
    # expression instead of gcc's hard "invalid operands to binary &
    # (have int64_t and char *)". Real, in Lib/stat.py's filemode():
    # `if mode & bit == bit:` where `bit`'s declaration is shared with a
    # `for k, v in <boxed>.items()`-shaped sibling for-loop pattern
    # earlier in the same runtime-dispatch fallback. Scoped strictly to
    # bitwise operators (not '+'/'%'/'/' etc.) so every existing
    # char*-string special case elsewhere in this method (concatenation,
    # path-join, %-formatting) is completely unaffected.
    if op in ('&', '|', '^', '<<', '>>'):
        if lt == 'char *' and rt != 'char *':
            lv = gen._new_val('int64_t', f'(int64_t){lv}')
            lt = 'int64_t'
        if rt == 'char *' and lt != 'char *':
            rv = gen._new_val('int64_t', f'(int64_t){rv}')
            rt = 'int64_t'

    c_op      = gimple_ctypes._BIN_OPS.get(op, op)
    res_type  = '_Bool' if op in gimple_ctypes._CMP_OPS else gimple_ctypes.TypeLattice.join(lt, rt)

    # Type system: Check BIT_WIDTH_PRESERVATION for arithmetic ops
    # For | on set/list/dict pointer types, use runtime union, not C bitwise |.
    # An empty `{}` operand lowers to MojoDict*; coerce such pointer operands
    # to MojoSet* so GIMPLE's strict pointer typing accepts the call.
    def _as_set(t, v):
        if t == 'MojoSet *':
            return v
        return gen._new_val('MojoSet *', f'(MojoSet *){gen._ensure_local(t, v)}')
    if op == '|' and (lt.endswith(' *') or rt.endswith(' *')):
        return 'MojoSet *', gen._call_expr('MojoSet *', 'mojo_set_union',
                                            [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
    # For - on set types, use runtime difference, not C subtraction
    if op == '-' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
        return 'MojoSet *', gen._call_expr('MojoSet *', 'mojo_set_difference',
                                            [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
    # For & on set types, use runtime intersection, not C bitwise &
    if op == '&' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
        return 'MojoSet *', gen._call_expr('MojoSet *', 'mojo_set_intersection',
                                            [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
    # For ^ on set types, symmetric difference = (a - b) | (b - a).
    # No dedicated runtime entry; compose from difference + union.
    if op == '^' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
        a, b = _as_set(lt, lv), _as_set(rt, rv)
        ab = gen._call_expr('MojoSet *', 'mojo_set_difference', [('MojoSet *', a), ('MojoSet *', b)])
        ba = gen._call_expr('MojoSet *', 'mojo_set_difference', [('MojoSet *', b), ('MojoSet *', a)])
        return 'MojoSet *', gen._call_expr('MojoSet *', 'mojo_set_union',
                                            [('MojoSet *', ab), ('MojoSet *', ba)])
    # Cast operands to result type to satisfy GIMPLE strict type checking
    arith_type = gimple_ctypes.TypeLattice.join(lt, rt)  # common type for arithmetic
    if lt != arith_type and arith_type not in ('_Bool',) and not arith_type.endswith(' *'):
        ct = gen._new_temp(arith_type)
        gen._safe_coerce_emit(lt, arith_type, lv, ct)
        lv = ct
    if rt != arith_type and arith_type not in ('_Bool',) and not arith_type.endswith(' *'):
        ct = gen._new_temp(arith_type)
        gen._safe_coerce_emit(rt, arith_type, rv, ct)
        rv = ct
    if op in ('==', '!=', '<', '>', '<=', '>=') and lt.endswith(' *') != rt.endswith(' *'):
        ip_l = gen._new_temp('int64_t')
        ip_r = gen._new_temp('int64_t')
        gen._emit(f'  {ip_l} = (int64_t){lv};')
        gen._emit(f'  {ip_r} = (int64_t){rv};')
        lv = ip_l; rv = ip_r
    # Floating-point division: gcc -fgimple ICEs (expmed_mode_index) on a
    # float/double `/` inside a __GIMPLE body. Route through a normal-C
    # runtime helper where the division expands correctly. Operands are
    # already coerced to res_type above.
    # TODO(gimple-fp-div): drop this indirection once the gcc -fgimple
    # float/double division ICE is fixed upstream.
    if c_op == '/' and res_type in ('double', 'float'):
        fn = 'mojo_div_double' if res_type == 'double' else 'mojo_div_float'
        return res_type, gen._call_expr(res_type, fn, [(res_type, lv), (res_type, rv)])
    # Floating-point modulo: plain GIMPLE `%` (trunc_mod_expr) is an
    # integer-only operator in C -- gcc rejects `double % double` outright
    # ("invalid operands to binary %"), the same class of error as the
    # `char *` string-formatting case this method's caller special-cases,
    # just for a different mismatched operand type. Found via `10.5 % 3.0`
    # (real Mojo/Python float modulo) while testing the %-string-format
    # fix. Python's float `%` is floor-based (result has the divisor's
    # sign for mixed-sign operands), not C's truncating fmod() -- compute
    # it the same way as `_lower_floordiv`'s float path: floor(x / y) * y
    # subtracted from x. The division must go through the same
    # mojo_div_double/float indirection as the '/' case just above
    # (gcc -fgimple ICEs on an inline float/double '/' in a __GIMPLE body).
    if c_op == '%' and res_type in ('double', 'float'):
        fn = 'mojo_div_double' if res_type == 'double' else 'mojo_div_float'
        div_t = gen._call_expr(res_type, fn, [(res_type, lv), (res_type, rv)])
        floor_t = gen._new_val(res_type, f"__builtin_floor ({div_t})")
        mul_t = gen._new_val(res_type, f"{floor_t} * {rv}")
        mod_t = gen._new_val(res_type, f"{lv} - {mul_t}")
        return res_type, mod_t
    # String `%` with non-literal format string: _lower_percent already
    # handled the StringLiteral-LHS case up in _lower_binary. Here at
    # the tail we have the lowered operands -- if either is a string
    # pointer, emit a safe concatenation fallback rather than invalid C
    # `int64_t % char *` (which gcc rejects).
    # String `%` with a non-literal char* LHS (a variable/expression
    # holding a format template — the StringLiteral-LHS case was already
    # handled by _lower_percent in _lower_binary). Only route through the
    # concatenation fallback when the LHS is a GENUINE string pointer;
    # `int64_t % int64_t` must stay numeric modulo (treating it as string
    # formatting broke real stdlib code like `value % range`).
    if c_op == '%' and lt == 'char *':
        rv_str = rv if rt == 'char *' else (gen._new_val('char *', f'(char *){rv}') if rt == 'int64_t' else gen._stringify_value(rt, rv))
        t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', rv_str)])
        return 'char *', t
    t = gen._new_val(res_type, f"{lv} {c_op} {rv}")
    return res_type, t


def _lower_compare_chain(gen, node: gimple_ctypes.CompareChain) -> tuple[str, str]:
    """Python-style chained comparison `a < b < c` (any length, any mix
    of comparison operators — `a < b == c > d` is valid Python). Each
    operand is evaluated exactly once, left-to-right, and the whole
    chain short-circuits to `_Bool` False the instant one
    `operands[i] ops[i] operands[i+1]` link fails, via real branching
    (not both/all links unconditionally evaluated then and-ed together)
    — mirrors eval_CompareChain in myinterpreter.py and the `and`/`or`
    real-branching lowering above. Reuses _lower_binary_tail /
    _lower_in_dispatch for the actual per-link comparison so string/
    pointer/is-not/membership semantics stay identical to what a plain
    two-operand BinaryOp of the same operator would produce."""
    result = gen._new_temp('_Bool')
    false_bb = gen._new_bb()
    merge_bb = gen._new_bb()
    left_node = node.operands[0]
    lt, lv = gen.lower_expr(left_node)
    n = len(node.ops)
    for i, op in enumerate(node.ops):
        right_node = node.operands[i + 1]
        rt, rv = gen.lower_expr(right_node)
        if op in ('in', 'not in'):
            cmp_type, cmp_val = gen._lower_in_dispatch(lt, lv, rt, rv, negate=(op == 'not in'))
        else:
            cmp_type, cmp_val = gen._lower_binary_tail(op, left_node, lt, lv, right_node, rt, rv)
        cond = gen._ensure_bool_cond(cmp_type, cmp_val)
        if i == n - 1:
            # Last link: truthy -> the whole chain held, every earlier
            # goto already confirmed -> result True.
            true_bb = gen._new_bb()
            gen._emit(f"  if ({cond}) goto {true_bb}; else goto {false_bb};")
            gen._emit_label(true_bb)
            # GIMPLE strictness: a bare integer_cst assigned straight
            # into a `_Bool` lvalue ("non-trivial conversion in
            # 'integer_cst'") is rejected — an explicit `(_Bool)` cast
            # on the literal is required (mirrors BoolLiteral/
            # _safe_coerce_emit elsewhere; found compiling base64.mojo's
            # `` `A` <= c <= `Z` ``, which -fgimple only flags once the
            # surrounding function is large enough to hit the strict
            # low-level GIMPLE path — a minimal repro compiled "fine").
            gen._emit(f"  {result} = (_Bool)1;")
            gen._emit(f"  goto {merge_bb};")
        else:
            next_bb = gen._new_bb()
            gen._emit(f"  if ({cond}) goto {next_bb}; else goto {false_bb};")
            gen._emit_label(next_bb)
        left_node, lt, lv = right_node, rt, rv
    gen._emit_label(false_bb)
    gen._emit(f"  {result} = (_Bool)0;")
    gen._emit(f"  goto {merge_bb};")
    gen._emit_label(merge_bb)
    return '_Bool', result


def _lower_percent(gen, node: gimple_ctypes.BinaryOp):
    """Python `%` is overloaded: Python's %-style string formatting when
    the LHS is a string ("%s (%d)" % (a, b)), ordinary numeric modulo
    otherwise. GCC's -fgimple back end has no such overload -- unconditional
    fallthrough to a plain GIMPLE `%` (trunc_mod_expr) on a `char *` LHS
    is exactly what produced the "invalid operands to binary %"/"invalid
    types for 'trunc_mod_expr'" class of errors across ~130 real stdlib
    files (colorsys.py's `h % 1.0` is the numeric case that must keep
    working; re/_constants.py's `'%s (line %d, column %d)' % (msg,
    self.lineno, self.colno)` is the string case that didn't).

    Only a *literal* format string on the LHS used to be handled specially
    here (the overwhelming majority of real `%`-formatting -- format
    templates are almost always written as literals, never built up at
    runtime). Anything else fell through to the ordinary numeric-modulo
    path.

    ONE dynamic-template shape now has a real lowering instead of that
    fallthrough: a DICT-keyed RHS (`text % dict(prog=...)`, `readme %
    textvars`, or `"%(x)s" % {..}` where the template happens to be a
    literal but the mapping is keyed). Positional compile-time splitting
    can't apply (there are no positional operands to map specs onto), and
    emitting raw GIMPLE `%` against a MojoDict* operand is exactly the
    "invalid operands to binary % (have 'int64_t' and 'MojoDict *')" hard
    error class seen in real argparse.py/build-installer.py closures.
    These lower to the new runtime primitive `mojo_str_format_dict`
    (runtime/mojo_runtime.c), which parses %(key)[flags][width][.prec]conv
    specs and looks up each key AT RUNTIME -- honest Python semantics for
    a dynamic template, including real catchable KeyError on a miss.
    Detection is deliberately AST/type-based BEFORE anything is emitted,
    so every non-dict shape still returns None and falls through to the
    generic modulo path with zero double-lowering of operands."""
    if isinstance(node.right, gimple_ctypes.DictExpr):
        return _lower_percent_dict(gen, node)
    if (isinstance(node.right, gimple_ctypes.CallExpr)
            and isinstance(node.right.func, gimple_ctypes.IdentExpr)
            and node.right.func.name == 'dict'
            and not gen._locally_binds_name('dict')):
        return _lower_percent_dict(gen, node)
    # A dict-typed RHS under any other expression shape (typically an
    # IdentExpr/MemberExpr holding a mapping built earlier, build-installer
    # .py's `readme % textvars`) — same lowering. Checked BEFORE the
    # literal-LHS branch so `"%(k)s" % mapping_var` doesn't get mis-mapped
    # positionally by _lower_percent_format.
    if gen._quick_type(node.right) == 'MojoDict *':
        return _lower_percent_dict(gen, node)
    if isinstance(node.left, gimple_ctypes.StringLiteral):
        fmt_text, is_fstring = gen._decode_str_literal_text(node.left.value)
        if not is_fstring:
            return gen._lower_percent_format(node, fmt_text)
    return None  # sentinel: caller falls through to generic numeric `%`


def _lower_percent_dict(gen, node: gimple_ctypes.BinaryOp):
    """Lower `<template> % <dict>` to the runtime dict-keyed formatter.

    Both operands are lowered normally (side effects preserved), then the
    LHS is coerced to `char *`: for a genuinely char*-typed template that
    is a no-op cast, and for an int64_t-mistyped template (the pervasive
    unknown-call-return fallback typing) the cast is still semantically
    safe because `% dict` on a non-string LHS is a TypeError in real
    Python — no VALID program ever reaches this call with a real integer
    in the slot. The alternative (refusing / falling through) keeps
    emitting invalid GIMPLE `%` on MojoDict*, which cannot link."""
    lt, lv = gen.lower_expr(node.left)
    rt, rv = gen.lower_expr(node.right)
    lvs = lv if lt == 'char *' else gen._new_val('char *', f"(char *){lv}")
    t = gen._new_val('char *', f"mojo_str_format_dict ({lvs}, {rv})")
    return 'char *', t


def _lower_percent_format(gen, node: gimple_ctypes.BinaryOp, fmt_text: str) -> tuple[str, str]:
    """Lower literal `%`-format string formatting to a `char *` result.

    Mirrors how f-string interpolation (_lower_StringLiteral's
    is_fstring branch / _parse_fstring_parts) splits literal text from
    `{expr}` parts and concatenates the pieces via mojo_str_cat: here
    the equivalent of an `{expr}` part is "the next %-spec", matched
    left-to-right against the RHS's operands (a tuple's elements for
    `fmt % (a, b, ...)`, or the single RHS expression for `fmt % x`).
    """
    rhs_exprs = (list(node.right.elements) if isinstance(node.right, gimple_ctypes.TupleExpr)
                 else [node.right])

    # Parse into ('lit', text) | ('spec', full_spec, conv) parts.
    # `full_spec` keeps the flags/width/precision text (e.g. '%08.3f')
    # so sprintf below reproduces them; only the conversion character
    # needs any Python->C translation.
    parts = []
    buf = []
    i, n = 0, len(fmt_text)
    while i < n:
        c = fmt_text[i]
        if c != '%':
            buf.append(c); i += 1
            continue
        if i + 1 < n and fmt_text[i + 1] == '%':
            buf.append('%'); i += 2
            continue
        if buf:
            parts.append(('lit', ''.join(buf))); buf = []
        spec_start = i
        i += 1
        # Flags, width, precision. Dynamic width/precision ('%*d') isn't
        # supported -- rare enough in practice to leave as a follow-up
        # rather than block the common literal-width case.
        while i < n and fmt_text[i] in '-+0 #.123456789':
            i += 1
        conv = fmt_text[i] if i < n else 's'
        if i < n:
            i += 1
        parts.append(('spec', fmt_text[spec_start:i], conv))
    if buf:
        parts.append(('lit', ''.join(buf)))

    n_specs = sum(1 for p in parts if p[0] == 'spec')
    if n_specs != len(rhs_exprs):
        # Can't safely map operands to specs (mismatched-arity source,
        # or a '%' that wasn't really meant as a format template).
        # Degrade to the literal text -- still evaluated the RHS for any
        # side effects real Python would have had -- rather than emit a
        # GIMPLE-invalid `char * % ...`.
        for e in rhs_exprs:
            gen.lower_expr(e)
        return 'char *', gen._new_val('char *', gen._intern_string(gimple_ctypes._c_escape(fmt_text)))

    arg_i = 0
    acc_val = None
    for part in parts:
        if part[0] == 'lit':
            text = part[1]
            if not text:
                continue
            part_val = gen._new_val('char *', gen._intern_string(gimple_ctypes._c_escape(text)))
        else:
            _, full_spec, conv = part
            et, ev = gen.lower_expr(rhs_exprs[arg_i])
            arg_i += 1
            part_val = gen._format_percent_spec(full_spec, conv, et, ev)
        acc_val = part_val if acc_val is None else gen._new_val(
            'char *', f'mojo_str_cat ({acc_val}, {part_val})')
    if acc_val is None:
        acc_val = gen._new_val('char *', gen._intern_string(''))
    return 'char *', acc_val


def _lower_floordiv(gen, node: gimple_ctypes.BinaryOp) -> tuple[str, str]:
    lt, lv = gen.lower_expr(node.left)
    rt, rv = gen.lower_expr(node.right)
    if lt in gimple_ctypes._FLOAT_TYPES or rt in gimple_ctypes._FLOAT_TYPES:
        td = gimple_ctypes.TypeLattice.join(lt, rt)
        t1 = gen._new_val(td, f"{lv} / {rv}")
        t2 = gen._new_val(td, f"__builtin_floor ({t1})")
        return td, t2
    # Coerce struct pointers to int64_t before integer floor division
    if lt.endswith(' *') and lt not in ('void *', 'char *'):
        ti = gen._new_val('int64_t', f"(int64_t){lv}")
        lv = ti
    if rt.endswith(' *') and rt not in ('void *', 'char *'):
        ti = gen._new_val('int64_t', f"(int64_t){rv}")
        rv = ti
    t = gen._new_val('int64_t', f"__mojo_floordiv ({lv}, {rv})")
    return 'int64_t', t


def _lower_pow(gen, node: gimple_ctypes.BinaryOp) -> tuple[str, str]:
    lt, lv = gen.lower_expr(node.left)
    rt, rv = gen.lower_expr(node.right)
    if lt in gimple_ctypes._FLOAT_TYPES or rt in gimple_ctypes._FLOAT_TYPES:
        td = gimple_ctypes.TypeLattice.join(lt, rt)
        t = gen._new_val(td, f"pow ({lv}, {rv})")
        return td, t
    # Coerce struct pointers to int64_t before converting to double
    # (casting struct * to double directly is invalid in GIMPLE)
    lv_for_double = lv
    rv_for_double = rv
    if lt.endswith(' *'):
        ti = gen._new_val('int64_t', f"(int64_t) {lv}")
        lv_for_double = ti
    if rt.endswith(' *'):
        ti = gen._new_val('int64_t', f"(int64_t) {rv}")
        rv_for_double = ti
    t1 = gen._new_temp('double')
    t2 = gen._new_temp('double')
    gen._emit(f"  {t1} = (double) {lv_for_double};")
    gen._emit(f"  {t2} = (double) {rv_for_double};")
    t3 = gen._new_val('double', f"pow ({t1}, {t2})")
    t4 = gen._new_val('int', f"(int) {t3}")
    return 'int', t4


def _lower_matmul(gen, node: gimple_ctypes.BinaryOp) -> tuple[str, str]:
    """Lower matrix multiply: a @ b → a.__matmul__(b)

    Calls the __matmul__ method on the left operand.
    TODO: Implement high-performance matrix multiplication using BLAS (e.g., dgemm)
    or SIMD intrinsics for larger matrices. For now, delegates to user-defined
    __matmul__ implementations on matrix types.
    """
    lt, lv = gen.lower_expr(node.left)
    rt, rv = gen.lower_expr(node.right)

    # Get struct name from left operand type
    struct_name = gimple_exprtypes._struct_name_of(lt)

    # Call __matmul__(self, other) method
    mangled = f"{struct_name}___matmul__"
    # `struct_name` is only trustworthy as a "this really is a struct with
    # its own __matmul__ method" signal when it names a KNOWN struct
    # (self.struct_field_types) — an UNANNOTATED param (this codegen's
    # generic fallback type for those is 'int64_t') left operand makes
    # struct_name == 'int64_t' here, and blindly emitting a call to
    # int64_t___matmul__ references a symbol nothing ever defines (real
    # Python has no `int.__matmul__` either — `int @ int` raises
    # TypeError at runtime, so this shape is genuinely never valid to
    # call, only ever REACHED as dead code inside a polymorphic helper
    # like `Lib/operator.py`'s `def matmul(a, b): return a @ b`, whose
    # untyped params this compiler can't know are never actually ints).
    # Confirmed via `mojo.py build` on both Lib/socket.py and
    # Lib/runpy.py's transitive closures (both reach operator.py):
    # "error: implicit declaration of function 'int64_t___matmul__'"
    # (promoted to a hard error, not just a warning, under -fgimple).
    # Mirror the established "no real definition will ever exist —
    # emit a guarded WEAK stub instead of a bare forward decl" pattern
    # already used for an unresolved-base-class method call a few
    # hundred lines up (`_structs_with_unresolved_base` branch) rather
    # than inventing new machinery.
    if struct_name not in gen.struct_field_types:
        # Variadic signature (not a fixed `(int64_t, int64_t)`) — `lv`/
        # `rv`'s actual GIMPLE types depend on whatever `lt`/`rt` this
        # non-struct operand happened to infer to (could be `char *`,
        # `double`, ... not necessarily `int64_t`), and this stub must
        # accept the call as emitted below regardless. Mirrors the
        # `(...)`-accepts-any-arity convention used throughout this
        # file's other auto-stub generators for the same GIMPLE-mode
        # reason (a fixed-arity `()` is "zero params" under -fgimple,
        # not "unspecified", and rejects any real argument list).
        _stub_guard = gimple_ctypes._stub_guard_name(gimple_ctypes._safe_name(mangled))
        _stub = (f'#ifndef {_stub_guard}\n#define {_stub_guard}\n'
                  f'__attribute__((weak)) int64_t {mangled} (...) '
                  f'{{ mojo_print ((char *)'
                  f'"{mangled}: unavailable in compiled mode (matmul on a '
                  f'non-struct/unannotated operand)"); return (int64_t)0; }}\n#endif')
        if _stub not in gen._elaborated_externs:
            gen._elaborated_externs.append(_stub)
        t = gen._new_val('int64_t', f"{mangled} ({lv}, {rv})")
        return 'int64_t', t
    result_type = gen.func_return_types.get(mangled, 'int64_t')  # Default: assume int result
    t = gen._new_val(result_type, f"{mangled} ({lv}, {rv})")
    return result_type, t


def _lower_in_range(gen, x_val: str, range_args: list,
                    negate: bool) -> tuple[str, str]:
    if len(range_args) == 1:
        _, n_val = gen.lower_expr(range_args[0])
        t1 = gen._new_temp('_Bool')
        t2 = gen._new_temp('_Bool')
        t3 = gen._new_temp('_Bool')
        gen._emit(f"  {t1} = {x_val} >= 0;")
        gen._emit(f"  {t2} = {x_val} < {n_val};")
        gen._emit(f"  {t3} = {t1} & {t2};")
    elif len(range_args) == 2:
        _, a_val = gen.lower_expr(range_args[0])
        _, b_val = gen.lower_expr(range_args[1])
        t1 = gen._new_temp('_Bool')
        t2 = gen._new_temp('_Bool')
        t3 = gen._new_temp('_Bool')
        gen._emit(f"  {t1} = {x_val} >= {a_val};")
        gen._emit(f"  {t2} = {x_val} < {b_val};")
        gen._emit(f"  {t3} = {t1} & {t2};")
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        t3 = gen._new_val('_Bool', "0")
    if negate:
        ti = gen._new_temp('int')
        tn = gen._new_temp('_Bool')
        gen._emit(f"  {ti} = (int) {t3};")
        gen._emit(f"  {tn} = {ti} == 0;")
        return '_Bool', tn
    return '_Bool', t3


def _lower_in_impl(gen, node: gimple_ctypes.BinaryOp, negate: bool) -> tuple[str, str]:
    xt, xv = gen.lower_expr(node.left)
    # Same boxed-pointer-mistyped-as-int64_t issue as the `rt` resolution
    # below, but on the left operand: a local reassigned from a value
    # whose static type inference lost track of it being a real char*
    # (e.g. `val = m.group()` in a regex-scan loop) reads back xt as
    # int64_t here even though xv is a valid char* value, so `val in
    # _KEYWORDS` fell to the int64_t branch (mojo_set_contains_int)
    # instead of the string one and could never match.
    xt = gen._get_actual_type(xt, xv)
    # Same C-level-still-int64_t situation as rv below: the logical type
    # is now correct, but the declared local is still int64_t at the C
    # level, so callees expecting a real char*/pointer need an explicit
    # cast, not just the corrected bookkeeping type.
    if xt == 'char *' and gen.var_types.get(xv) == 'int64_t':
        xv = gen._new_val('char *', f"(char *){xv}")
    elif xt.endswith(' *') and xt != 'char *' and gen.var_types.get(xv) == 'int64_t':
        xv = gen._new_val(xt, f"({xt}){xv}")
    return gen._lower_in_impl_values(xt, xv, node.right, negate)


def _lower_in_impl_values(gen, xt: str, xv: str, right_node, negate: bool) -> tuple[str, str]:
    """The rest of `in`/`not in` lowering, taking the already-lowered
    left operand (xt, xv) instead of re-lowering it from an AST node.
    Split out of _lower_in_impl so a CompareChain link (`a in b < c`,
    however rare) can reuse this without evaluating the shared operand
    `a` (or, for a middle link, the previous link's right-hand operand)
    a second time — see _lower_compare_chain."""
    if (isinstance(right_node, gimple_ctypes.CallExpr) and
            isinstance(right_node.func, gimple_ctypes.IdentExpr) and
            right_node.func.name == 'range'):
        return gen._lower_in_range(xv, right_node.args, negate=negate)

    rt, rv = gen.lower_expr(right_node)
    return gen._lower_in_dispatch(xt, xv, rt, rv, negate)


def _lower_in_dispatch(gen, xt: str, xv: str, rt: str, rv: str, negate: bool) -> tuple[str, str]:
    """Container-type dispatch (list/dict/set/str) for `in`/`not in`,
    given both operands already lowered. Split out of
    _lower_in_impl_values so _lower_compare_chain's 'in'/'not in' links
    can reuse it directly with their own pre-lowered right operand —
    the range()-literal fast path (_lower_in_range) isn't reachable
    from here since that needs the RAW range(...) call args, not an
    already-evaluated value; a chained `x in range(...)` link falls
    through to ordinary CallExpr lowering of range() instead, same as
    any other non-'in' use of a bare range() value already would."""
    # A module-level MojoList*/MojoDict*/MojoSet* global is boxed as
    # int64_t at the static-type level (_lower_IdentExpr stashes the
    # real type in _actual_types instead) — without resolving through
    # it here, `rt` is always 'int64_t' for e.g. `x in SOME_GLOBAL_SET`,
    # never matching any of the branches below, so membership against
    # any top-level set/dict/list constant silently always returned
    # False. Found via `val in _KEYWORDS` (mojo_compiler.py's own
    # tokenizer) misclassifying every keyword as a plain NAME in the
    # self-hosted compiled path. len()/iteration elsewhere already
    # resolve through _get_actual_type; this call site didn't.
    rt = gen._get_actual_type(rt, rv)
    # rv itself is still declared int64_t at the C level even after the
    # logical-type resolution above (only the bookkeeping dict changed) —
    # cast it to the real pointer type, same idiom as _gen_for_set/_gen_for_dict.
    if rt.endswith(' *') and gen.var_types.get(rv) == 'int64_t':
        rv = gen._new_val(rt, f"({rt}){rv}")
    ti = gen._new_temp('int')

    if rt == 'MojoList *':
        # Determine list element type: prefer actual list elem type over left operand
        if rv in gen._elem_types:
            list_elem = gen._elem_types[rv]
        else:
            list_elem = xt
        suf = gimple_ctypes.TypeLattice.list_suffix(list_elem)
        xv_cast = gen._cast_for_list(xt, xv, suf)
        gen._emit(f"  {ti} = mojo_list_contains_{suf} ({rv}, {xv_cast});")
    elif rt == 'MojoDict *':
        # Ensure key is char * for dict operations (all dict keys are strings in runtime)
        xt, xv = gen._char_to_cstr(xt, xv)
        gen._emit_call('int', ti, 'mojo_dict_contains', [('MojoDict *', rv), (xt, xv)])
    elif rt == 'MojoSet *':
        # Route through _emit_call so global/_slit_ args are loaded into locals
        # first (GIMPLE: a call argument must be a local, not a global decl).
        if xt == 'char *':
            gen._emit_call('int', ti, 'mojo_set_contains_str', [('MojoSet *', rv), ('char *', xv)])
        else:
            xv64 = gen._to_int64(xt, xv)
            gen._emit_call('int', ti, 'mojo_set_contains_int', [('MojoSet *', rv), ('int64_t', xv64)])
    elif rt == 'MojoStr *':
        gen._emit_call('int', ti, 'mojo_str_contains', [('MojoStr *', rv), ('char *', xv)])
    elif rt == 'char *':
        # `x in some_string` — substring/char membership via strstr
        # (mojo_str_contains). The left operand is the needle: a bare
        # `char` (e.g. `raw[i] in 'fFrRbBuUtT'`, a single indexed char)
        # must be turned into a real 1-char string first — a raw
        # `(char *)` reinterpret of its byte value would be a garbage
        # pointer (same class of bug as the char→char* coercion fix in
        # _safe_coerce_emit). Was a hardcoded always-False stub: the
        # documented historical regression from enabling this
        # ("plain string literals after an f-string come back unstripped")
        # was a downstream symptom of that same char→char* coercion bug,
        # now fixed — a full `make bootstrap` (which exercises
        # Parser._strip_string_prefix_and_quotes's `raw[i] in 'frbu...'`
        # heavily) stays green with this enabled.
        if xt == 'char':
            needle = gen._call_expr('char *', 'mojo_char_to_str', [('char', xv)])
        elif xt == 'char *':
            needle = xv
        elif xt.endswith(' *'):
            needle = gen._new_val('char *', f'(char *){xv}')
        else:
            cv = gen._new_val('char', f'(char){xv}')
            needle = gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
        gen._emit_call('int', ti, 'mojo_str_contains', [('char *', rv), ('char *', needle)])
    else:
        gen._emit(f"  /* TODO: 'in' for {rt} */")
        gen._emit(f"  {ti} = 0;")

    t = gen._new_val('_Bool', f"{ti} != 0")

    if negate:
        ti2 = gen._new_temp('int')
        tn  = gen._new_temp('_Bool')
        gen._emit(f"  {ti2} = (int) {t};")
        gen._emit(f"  {tn} = {ti2} == 0;")
        return '_Bool', tn
    return '_Bool', t


def _lower_external_call(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Lower external_call["name", Ret](args) / _external_call_const[...] to a
    direct C call.  This is the irreducible primitive the stdlib bottoms out on
    (e.g. FileDescriptor.write_bytes → external_call["write", c_ssize_t](...)).

    The subscript index is `"name"` or `("name", RetType, *ParamTypes)`.  We take
    the name and return type from the index and the argument C types from the
    lowered call arguments, then register one extern prototype per name (first use
    wins) for emission in the preamble.
    """
    idx = node.func.index
    elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]

    cname = elems[0].value if elems and isinstance(elems[0], gimple_ctypes.StringLiteral) else None
    if not cname:
        t = gen._new_temp('int')
        gen._emit(f"  {t} = 0;  /* external_call with non-literal name */")
        return 'int', t
    cname = ''.join('_' if not c.isalnum() and c != '_' else c for c in cname)

    ret_ct = 'void'
    if len(elems) >= 2:
        ann = gen._type_expr_to_ann(elems[1])
        if ann == 'NoneType':
            ret_ct = 'void'
        elif ann:
            ret_ct = gimple_ctypes._mojo_type(ann)
    # _KNOWN_SIGS takes precedence over Mojo type annotation (e.g. Scalar[T] → int64_t)
    # when the C function has a non-int64_t return type (float, double, FILE*, etc.)
    # Also check _LIBC_SIGS for C stdlib functions like getenv → char*
    if cname in gen._KNOWN_SIGS:
        ret_ct = gen._KNOWN_SIGS[cname][0]
    elif cname in gen._LIBC_SIGS:
        ret_ct = gen._LIBC_SIGS[cname][0]

    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Pad to the known libc arity: a Mojo FFI wrapper may forward fewer args than
    # the C function takes (e.g. `external_call["setvbuf"](stream, buffer)` vs the
    # 4-arg libc setvbuf). Supplying 0 for the trailing params gives a defined call
    # that matches <stdio.h>, instead of a "too few arguments" clash. (Whether the
    # wrapper SHOULD forward its mode/size is an upstream-source question; this just
    # makes the binding compile with defined behavior rather than reading garbage.)
    if cname in gen._LIBC_SIGS:
        _sig_params = gen._LIBC_SIGS[cname][1]
        while len(arg_pairs) < len(_sig_params):
            arg_pairs.append((_sig_params[len(arg_pairs)], '0'))
    # First use wins: pin the prototype's parameter types and coerce later calls to match.
    # Never register LIBC functions - let system headers provide them
    if cname not in gen._external_protos and (
            cname not in gen._LIBC_DECLARED or cname in gen._NEEDS_SELF_EXTERN):
        # Prefer the pinned libc signature for the prototype so a self-emitted
        # extern (e.g. `int pipe(int *)`) matches the coerced call args rather
        # than the raw int64_t-lowered argument types.
        _proto_params = (gen._LIBC_SIGS[cname][1] if cname in gen._LIBC_SIGS
                         else [at for (at, _) in arg_pairs])
        gen._external_protos[cname] = (ret_ct, _proto_params)
    # Track param types for coercion, even if not emitting declaration
    if cname not in gen.func_param_types:
        if cname in gen._LIBC_SIGS:
            gen.func_param_types[cname] = gen._LIBC_SIGS[cname][1]
        elif cname in gen._external_protos:
            gen.func_param_types[cname] = gen._external_protos[cname][1]
        else:
            gen.func_param_types[cname] = [at for (at, _) in arg_pairs]

    if ret_ct == 'void':
        gen._emit_call('', '', cname, arg_pairs)
        t = gen._new_temp('int')
        gen._emit(f"  {t} = 0;  /* void external_call result */")
        return 'int', t
    t = gen._call_expr(ret_ct, cname, arg_pairs)
    if ret_ct == 'void *' and cname in ('dlopen', 'dlsym'):
        # The dynamic-linker handle functions return void* but Mojo models the
        # handle as int64_t (c_void_ptr). Coerce through a register so the
        # surrounding int64_t store/return is a valid single cast rather than a
        # void*→int64_t direct assignment. (FILE*-returning calls like fopen/
        # popen keep void* — their results stay pointers.)
        ct = gen._new_temp('int64_t')
        gen._emit(f"  {ct} = (int64_t){t};")
        return 'int64_t', ct
    return ret_ct, t


def _lower_mlir_mem(gen, kind: str, arg_pairs: list) -> tuple[str, str]:
    """Emit a memory/lvalue MLIR op classified by mlir.mem_op_kind().

    load   (addr)        -> *addr
    store  (val, addr)   -> *addr = val          (statement; yields 0)
    offset (ptr, idx)    -> _mojo_at_T(ptr, idx)  (GIMPLE-legal pointer add)
    """
    if kind == 'load':
        at, av = arg_pairs[0]
        pt, pv = gen._as_ptr(at, av)
        et = gimple_ctypes._elem_type(pt)
        t = gen._new_val(et, f"*{pv}")
        return et, t

    if kind == 'store':
        (vt, vv), (at, av) = arg_pairs[0], arg_pairs[1]
        pt, pv = gen._as_ptr(at, av)
        et = gimple_ctypes._elem_type(pt)
        sv = vv
        if vt != et:
            sv = gen._new_val(et, f"({et}) {vv}")
        gen._emit(f"  *{pv} = {sv};")
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = (int64_t)0;  /* pop.store (no value) */")
        return 'int64_t', t

    # offset / array.gep: ptr + idx via the _mojo_at_ helper (pointer
    # arithmetic is illegal inside __GIMPLE).
    (pt0, pv0), (it, iv) = arg_pairs[0], arg_pairs[1]
    pt, pv = gen._as_ptr(pt0, pv0)
    et = gimple_ctypes._elem_type(pt)
    cn = gimple_ctypes._c_id(et)
    gen._ptr_helpers_needed.add(et)
    idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
    addr = gen._new_val(pt, f"_mojo_at_{cn} ({pv}, {idx64})")
    return pt, addr


def _lower_mlir_struct(gen, kind: str, index, arg_pairs: list):
    """Emit a struct/aggregate GEP op (extract / gep / aget) classified by
    mlir.struct_op_kind().  Returns (ctype, val) when the struct layout and
    a literal field index are resolvable, else None (caller → deferred stub).

    extract (struct_val) -> struct_val.fieldN     (N-th field value)
    gep     (struct_ptr) -> &struct_ptr->fieldN   (pointer to N-th field)
    aget    (array_val)  -> array_val[N]           (N-th element, via helper)
    """
    if not isinstance(index, int):
        return None
    ct, v = arg_pairs[0]

    # aget: index into an array/pointer value → offset + deref (GIMPLE-legal).
    if kind == 'aget':
        pt, pv = gen._as_ptr(ct, v)
        et = gimple_ctypes._elem_type(pt)
        cn = gimple_ctypes._c_id(et)
        gen._ptr_helpers_needed.add(et)
        addr = gen._new_val(pt, f"_mojo_at_{cn} ({pv}, {index})")
        t = gen._new_val(et, f"*{addr}")
        return et, t

    # extract / gep: resolve the struct's N-th field by declaration order.
    base = ct[:-2] if ct.endswith(' *') else ct
    op = '->' if ct.endswith(' *') else '.'
    fields = gen.struct_field_types.get(base)
    if not fields or index >= len(fields):
        return None
    fname = list(fields.keys())[index]
    ftype = fields[fname]

    if kind == 'extract':
        t = gen._new_val(ftype, f"{v}{op}{fname}")
        return ftype, t

    # gep → address of the field
    t = gen._new_val(f"{ftype} *", f"&{v}{op}{fname}")
    return f"{ftype} *", t


def _lower_list_literal(gen, node: gimple_ctypes.ListExpr) -> tuple[str, str]:
    elem = gen._infer_list_elem_type(node.elements)
    suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
    t    = gen._new_temp('MojoList *')
    # See _literal_elements_include_none's docstring: don't tag an
    # int64_t-joined list as elem-type int64_t when the literal itself
    # spells out a `None` among its elements — _list_repr_fn would
    # otherwise route it through mojo_repr_list_ints (no None-sentinel
    # check), silently misprinting that `None` as `0`.
    if not (elem == 'int64_t' and gen._literal_elements_include_none(node.elements)):
        gen._elem_types[t] = elem
    gen._emit(f"  {t} = mojo_list_new ();")
    # Lower elements first so we can see all their types before choosing how
    # to append. A single list-wide suffix mis-types a genuinely heterogeneous
    # collection — e.g. a tuple ('int', 5) would append the int via
    # mojo_list_append_str. Detect a string/non-string mix and, only then,
    # append each element by its OWN type. Numeric-only lists (incl. promoted
    # [1, 2.0]) keep the promoted list-wide suffix, so this never regresses
    # homogeneous lists.
    lowered = [(el, *gen.lower_expr(el)) for el in node.elements]

    def _is_spread(el, et):
        # Only treat as spread if it's an explicit spread operator (*seq)
        # Don't treat nested list literals [[...]] as spreads - those should append the list pointer
        return isinstance(el, gimple_ctypes.UnaryOp) and el.op == '*'

    scalar_sufs = {gimple_ctypes.TypeLattice.list_suffix(et)
                   for el, et, _ev in lowered if not _is_spread(el, et)}
    per_element = 'str' in scalar_sufs and scalar_sufs != {'str'}

    for el, et, ev in lowered:
        # Spread element (*seq): extend the list instead of appending
        if _is_spread(el, et):
            gen._emit_call('void', '', 'mojo_list_extend', [('MojoList *', t), (et, ev)])
            # Track nested element type if extending with a list that has tracked elements
            # IMPORTANT: Keep _elem_types[t] as 'MojoList *' (what t contains),
            # and set _nested_elem_types[t] to what those lists contain
            if et == 'MojoList *' and ev in gen._elem_types:
                # Don't overwrite _elem_types[t] - it correctly says t contains MojoList*
                # Instead, track what those lists contain in _nested_elem_types
                gen._nested_elem_types[t] = gen._elem_types[ev]
            continue
        use = gimple_ctypes.TypeLattice.list_suffix(et) if per_element else suf
        ev_cast = gen._cast_for_list(et, ev, use)
        # GIMPLE: load global string literals into temp before function call
        if use == 'str' and ev_cast.startswith('_slit_'):
            temp = gen._new_val('char *', f'{ev_cast}')
            ev_cast = temp
        gen._emit(f"  mojo_list_append_{use} ({t}, {ev_cast});")
        # A list whose elements are TUPLES (`[(a, b), (c, d)]`) — record
        # the tuple's own element type so a later `for x, y in lst:`
        # tuple-target loop reads each slot with the right accessor
        # (char* -> get_str, otherwise boxed int64 -> get_int). Set before
        # _dict_items_val_elems so a dict-item tuple never lands here.
        if et == 'MojoList *' and ev in gen._elem_types and t not in gen._dict_items_val_elems:
            gen._nested_elem_types.setdefault(t, gen._elem_types[ev])
            if ev in gen._tuple_slot_types:
                gen._tuple_slot_types[t] = gen._tuple_slot_types[ev]
        # Propagate dict value type from appended dict elements to the
        # list temp, so subsequent list[0]["key"] knows the dict value
        # type (char * vs int64_t vs double) — see BUG-2026-044.
        if et == 'MojoDict *' and ev in gen._dict_val_types:
            gen._dict_val_types[t] = gen._dict_val_types[ev]
    return 'MojoList *', t


def _lower_dict_literal(gen, node: gimple_ctypes.DictExpr) -> tuple[str, str]:
    t = gen._new_val('MojoDict *', "mojo_dict_new ()")
    # Infer value type from first pair (for subscript / iteration dispatch)
    if node.pairs:
        vt_sample = gen._quick_type(node.pairs[0][1])
        if vt_sample in gimple_ctypes._FLOAT_TYPES:
            gen._dict_val_types[t] = 'double'
        elif vt_sample == 'char *':
            gen._dict_val_types[t] = 'char *'
        else:
            gen._dict_val_types[t] = 'int64_t'
    for key_expr, val_expr in node.pairs:
        _emit_dict_pair_store(gen, t, key_expr, val_expr)
    return 'MojoDict *', t


def _emit_dict_pair_store(gen, t, key_expr, val_expr) -> None:
    """Emit one `mojo_dict_set_*` store of (key_expr → val_expr) into the
    dict temp `t`, shared by the dict-LITERAL lowering (`{k: v}` pairs)
    and the `dict(k=v, ...)` builtin's kwarg pairs — previously only the
    literal shape existed and `_lower_builtin_dict` silently DROPPED
    kwargs (`dict(prog="x")` built an empty dict), which surfaced as a
    runtime KeyError the moment the new dict-keyed `%`-formatting routed
    argparse.py's real `text % dict(prog=self._prog)` shape through it.
    Single source of truth for key coercion + per-type setter dispatch."""
    kt, kv = gen.lower_expr(key_expr)
    vt, vv = gen.lower_expr(val_expr)
    # Load global string literals into temps before passing to dict functions
    if kv.startswith('_slit_'):
        kv_tmp = gen._new_val('char *', f"{kv}")
        kv = kv_tmp
    elif kt in ('int', 'int64_t', '_Bool'):
        # Runtime dict keys are always char *; convert non-string keys
        # to strings via mojo_str_from_int (e.g. Int key 0 → "0") instead
        # of C-casting the int to char* which produces NULL for 0.
        kv = gen._new_val('char *', f"mojo_str_from_int({kv})")
    elif kt != 'char *':
        # A non-scalar key (tuple, list, or other struct/pointer type
        # — e.g. `{('a', 'b'): ...}`, real Python code found in the
        # stdlib's own _compat_pickle.py) used to fall into the SAME
        # mojo_str_from_int(kv) call above unconditionally: `kt !=
        # 'char *'` is true for ANY non-string key, not just an int,
        # so a tuple key's MojoList* pointer got passed to a
        # function expecting int64_t — "makes integer from pointer
        # without a cast", a hard GCC error, so the file never
        # compiled at all. Use the general-purpose repr-based
        # stringification instead: it already dispatches correctly
        # per-type (MojoList*/MojoDict*/other struct/float), giving
        # a value-based string distinct tuple/list contents won't
        # collide on — close enough to Python's own structural
        # hashing for this string-keyed runtime, and at least
        # compiles and round-trips consistently. Deliberately NOT
        # used for the plain int/bool case above: _repr_value's
        # int path (mojo_repr_int) returns a shared static buffer,
        # safe only because mojo_dict_set_str's callee immediately
        # strdup()s it — mojo_str_from_int's own heap-allocated
        # buffer is the already-proven-safe, unchanged behavior for
        # by far the most common dict-key type.
        kv = gen._repr_value(kt, kv)
    if vt in gimple_ctypes._FLOAT_TYPES:
        gen._emit(f"  mojo_dict_set_double ({t}, {kv}, {vv});")
    elif vt == 'char *':
        if vv.startswith('_slit_'):
            vv_tmp = gen._new_val('char *', f"{vv}")
            vv = vv_tmp
        gen._emit(f"  mojo_dict_set_str ({t}, {kv}, {vv});")
    else:
        # _lower_BoolLiteral returns ctype 'int' (not '_Bool'), same
        # as any other int — vt alone can't distinguish a real bool
        # literal from a genuine int, so check the AST node itself.
        if isinstance(val_expr, gimple_ctypes.BoolLiteral):
            gen._emit(f"  mojo_mark_dict_bool_values ({t});")
        vv64 = gen._to_int64(vt, vv)
        gen._emit(f"  mojo_dict_set_int ({t}, {kv}, {vv64});")


def _lower_set_literal(gen, node: gimple_ctypes.SetExpr) -> tuple[str, str]:
    t = gen._new_val('MojoSet *', "mojo_set_new ()")
    for el in node.elements:
        et, ev = gen.lower_expr(el)
        if et == 'char *':
            gen._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', t), ('char *', ev)])
        else:
            ev64 = gen._to_int64(et, ev)
            gen._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', t), ('int64_t', ev64)])
    return 'MojoSet *', t


def _lower_tuple_literal(gen, node: gimple_ctypes.TupleExpr) -> tuple[str, str]:
    # Tuples lowered as MojoList (immutable semantics not enforced at C level).
    # Tuples are heterogeneous by nature — e.g. ('int', 5) — so a single
    # list-wide append suffix would mis-type elements (append_str on an int).
    # Append each element by its own type when the tuple mixes string and
    # non-string elements; otherwise keep the list-wide suffix (same logic as
    # _lower_list_literal).
    elem = gen._infer_list_elem_type(node.elements)
    suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
    t    = gen._new_temp('MojoList *')
    # See _literal_elements_include_none's docstring (_lower_list_
    # literal's identical guard) — a tuple literal spelling out a
    # `None` element (`(x, None)`) must not be tagged elem-type
    # int64_t, or _list_repr_fn would route it through
    # mojo_repr_list_ints and silently misprint that `None` as `0`.
    if not (elem == 'int64_t' and gen._literal_elements_include_none(node.elements)):
        gen._elem_types[t] = elem
    gen._emit(f"  {t} = mojo_list_new ();")
    # Mark as a tuple (not a plain list) so generic repr() picks `(...)`
    # over `[...]` — see mojo_mark_as_tuple's doc comment in
    # runtime/mojo_runtime.c; there is otherwise no runtime distinction
    # between the two, since both lower to the same MojoList.
    gen._emit(f"  mojo_mark_as_tuple ({t});")
    lowered = [(el, *gen.lower_expr(el)) for el in node.elements]
    scalar_sufs = {gimple_ctypes.TypeLattice.list_suffix(et) for _el, et, _ev in lowered}
    # Any mix of suffixes (not just str-vs-other) needs per-element dispatch —
    # e.g. (Float64, Span*) both look like non-str, but list_suffix maps
    # Float64 -> 'double' and Span* -> 'int' (its generic pointer bucket), so a
    # single list-wide suffix would append-cast the pointer as a double.
    per_element = len(scalar_sufs) > 1
    # Record per-slot element types when elements are stored by their own
    # type — a later `for a, b in <list of these tuples>:` needs each
    # slot's real accessor (get_str vs get_int). The joined `elem` is
    # useless for a (char*, pointer) pair like `(name, func)`.
    if per_element:
        gen._tuple_slot_types[t] = [et for _el, et, _ev in lowered if not (isinstance(_el, gimple_ctypes.UnaryOp) and _el.op == '*')]
    for _el, et, ev in lowered:
        # A `*spread` element (`(el, *self.lower_expr(el))`, this codegen's
        # own pervasive comprehension pattern) must EXTEND the tuple with the
        # spread's elements, not append the container handle as one element
        # — the old append produced [el, <2-tuple handle>] (2 slots) where
        # callers unpack 3 ([el, et, ev]), reading garbage for et/ev (the
        # self-hosted compiled list-literal `[1, 2, 3]` emitted `_t3 = ;`
        # with raw-address type names). Mirrors _lower_list_literal's
        # identical _is_spread handling.
        if isinstance(_el, gimple_ctypes.UnaryOp) and _el.op == '*':
            gen._emit_call('void', '', 'mojo_list_extend', [('MojoList *', t), (et, ev)])
            continue
        use = gimple_ctypes.TypeLattice.list_suffix(et) if per_element else suf
        ev_cast = gen._cast_for_list(et, ev, use)
        # GIMPLE: load global string literals into temp before function call
        if use == 'str' and ev_cast.startswith('_slit_'):
            temp = gen._new_val('char *', f'{ev_cast}')
            ev_cast = temp
        gen._emit(f"  mojo_list_append_{use} ({t}, {ev_cast});")
    return 'MojoList *', t


def _lower_comprehension(gen, node: gimple_ctypes.Comprehension) -> tuple[str, str]:
    if not node.generators:
        t = gen._new_temp('int')
        # Skip emitting comment to avoid GIMPLE global-passing issues
        gen._emit(f"  {t} = 0;")
        return 'int', t

    gen0 = node.generators[0]

    if node.kind == 'list':
        res_type, res_new = 'MojoList *', 'mojo_list_new'
    elif node.kind == 'set':
        res_type, res_new = 'MojoSet *', 'mojo_set_new'
    elif node.kind == 'dict':
        res_type, res_new = 'MojoDict *', 'mojo_dict_new'
    elif node.kind == 'generator':
        # Generator expressions: convert to list for simplicity
        # (In a full implementation, these would be lazily evaluated)
        res_type, res_new = 'MojoList *', 'mojo_list_new'
    else:
        t = gen._new_temp('int')
        gen._emit(f"  /* TODO: comprehension kind {node.kind!r} */")
        gen._emit(f"  {t} = 0;")
        return 'int', t

    res = gen._new_val(res_type, f"{res_new} ()")

    # `for i, x in enumerate(seq)` / `enumerate(seq, start)` inside a
    # comprehension's `for` clause — a genuinely separate lowering path
    # from the generic dispatch below, which has no notion of pairing
    # an index with each element at all: falling through to it made
    # `lower_expr(gen0.iterable)` lower the CallExpr generically (a
    # direct call to the `mojo_enumerate` runtime shim, which only
    # takes 1 arg — "too many arguments to function 'mojo_enumerate'"
    # for the 2-arg `start=` form, e.g. Lib/gettext.py:114's
    # `{i: c for i, c in enumerate(_binary_ops, 1)}") and, even for the
    # 1-arg form, silently produced an EMPTY result (mojo_enumerate is
    # an identity passthrough returning the same list unchanged, then
    # _compr_list_loop's tuple-target branch treated each element as if
    # it were itself a sub-list/tuple to unpack — which a plain
    # enumerate()'d list never is). Handled directly here instead: lower
    # the underlying iterable once, then walk it by index, assigning
    # the (optionally start-offset) counter to the target's first slot
    # and each element to the second — mirrors `_gen_for_enumerate`'s
    # (the bare `for i, x in enumerate(...):` statement path) identical
    # index-loop shape.
    is_enumerate = (isinstance(gen0.iterable, gimple_ctypes.CallExpr) and
                     isinstance(gen0.iterable.func, gimple_ctypes.IdentExpr) and
                     gen0.iterable.func.name == 'enumerate' and
                     gen0.iterable.args)
    if is_enumerate:
        _inner_it_type, _inner_it_val = gen.lower_expr(gen0.iterable.args[0])
        _resolved = gen._get_actual_type(_inner_it_type, _inner_it_val)
        if _resolved != _inner_it_type and _resolved.endswith(' *'):
            _old_val = _inner_it_val
            _inner_it_val = gen._new_val(_resolved, f'({_resolved}){_inner_it_val}')
            if _old_val in gen._elem_types:
                gen._elem_types[_inner_it_val] = gen._elem_types[_old_val]
            if _old_val in gen._nested_elem_types:
                gen._nested_elem_types[_inner_it_val] = gen._nested_elem_types[_old_val]
        _inner_it_type = _resolved
        _start_val = None
        if len(gen0.iterable.args) >= 2:
            _, _start_raw = gen.lower_expr(gen0.iterable.args[1])
            _start_val = gen._new_val('int64_t', f"(int64_t){_start_raw}")
        if _inner_it_type == 'MojoList *':
            gen._compr_enumerate_loop(node, gen0, res, res_type, _inner_it_val, _start_val)
        else:
            gen._emit(f"  /* TODO: enumerate comprehension over {_inner_it_type} */")
        return res_type, res

    is_range = (isinstance(gen0.iterable, gimple_ctypes.CallExpr) and
                isinstance(gen0.iterable.func, gimple_ctypes.IdentExpr) and
                gen0.iterable.func.name == 'range')

    it_type = ''
    if not is_range:
        it_type, it_val = gen.lower_expr(gen0.iterable)
        # Resolve a pointer stored as int64_t (e.g. from a method call
        # returning a list) to its real tracked type — mirrors
        # _gen_for_iter's identical call, which this comprehension path
        # was missing entirely. Without it, a heterogeneous MojoList*
        # merely *typed* int64_t at this call site (its real type only
        # recoverable via _actual_types) fell through every branch below
        # to the unsupported-iterable fallback, silently producing zero
        # elements — e.g. `[s for s in body if isinstance(s, (VarDecl,
        # AssignStmt))]` in Parser._parse_struct always returned [].
        _resolved_type = gen._get_actual_type(it_type, it_val)
        if _resolved_type != it_type and _resolved_type.endswith(' *'):
            # it_val's C-declared storage is still int64_t even though we
            # now know its real pointer type — cast it, mirroring
            # _gen_for_list's identical `list_ptr = (MojoList *)it_val`
            # pattern, or every mojo_list_len/mojo_list_get_int(it_val)
            # call below passes a bare int64_t where a pointer is
            # expected ("makes pointer from integer without a cast").
            _old_it_val = it_val
            it_val = gen._new_val(_resolved_type, f'({_resolved_type}){it_val}')
            # Preserve element-type tracking under the new temp's name —
            # otherwise _elem_of(it_val) below misses it (only the OLD
            # name was tracked), silently defaulting the loop variable to
            # int64_t and corrupting any downstream string/struct access.
            if _old_it_val in gen._elem_types:
                gen._elem_types[it_val] = gen._elem_types[_old_it_val]
            if _old_it_val in gen._nested_elem_types:
                gen._nested_elem_types[it_val] = gen._nested_elem_types[_old_it_val]
            if _old_it_val in gen._generator_var_api:
                gen._generator_var_api[it_val] = gen._generator_var_api[_old_it_val]
        it_type = _resolved_type

    if is_range:
        gen._compr_range_loop(node, gen0, res, res_type)
    elif it_type == 'MojoList *':
        gen._compr_list_loop(node, gen0, res, res_type, it_val)
    elif it_type == 'MojoStr *':
        gen._compr_str_loop(node, gen0, res, res_type, it_val)
    elif it_type == 'char *':
        gen._compr_cstr_loop(node, gen0, res, res_type, it_val)
    elif it_type == 'MojoDict *':
        gen._compr_dict_loop(node, gen0, res, res_type, it_val)
    elif it_type == 'MojoSet *':
        gen._compr_set_loop(node, gen0, res, res_type, it_val)
    elif it_type == 'MojoGenerator *':
        gen._compr_generator_loop(node, gen0, res, res_type, it_val)
    else:
        gen._emit(f"  /* TODO: comprehension over {it_type} */")

    return res_type, res

# fp-probe
