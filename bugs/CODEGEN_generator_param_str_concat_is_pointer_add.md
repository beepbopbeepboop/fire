# `root + str(k)` in a compiled generator with an unannotated `root` adds pointers

Found 2026-10-31 while closing item 2 of the (still open) dynamic-call-layer residue doc.

    # pkg/lib.py
    def walk(root, suffix=None):
        for k in range(3):
            yield root + str(k)
    # main.py
    from pkg import lib
    print(list(lib.walk("r")))      # CPython ['r0','r1','r2']; compiled ['43033668960', ...]

Same result in a single file (`fire` build of one module with `def walk(root)`).
`root` is an unannotated parameter typed `int64_t`; `root + str(k)` lowers to an
integer add of the string pointer and `str(k)`'s pointer, and the yielded word
prints as a decimal. Expected: the call site's argument type (`"r"`, a string) or
a runtime-dispatched `+` (`mojo_add_dyn`-style) decides concatenation.

Next step: look at how `_lower_BinaryOp` handles `int64_t + char *` for an
unsolved-param operand; the cross-module unannotated-param inference
(`test_cross_module_unannotated_param_takes_the_callers_literal_type`) already
takes the caller's literal type for plain functions and does not reach generators
(`<base>_start` slots). Quick test: the snippet above against CPython.

## Status (2026-10-31)

**Same-module spelling: FIXED.** Root cause: the coroutine pass recorded the
call-site evidence that `root` is a string (`_CALLSITE_PARAM_KINDS['walk']
== {'root': 'p'}`, carried to the body as `_coro_str_params['__mgco_walk_body']
== {'root'}`), but only the `for`-loop lowering read it. The `+` lowering
consults `_int64_may_hold_str`, which a generator body never received, so
`root + str(k)` became `mojo_str_from_int(root)` concatenation of a pointer
decimal. Landed:

* `module_gen.py`: a coroutine body's string params are also folded into
  `_int64_may_hold_str` (the same provenance the plain-function
  call-site contract uses).
* `emit_exprs.py`: a `char *` + int64 concatenation whose int64 operand is a
  may-hold-string parameter goes through `mojo_cstr_or_int_str`, the same
  runtime discriminator the dynamic-word arm already uses.
* Test: `test_link_mode.py::test_generator_str_param_concat_is_string_concatenation`
  (fails before the fix with `['43111790480', ...]`, passes after with
  `['r0', 'r1', 'r2']`).

**Cross-module literal spelling: FIXED 2026-10-31.** `pkg/main.py` doing
`from pkg import lib; lib.walk("r")` now prints `['r0', 'r1', 'r2']`.
Root cause: the importer's string-literal call site was already recorded in
`_xmod_gen_param_hints` (`pkg_lib::walk` -> `root: 'char *'`) and merged into
the generator's start-shim signature, but the lowered generator BODY — the
thing that emits `root + str(k)` — reads the body-keyed string tables
(`_coro_str_params`, `_int64_may_hold_str`), which that merge never wrote.
Landed:

* `mojo/middle/coro.py`: `generator_base_name(fn_name, qualifier)`, the one
  place the module-level generator base symbol is spelled;
  `_async_method_setup` uses it.
* `mojo/backend_gimple/module_gen.py`: the cross-module hint merge feeds a
  `char *` hint into both body-keyed tables under `<base>_body`;
  `_coro_str_params` is now created beside `_int64_may_hold_str` so the
  merge's writes are not dropped by a later re-initialisation.
* Test: `test_link_mode.py::test_generator_str_param_concat_cross_module`
  (pre-fix output `['43634604000', ...]`, post-fix matches CPython). The
  same-module sibling still passes.

**Cross-module variable argument: FIXED 2026-10-31.** `s = "r";
lib.walk(s)` (module scope, and a local `s` in a function) now prints
`['r0', 'r1', 'r2']`. Root cause: `_gmi_literal_ctype` answers `None` for an
identifier, so `_xg_record_scalar_args` recorded no hint for it. Landed:

* `mojo/backend_gimple/module_gen.py`: a binder census
  (`_gmi_bound_names`, `_gmi_binding_index`) and
  `_gmi_identifier_literal_ctype`, which resolves an identifier argument only
  when its ONE binder in scope is `name = <literal>` (or `var name = ...`).
  The scope is the enclosing function when it binds the name, else the whole
  module. Any second binder, a non-literal binder, a parameter, a
  `global`/`nonlocal`, or a wildcard import declines. The cross-module
  recorder uses it; the module index is built once per module.
* Tests: `test_link_mode.py::test_generator_str_param_concat_cross_module_variable_arg`
  and `..._cross_module_local_var_arg` (both fail before, pass after; the
  existing literal and same-module tests still pass).

**Still open: same-module identifier arguments (2 spellings, measured
2026-10-31).** The same root (an identifier argument carries no call-site type
evidence) is not fixed on the same-module paths, which take literal arguments
only:

1. **Ordinary `def`, silent corruption.** `def f(root): return root + str(0)`
   and `s = "r"; print(f(s))` in one module prints `43104041840` (exit 0;
   CPython `r0`). The evidence comes from `_gmi_apply_call_site_param_evidence`
   (`module_gen.py`), which calls `_gmi_literal_ctype(arg)` only. The
   cross-module ordinary-def spelling `lib.f(s)` is already correct.
2. **Generator, module-level call, loud refusal.** `def walk(root): yield
   root + str(k)` with `s = "r"; print(list(walk(s)))` at module scope fails
   the build with `walk: yields ['root'], whose call sites do not all pass
   the same statically-known type`. The same call inside a function (`def
   main(): s = "r"; ...`) compiles and prints `['r0', 'r1', 'r2']`. The
   evidence comes from `_scan_callsite_param_kinds` / `_visit_call` in
   `mojo/middle/coro.py`, which is where the module-scope identifier is not
   typed.

Next step: for (1), call `_gmi_identifier_literal_ctype(name, enclosing,
mod_index)` from `_gmi_apply_call_site_param_evidence` for an `IdentExpr`
argument, passing the enclosing FunctionDef (the function already iterates
per call; it needs the enclosing function alongside each call, and a
module-level call passes `None`). Build `mod_index = _gmi_binding_index(stmts)`
once. Quick test: the snippet in (1) against CPython `r0`. For (2), find how
`_visit_call` types an identifier argument and why a module-scope binding
does not reach it, then route it through the same resolver. Quick test:
`walk(s)` at module scope against CPython `['r0', 'r1', 'r2']`. Both are
`module_gen.py`/`coro.py` changes; each needs its own regression test next to
`test_generator_str_param_concat_*` in `test_link_mode.py`.
