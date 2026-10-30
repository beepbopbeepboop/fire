# CODEGEN: a class-level attribute that reads an enclosing local is silently 0

## Status (2026-10-29, round 7: the silent cases are fixed; two residuals remain)

The original symptom: a `class` statement inside a function body whose
non-literal class attribute names a local (`__version__ = version`) lowered
to nothing, so the attribute read 0 and the program exited 0.

Landed (plain-function and struct-method bodies; generators unchanged):

- **Value is stored at the `class` statement** (`emit_stmts.py`
  `_gen_stmt_StructDef`).
- **Per-execution storage** (commit dc7643036 on this branch). Each
  execution of the `class` statement allocates a fresh cell for each
  non-constant attribute; instances keep the cell they were built under
  (hidden `_clscell_<attr>` field). `a = make(5); b = make(7); a.__version__`
  prints `5`, as CPython does.
- **Save/restore of the current cell** (this round, `emit_methods.py`
  `_cattr_restore_begin` / `_cattr_snapshot` / `_cattr_restore_emit` /
  `_cattr_restore_fallthrough` / `_cattr_restore_end`, wired in
  `emit_funcs.py` (both body paths), `emit_stmts.py` (`return`, and the
  `try`/`assert_raises` exception edges)). The cell global is shared by every
  execution of its function, so a nested or recursive call that runs the same
  `class` statement used to leave the caller reading the callee's cell.
  Measured before this round: `f(5, 1)` with a recursive `f` printed `6 6 6 6`
  (CPython `6 6 5 5`). Now it prints `6 6 5 5`. The function restores its
  entry values at every `return` and at a reachable fall-through end; a caught
  exception restores the values the `try` started with (its own cell), since
  the entry value is the caller's.
- Functions with no such class emit nothing new, so their C is unchanged.

Regression tests (`test_nested_class_attr_cross_execution_regression.py`,
all PASS; each of the three new ones fails with its fix disabled):

- `gimple_nested_class_attr_cross_exec`: `5 7 9 5` (per-execution cells).
- `gimple_nested_class_container_attr_cross_exec`: `1 2`.
- `gimple_nested_class_attr_recursive`: `6 5 7` (save/restore, fall-through and bare return).
- `gimple_nested_class_attr_recursive_return`: `5 9` (restore before `return <value>`).
- `gimple_nested_class_attr_exception_unwind`: `caught 5` (the handler restores its own cell; fails with `6` when that restore is disabled).
- `test_gimple_runner.py` nested-class cases (`5 7`, `3`): still green. The
  file's total is 477 passed, 4 failed; the four failures are unrelated
  programs with no class statement, and they fail the same way without this
  change (`gimple_struct_mixed_reads_survive_a_derivation`,
  `gimple_heterogeneous_list_literal_keeps_each_slot`,
  `gimple_struct_mixed_reads_survive_a_function_boundary`,
  `gimple_ctor_param_polymorphic_slot_reads_receiver`).

Still open:

1. **A catch in a DIFFERENT function still leaves the cell wrong** (SILENT,
   reproduced, `.tmp/resid.py` shape). `x(v, d)` defines `T`, and calls
   `h(v + 1, d - 1)`, which calls `x(v, d)` inside a `try`. The inner `x`
   raises, `h` catches it, and `x` then reads `T.__version__`. `h` restores
   only its own cells (it defines none), so `x` reads the inner cell: `6`,
   CPython `5`. Closing it needs the restore to run during UNWINDING, not at a
   catch site. Next step: a new cleanup-stack kind in `runtime/fire_runtime.c`
   (`_mojo_cleanup_push` with a saved-value record that writes back the global
   on pop and on longjmp unwind), pushed at the save in
   `emit_methods._cattr_restore_begin` and popped where `emit_return_frees`
   and the fall-through frees run. That is a runtime and ownership-machinery
   change, so it is deliberately not done in this round.
2. **Same name in two functions.** Two classes both called `T`, in different
   functions, make class-name attribute reads resolve to the first one. That
   is separate from the cell work and reproduces with literal attributes:
   `CODEGEN_same_named_function_scoped_classes_share_class_attrs.md`.
3. **A class OBJECT that escapes its function** (`return Tag`, then used
   later). Measured: `def mk(v): class Tag: __version__ = v; return Tag`,
   `A = mk(5); B = mk(7); print(A.__version__)`, and `A().__version__` both
   fail LOUDLY today (`Unhandled exception: AttributeError: __version__`,
   exit 1), not with a wrong number. Closing it needs the class object as a
   runtime value: a separate, larger project. Until then the loud failure is
   the honest behaviour, and a silent answer has not been observed for this shape.
4. **Leak.** One heap cell per non-constant attribute per execution of the
   `class` statement, never freed (same class as
   `CODEGEN_closure_env_and_boxed_local_never_freed.md`). A `class` statement
   in a hot loop leaks about 8 bytes per attribute per iteration.
5. **Container defaults with no initializer** (`var xs: List[Int]` in a class
   body) are still per-class globals seeded by the allocator, not per execution.
6. **Generators** are unchanged: `mojo/middle/coro.py`
   `_nested_class_nonliteral_attr` still refuses a generator whose nested class
   has a non-literal class attribute (`nested_class_local_attr_refused` in
   `test_gimple_generator_runner.py`). The `cpp_*` readers still use the global.

Earlier planning rounds (1-6, 2026-10-29) are in git history on this branch;
their designs were superseded by the cell design above.
