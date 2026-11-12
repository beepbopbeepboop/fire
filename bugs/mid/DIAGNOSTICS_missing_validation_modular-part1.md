# DIAGNOSTICS_missing_validation_modular part 1: `where (cond, "message")` enforcement

Part 1 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
Plan: `docs/diagnostics-missing-validation-plan.md` §1 (the partially-landed
generic constraint step). The other clusters of the umbrella are already filed
as their own docs (`DIAGNOSTICS_trait_conformance.md`,
`DIAGNOSTICS_elaboration_recursion.md`, `DIAGNOSTICS_inferred_param_dependency.md`,
`DIAGNOSTICS_binding_deferrals.md`, `DIAGNOSTICS_align_decorator.md`,
`DIAGNOSTICS_mlir_annotations.md`, `DIAGNOSTICS_lsp_error_recovery.md`,
`DIAGNOSTICS_docstring_self_import.md`, `DIAGNOSTICS_mojoc_imports.md`,
`GPU_offload_validation_modular.md`); this part does not duplicate them.

## Why this part

Modular's `test/mojo-parser/decls/where_message_errors.mojo` requires three
things from a `where` clause that carries an optional message:

- a provably-false integer/boolean condition is rejected:
  `error: invalid call to 'gated_fn': violated constraint`, and the note names
  the user message (`scaling factor must be greater than 1`);
- a struct body constraint is enforced at instantiation:
  `var x = ViolatedStruct[-1]` is `error: violated constraint`, and the note
  names `N must be positive`.

Measured in this tree (2026-11-10), both compile silently. Both
`def fn_msg[sc: Int]() where (sc > 1, "...")` called as `fn_msg[1]()` and
`struct StructMsg[N: Int] where (N > 0, "...")` instantiated as
`StructMsg[-1]()` produce no diagnostic, and the true-value forms compile too.
Two independent causes:

1. `fire_compiler.py` discards the clause. `_parse_funcdef` skips tokens after
   `where` up to `:`/`NEWLINE`/`EOF` (`fire_compiler.py` around line 4603),
   and `_parse_structdef` does the same after the base list (around line 4843).
   `vars(FunctionDef)` / `vars(StructDef)` have no `where` field, so the parsed
   condition and its message are unrecoverable.
2. `elaborate.py::check_where_clauses` is a regex over the template text and
   only recognises `X.is_floating_point()`, `X.is_integral()`, and `T == U`
   (`elaborate.py` around line 615). Comparisons such as `N > 0` and the
   `(cond, "message")` tuple form are invisible to it.

The existing `test_where_clause_call_site_diagnostic.py` (DType predicates)
must keep passing; this part extends that path, it does not replace it with a
second evaluator.

## Scope

1. **Retain the clause on the AST.** In `fire_compiler.py`, where
   `_parse_funcdef` and `_parse_structdef` currently skip `where`, parse the
   clause(s) into a new field (e.g. `where_clauses: list`) with the default
   empty so every existing reader is unaffected. Each entry is the condition
   expression plus `msg: str | None`.
   - Multiple clauses: `where (a > 0, "a") where (b > 0, "b")` must produce two
     entries.
   - `where (cond, "msg")` is a message clause only when the parenthesised
     expression is a two-element tuple whose second element is a string
     literal. A parenthesised single condition such as
     `where (x > 0 and x < 10)` is one condition with no message (the
     `wrapping_cond` case in `test/mojo-parser/decls/where_message.mojo`).
   - The same handling is wanted for a function and a struct. Leave the
     unrelated `where` skips (a `comptime` alias, a trait base list) alone
     except where they share this helper.
2. **Evaluate the clause with the shared constant folder.** In
   `elaborate.py`, replace the regex-only checks with evaluation through
   `mojo.middle.comptime.eval_const_bool_state` (or
   `eval_const_bool`/`eval_const_bool_state` as appropriate), using bindings
   built from the instantiation's `targs`. `targs` values are strings; convert
   an integer literal to `int` and `true`/`false` to `bool`, and leave an
   unknown argument out. Keep the existing DType-predicate result by falling
   back to the present predicate checks only if the folder cannot evaluate a
   predicate; do not maintain two independent implementations of the same
   rule.
   - `False` → raise `ConformanceError` whose text includes the clause's
     message when present, otherwise the clause source.
   - `None` (inconclusive) → keep today's accept behaviour in this part. Do
     **not** turn an unprovable clause into an error yet: a function body may
     have proved it with a preceding `comptime assert` (modular's
     `test_assert_enables_where_constraint` calls `requires_natural[x](y)`
     after `comptime assert x >= 0`). Rejecting inconclusive clauses without
     that assumption machinery is a regression, and the `lacking evidence`
     note is a separate follow-up.
   - `True` → no diagnostic.
3. **Surface it at both instantiation sites.** `emit_resolve.py` already
   re-raises a `ConformanceError` from a generic function call as
   `error: invalid call to '<fn>': violated constraint`. Make sure the struct
   instantiation path (`_ensure_generic_struct` / `elaborate_generic_struct`
   and `elab_intu`'s materialization) calls `check_bounds` and propagates the
   same diagnostic instead of swallowing it. A satisfied clause must continue
   to compile exactly as now.
4. Do not change alignment, layout, or codegen semantics. This part adds
   diagnostics only.

## Acceptance

Add `test_where_message_diagnostic.py` beside
`test_where_clause_call_site_diagnostic.py`. Compile snippets with
`compile_to_gimple(src, do_imports=True, filename=<real temp file>)`, because
the elaborator reads the template back from the file (the same helper shape as
`test_align_decorator_parametric_diagnostic.py` and
`test_where_clause_call_site_diagnostic.py`).

| source | expected |
|---|---|
| `def gated_fn[sc: Int]() where (sc > 1, "scaling factor must be greater than 1")` called as `gated_fn[0]()` | `RuntimeError` containing `invalid call to 'gated_fn': violated constraint` and `scaling factor must be greater than 1` |
| the same with `gated_fn[2]()` | compiles |
| `struct ViolatedStruct[N: Int] where (N > 0, "N must be positive")` instantiated `ViolatedStruct[-1]()` | diagnostic containing `violated constraint` and `N must be positive` |
| `ViolatedStruct[5]()` | compiles |
| `where (N > 0 and N < 10, "N must be in (0, 10)")` with `-1` and with `5` | false gives the message; true compiles |
| `def f[x: Int]() where (x > 0 and x < 10)` called `f[20]()` | `violated constraint` (parenthesised single condition) |
| `comptime assert x >= 0` followed by `requires_natural[x](y)` where `requires_natural` has `where x >= 0` | compiles (inconclusive stays accepted in this part) |

Run, in this order and only these:

    python3 test_where_message_diagnostic.py
    python3 test_where_clause_call_site_diagnostic.py

No suite registration is added by this part, and no whole-closure compile is
needed. The modular `where_message_errors.mojo` itself lives outside this
worktree; the snippets above are its reduced, in-tree equivalents.

## Status
- **Open.**
