# CODEGEN: a `comptime if` over an imported comptime alias becomes a runtime branch on a zero boxed value

## What I ran

A synthetic module with the real `std.traits` alias and a generic whose body
is `std/memory/memory.mojo`'s `unsafe_destroy_n` shape, instantiated in the
same translation unit:

    from std.traits import IsTriviallyDeinitable

    def maybe[T: AnyType](n: Int) -> Int:
        comptime if IsTriviallyDeinitable[T]:
            return 1
        else:
            return 2

    def use(n: Int) -> Int:
        return maybe[Int](n)

    python3 - <<'EOF'
    import build_stdlib_dylib as b
    c = b.compile_module_to_c(open('p.mojo').read(), 'p.mojo', 'p', linkable=False)
    print(c)
    EOF

## What I saw

The instantiation is emitted (`maybe_1_T_3_Int`) but its `comptime if` is
NOT folded:

    int64_t maybe_1_T_3_Int (int64_t n)
    {
      ...
      _t1 = (int64_t)0;  /* ct param or undeclared: IsTriviallyDeinitable */
      ...
      if (_t6) goto bb_5; else goto bb_4;
    }

The same shape is emitted for `std/memory/memory.mojo`'s
`unsafe_destroy_n`, whose real body is

    comptime if IsTriviallyDeinitable[T]:
        pass
    else:
        for i in range(count):
            pointer.unsafe_offset(i).unsafe_deinit_pointee()

measured in the defining module's generated C when the cross-module
generic-instance pre-pass appends the erased-signature instance
(`bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs` part 9): the body
evaluates the alias call as a boxed class reference, reads it as a
`MojoList *`, and emits `mojo_list_get_int(0, 0)` as the branch condition.
For `T = Int` the source's condition is TRUE, so the emitted branch is not
the program the source describes; at run time it dereferences a NULL list.

This is NOT specific to the appended-instance path: the same synthetic
module compiled normally (a local `maybe[Int](n)` call, in-TU instantiation)
produces the same unfolded branch. So the root cause is the `comptime if`
evaluator, not the cross-module pre-pass.

## Why it matters

`IsTriviallyDeinitable[T]` is a module-level `comptime` alias in
`std/traits/deinitable.mojo`:

    comptime IsTriviallyDeinitable[T: AnyType]: Bool = conforms_to(
        T, TrivialRegisterPassable
    ) or (conforms_to(T, Deinitable) and downcast[T, Deinitable].__del__is_trivial)

The evaluator (`mojo/middle/comptime.py`) sees `IsTriviallyDeinitable` as an
undeclared name. The importer DOES try to fold an imported `comptime` value:
`module_gen`'s `from X import NAME` walk calls `_gmi_find_comptime_one`,
which matches the `ComptimeVarStmt` and calls `_eval_const` on its RHS. But
`IsTriviallyDeinitable` is a GENERIC alias — its RHS mentions the unbound
bracket parameter `T` — so that import-time evaluation returns None and
nothing is recorded. The alias needs its bracket arguments substituted at
the CALL (`IsTriviallyDeinitable[Int]`), which the import-time walk cannot
do. When the condition is CONST_UNKNOWN, `_gen_stmt_ComptimeIfStmt` emits a
RUNTIME branch on the lowered expression instead of refusing, and the
lowered expression is a class-ref/boxed word that reads as address 0.

So every generic whose body dispatches on an imported comptime alias (not
just this one) gets a silently wrong body the first time it is instantiated.
`unsafe_destroy_n` is the first measured instance because
`std/collections/array.mojo` calls it from an erased generic method, where
the caller cannot elaborate.

## Expected

Either:

1. `comptime if` over an imported module-level `comptime` alias folds — the
   importer's bindings map should include the alias (and a generic alias
   should be substituted for its type arguments, the way a local alias is),
   so `IsTriviallyDeinitable[Int]` evaluates to `True` and only the `pass`
   branch is emitted; or
2. a CONST_UNKNOWN `comptime if` condition is an honest refusal (the same
   disposition `_fn_template_has_comptime_control` gives a template it
   cannot instantiate), never a runtime branch on a zero boxed value.

Option 2 is also what the dylib contract wants: a reference left undefined
falls back to source, while a defined wrong body is a silent miscompile.

## Exact next step

1. Keep a generic comptime alias's RHS AST instead of only its evaluated
   value: in `module_gen`'s `from X import NAME` walk, when
   `_gmi_find_comptime_one`'s `_eval_const(_cn.value)` returns None because
   the RHS mentions a bracket parameter, record `(params, RHS)` as an alias
   template.
2. Teach `mojo/middle/comptime.py`'s call path for `NAME[args]` to bind the
   alias's bracket parameters to the call's arguments and evaluate the RHS —
   the same substitution `_eval_parametrized_aliases` already does for struct
   fields (`elab_intu.py`).
3. Add the synthetic `maybe[Int]` case above to `test_gimple.py` (or the
   comptime tests) and assert the emitted C has NO `ct param or undeclared:
   IsTriviallyDeinitable` and no runtime branch for the condition.
4. Until then, `_gen_stmt_ComptimeIfStmt`'s CONST_UNKNOWN arm should refuse
   (a visible error naming the condition) rather than emit the runtime
   branch, so a future instance cannot ship a NULL-dereferencing body.
