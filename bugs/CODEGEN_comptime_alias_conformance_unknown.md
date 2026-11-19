# CODEGEN: a `comptime if` over a comptime alias whose conformance question is undecidable still becomes a runtime branch on a zero word

## What I ran

The same synthetic module the (now fixed) imported-generic-alias fold bug
used, with a type argument whose `conforms_to` answer this compiler cannot
decide. Two measured cases:

    # 1. a stdlib struct: String has a user __deinit__, so the answer is False
    from std.traits import IsTriviallyDeinitable

    def maybe[T: AnyType](n: Int) -> Int:
        comptime if IsTriviallyDeinitable[T]:
            return 1
        else:
            return 2

    def use(n: Int) -> Int:
        return maybe[String](n)

    # 2. a builtin against a trait the MODULE declares: Int cannot conform,
    #    but the answer is not known because Int is not a declared struct
    trait Widget:
        pass

    comptime is_widget[T: AnyType]: Bool = conforms_to(T, Widget)

    def pick[T: AnyType](n: Int) -> Int:
        comptime if is_widget[T]:
            return 1
        else:
            return 2

    def use(n: Int) -> Int:
        return pick[Int](n)

    python3 - <<'EOF'
    import build_stdlib_dylib as b
    c = b.compile_module_to_c(open('p.mojo').read(), 'p.mojo', 'p', linkable=False)
    print(c)
    EOF

## What I saw

Both instances are emitted with the alias name still lowered to the
undeclared-identifier placeholder, and the condition is a runtime branch on a
NULL boxed list:

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

and the same shape for `pick_1_T_3_Int` with `is_widget`. At run time both
read a NULL `MojoList *`; the source's answers are False (`String` has a user
`__deinit__`; `Int` does not declare `Widget`), so only the else arm should
exist.

## Why it is not the fixed bug

The fix in the preceding commits keeps a generic alias's declaration and
substitutes an application's arguments into its body, and it knows the
builtin scalars' `TrivialRegisterPassable` conformance (they are not source
structs). What it does not have is an answer for any OTHER type the compiling
module does not itself declare: `conforms_to(String, TrivialRegisterPassable)`
and `conforms_to(Int, Widget)` are both undecidable from `_struct_bases`,
`_trait_bases` and `_conformance_bases_extra`, so the body folds to None,
`_const_foldable` says unknown, and `_gen_stmt_ComptimeIfStmt` emits the
runtime branch on the placeholder.

## Exact next step

Either:

1. Resolve a foreign struct's declared bases from its OWN module's AST (the
   importer already has `gen._find_imported_struct`, `gen._find_symbol_home_module`
   and `gen._parsed_import`) and derive triviality with the rule
   `ownership_check._struct_def_is_trivial` already implements (no user
   `__deinit__`, no user copy/move constructor, all fields trivial). Feed the
   result into the same bases map. Measured answers this must produce:
   `conforms_to('String', 'TrivialRegisterPassable') is False`,
   `conforms_to('Int', 'TrivialRegisterPassable') is True` (already true).

2. Decide the NEGATIVE for a module-local trait: a builtin scalar can never
   conform to a trait this module declares, so `conforms_to('Int', 'Widget')`
   is False once `Widget` is known to be a declared trait. That closes case 2
   without any foreign-struct lookup. Be careful to leave a stdlib trait the
   scalar DOES conform to (`Writable`, ...) at None, not False.

3. Until either exists, make the CONST_UNKNOWN arm of
   `_gen_stmt_ComptimeIfStmt` refuse when the condition is an application of a
   generic comptime alias that failed to fold (a visible error naming the
   condition and the type argument), so a dylib build falls back to source
   instead of emitting a NULL-dereferencing body. Do NOT refuse every
   CONST_UNKNOWN condition: rule 2 in `mojo/middle/comptime.py` deliberately
   degrades an opaque condition to a runtime branch, and the stdlib relies on
   it. Also expect the stdlib-dylib `skip <module>:` count to move if a real
   module carries an erased-signature instance of this shape, so land 1 or 2
   rather than this one where the ratchet cannot take an increase.

## Done when

`test_comptime_generic_alias_fold.py` gains the two cases above, each asserting
the instance body has no `ct param or undeclared:` for the alias, no
`mojo_list_get_int`, no runtime `if (`, and contains the FALSE arm
(`return 2`).
