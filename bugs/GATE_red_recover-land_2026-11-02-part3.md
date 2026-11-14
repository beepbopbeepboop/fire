# A container-annotated parameter is not "provably Int" in the membership diagnostic (part 3)

Part 3 of 5 of `bugs/hard/GATE_red_recover-land_2026-11-02.md`. Class: easy —
one predicate's input (`_definitive_binding_type`), plus its regression case.
This is measured to be red on its own **and** it is the reason
`bootstrap-stage1-transitive` currently reports
`# ERROR: compiling imported module 'mojo.middle.exprtypes'`.

## Measured (2026-11-13, this tree)

    def has(x, names: frozenset | None = None) -> bool:
        return x in names

`compile_to_gimple(src)` raises, 0.1 GB, under a second:

    RuntimeError: 'Int' does not implement the '__contains__' method

The same failure in the closure path (measured by compiling
`ownership_destruct.py` with `do_imports=True`):

    # ERROR: compiling imported module 'mojo.middle.exprtypes' from …/mojo/middle/exprtypes.py:
    'Int' does not implement the '__contains__' method

`CLOSURE_INCOMPLETE` matches `# ERROR: compiling imported module`, so
`bootstrap-stage1-transitive` is red from this alone. The line in the compiler's
own source is `mojo/middle/exprtypes.py:1126`
(`_frt[:-2] in known_structs`), where
`known_structs: frozenset | None` — measured by instrumenting
`_membership_container_type`, which reported `CONTAINER Int … name known_structs`.

Root cause: `_definitive_binding_type` (`emit_exprs.py:6318`) treats every
parameter annotation that is not one of the function's type parameters, not
`AnyType`, and not empty as "a concrete scalar annotation" and answers `'Int'`
(`emit_exprs.py:6369`). `frozenset | None` lowers to `int64_t` (a boxed word),
so a container-typed parameter is claimed to be an Int.

The previous fix in this area (`32d9c79c7`) closed the *call-result* half of the
same over-claim; this is the annotation half it did not cover.

## Goal

`_definitive_binding_type` answers `'Int'` only when the parameter's annotation
itself resolves to a scalar int C type — through the same annotation-to-C-type
resolver every annotation already goes through — never merely because it is not
generic. In particular:

- `Int`, `int`, and any annotation resolving to `int64_t`/`int` -> `'Int'`;
- `frozenset | None`, `dict | None`, `list[Int]`, `str | None`,
  `MojoList *`-shaped annotations -> `None` (keep runtime dispatch);
- `Bool` -> `'Bool'`, `Float64` -> `'Float64'` (unchanged);
- an unresolved generic parameter, `AnyType`, or an empty annotation -> `None`
  (unchanged).

Do not special-case `frozenset`; the rule is about the resolved C type. Do not
add a second annotation classifier: the existing resolver that `_quick_type` /
`_mojo_type` use is the one to ask.

## Acceptance

- `def has(x, names: frozenset | None = None): return x in names` compiles
  (no RuntimeError) and the emitted membership stays the runtime-dispatch form.
- `mojo/middle/exprtypes.py` compiles in the closure: no `# ERROR: compiling
  imported module 'mojo.middle.exprtypes'`.
- The diagnostic still rejects the provable-scalar cases: `x in y` with
  `x: Int, y: Int`; `y: Float64`; `y: Bool`; `1 in len(s)`; `1 in int(s)`;
  `1 in n()` with `n() -> Int`.
- A parameter with a scalar annotation still rejects (`a: Int`, `x in (a + 1)`).
- No stdlib module gains a `skip <module>:` (this diagnostic's earlier
  over-claim cost six `stdlib-dylib` modules).

## Done when

File: `test_contains_method_diagnostic.py` (repo root; existing file — add the
case beside `test_unannotated_call_result_is_not_provably_int`).

Command: `python3 test_contains_method_diagnostic.py`

The new case is
`test_container_typed_parameter_is_not_provably_int`: it `_expect_ok(...)`s the
`frozenset | None` repro above and a `dict | None` variant. Red today: the
repro raises `'Int' does not implement the '__contains__' method`.

## Where to start

- `mojo/backend_gimple/emit_exprs.py:6318` `_definitive_binding_type`, the
  `ctype in ('int', 'int64_t')` arm and its `return 'Int'` at line 6369. The
  annotation is read out of `_current_func_node`'s `params`/`param_types`
  there; ask the type resolver what that annotation lowers to instead of
  deciding from "not a type param".
- `test_contains_method_diagnostic.py` — the existing cases that must stay red
  (scalar) or green (erased) are the guard rail.
