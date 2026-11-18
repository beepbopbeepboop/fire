# CODEGEN: a `comptime if` over an alias whose type argument is NOT a builtin still becomes a runtime branch on a zero word

## What I ran

The same synthetic module the now-fixed imported-generic-alias bug used, with
a non-builtin type argument (`String` is a stdlib struct with a user
`__deinit__`, so `IsTriviallyDeinitable[String]` is `False`):

    from std.traits import IsTriviallyDeinitable

    def maybe[T: AnyType](n: Int) -> Int:
        comptime if IsTriviallyDeinitable[T]:
            return 1
        else:
            return 2

    def use(n: Int) -> Int:
        return maybe[String](n)

    python3 - <<'EOF'
    import build_stdlib_dylib as b
    c = b.compile_module_to_c(open('p.mojo').read(), 'p.mojo', 'p', linkable=False)
    print(c)
    EOF

## What I saw

The alias APPLICATION is now recognised (`IsTriviallyDeinitable` is no longer
an undeclared name in the general case), but its body cannot be decided for
this argument, so `eval_const_bool_state` still answers CONST_UNKNOWN and
`_gen_stmt_ComptimeIfStmt` emits the runtime branch on the placeholder:

    int64_t maybe_1_T_6_String (int64_t n)
    {
      ...
      _t1 = (int64_t)0;  /* ct param or undeclared: IsTriviallyDeinitable */
      ...
      _t3 = (MojoList *)_t4;
      _t5 = mojo_list_get_int (_t3, _t2);
      if (_t5) goto bb_5; else goto bb_4;
      ...
    }

At run time this reads a NULL `MojoList *`; the source's condition is FALSE,
so only the else arm (`return 2`) should exist.

## Why it is not the fixed bug

The fix in the preceding commit keeps the alias declaration and substitutes an
application's arguments into its body. What it does NOT have is any fact about
a type the compiling module does not declare: `conforms_to(String,
TrivialRegisterPassable)` is answered from that module's own
`_struct_bases`/`_trait_bases` plus the builtin-scalar table, and `String` is
neither. So the body's `conforms_to(T, ...) or (...)` stays unknown.

`IsTriviallyDeinitable[T]` is not the only shape: any generic comptime alias
whose RHS asks a conformance question about its parameter has this hole for a
foreign struct argument.

## Exact next step

Either, in `mojo/backend_gimple/emit_infra.py::_conforms_to_pred` / the shared
`mojo/middle/comptime.conforms_to`:

1. Resolve a foreign struct's declared bases from its OWN module's AST (the
   importer already has `gen._find_imported_struct` / `_find_symbol_home_module`
   and `_parsed_import`), and derive triviality with the rule
   `ownership_check._struct_def_is_trivial` already implements (no user
   `__deinit__`, no user copy/move constructor, trivial fields). Feed the
   result into the same bases map. Measured answers this must produce:
   `conforms_to('String', 'TrivialRegisterPassable') is False`,
   `conforms_to('Int', 'TrivialRegisterPassable') is True` (already true).

or, until that exists:

2. Make the CONST_UNKNOWN arm of `_gen_stmt_ComptimeIfStmt` refuse when the
   condition is an application of a generic comptime alias that failed to
   fold (a visible error naming the condition and the type argument), so the
   dylib build falls back to source instead of emitting a NULL-dereferencing
   body. Do NOT refuse every CONST_UNKNOWN condition: rule 2 in
   `mojo/middle/comptime.py` deliberately degrades an opaque condition to a
   runtime branch, and the stdlib relies on it.

## Done when

`test_comptime_generic_alias_fold.py` gains a `maybe[String]` case asserting
the instance body has no `ct param or undeclared: IsTriviallyDeinitable`, no
`mojo_list_get_int`, no runtime `if (`, and contains `return 2` (the FALSE
arm). The same assertion then holds for any foreign struct argument.
