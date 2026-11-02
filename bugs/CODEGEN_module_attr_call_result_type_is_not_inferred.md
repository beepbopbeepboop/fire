# CODEGEN: a call through a bare module attribute (`import m; m.f(...)`) is typed `int64_t` where the result is consumed by inference, so a `str` prints as a pointer integer

## Status

OPEN, 2026-10-29, filed from `work/bug-compile-fail-ctypes-util` while fixing
the parameter half of the same shape (see the test
`test_link_mode.py::test_cross_module_unannotated_param_takes_the_callers_literal_type`,
which pins the part that now works). The parameter half is FIXED: an unannotated
imported function's `str`/`bytes`/container literal arguments now reach the
defining module's parameter types. What is left is the RESULT half, below.

## What I ran, and what I saw

Sibling `_shm.py` is `def which(cmd, path=None):\n    return cmd\n` (no return
annotation). Each program was compiled with `driver.compile_program` (default
link mode) and run; CPython prints `gcc` for every one.

| main module | compiled output | verdict |
|---|---|---|
| `import _shm`; `print(_shm.which('gcc'))` | `gcc` | correct |
| `import _shm`; `def f(): x = _shm.which('gcc'); print(x)`; `f()` | `gcc` | correct |
| `from _shm import which`; `print(which('gcc'))` | `gcc` | correct (after the parameter fix) |
| `import _shm`; `x = _shm.which('gcc')` at MODULE scope; `print(x)` | `4299312296` | **WRONG** — pointer printed as an int, exit 0 |
| `import _shm`; `def find(n): c = _shm.which('gcc'); if not c: return None; return c`; `print(find(1))` | `4343434384` | **WRONG** — `find`'s own return type is inferred `int64_t` |

The `find` row is the one `ctypes/util.py` hits in shape (its `find_library`
binds `shutil.which('gcc')` to a local and then returns through other
paths). The module-scope row is the same defect for a global.

Before the parameter fix the first and third rows were ALSO wrong
(`4343434384` / `4371090576`); the module-scope row was wrong with an
annotated `-> str` sibling as well (`annotated_str_nomodpath`), so this is not
caused by the unannotated return.

## What is established

- The CALL's own result ctype is correct: with the parameter fix in place,
  the call site's `_func_csym` mirror reads `home='char *'` and
  `bare_slot='char *'` for `_shm_which_e253d6` (traced, both the bare-import
  and the function-scoped rows).
- So the wrong type is assigned by the INFERENCE that types the enclosing
  global or the enclosing function's return, not by the call lowering.
- `mojo/middle/exprtypes.py` `_infer_simple_expr_ctype` resolves a
  `CallExpr` by callee shape: an `IdentExpr` callee via `fn_return_types`
  (around line 1041), and a `MemberExpr` callee only through a hard-coded list
  of stdlib method names (`format`, `replace`, `strip`, `join`, `split`, ...,
  around line 1046 onwards). A `MemberExpr` callee whose object is an IMPORTED
  MODULE binding is never consulted against `fn_return_types` /
  `_home_def_return_type`, so the answer falls through to the `int64_t`
  default.
- The module-scope global is typed from the same function, and it runs before
  the sibling is compiled, so `_home_def_return_types` is still empty at that
  point. That is the same ordering problem as
  `bugs/CODEGEN_a_module_scope_global_bound_to_a_container_returning_call_is_a_box.md`
  (same-module `f = mk()` with a container return is also `int64_t`).

## Exact next step

1. In `_infer_simple_expr_ctype`, add a branch for `CallExpr` whose callee is
   `MemberExpr(obj=IdentExpr(B), member=F)` where `B` is a bare-import binding
   (`ImportStmt`, unaliased or aliased, not a `from` binding). Resolve `F`
   through the SAME home-store answer the call lowering uses
   (`_home_def_return_type(gen, <qualifier of B's module>, F)`, falling back to
   `fn_return_types`), and only for the shapes that are already trusted
   (`char *`, `MojoList *`, `MojoDict *`, `MojoSet *`). Do not match by member
   name alone: a method named `which` on a struct must not be typed by a module
   function `which`.
2. Module-scope globals: the global-type pass must either run after the
   sibling's home store is populated, or read the imported function's
   `c_return_type` from the export entry when it is NOT default
   (`c_return_type_is_default` is False). The unannotated case still needs the
   home store, so this step depends on the order question above.
3. Test: add the module-scope and `return c` rows of the table above to
   `test_link_mode.py` next to
   `test_cross_module_unannotated_param_takes_the_callers_literal_type`,
   each compared to CPython, and fails-before on this tree.
4. Gate: `make gate` once at the end (this touches `module_gen`'s inference
   inputs and the compiled path, so the stdlib-dylib and bootstrap steps apply).

## Related

- `bugs/CODEGEN_a_module_scope_global_bound_to_a_container_returning_call_is_a_box.md`
  — the same module-scope-global class for same-module container returns.
- `bugs/COMPILE_FAIL_ctypes_util.md` — `ctypes/util.py`'s `find_library`
  reaches this through `shutil.which(...)`.
