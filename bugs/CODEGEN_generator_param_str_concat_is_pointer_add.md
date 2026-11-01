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

**Cross-module spelling: still open.** `pkg/main.py` doing
`from pkg import lib; lib.walk("r")` still prints pointer decimals. Measured:
compiling `main.py` with `do_imports=True` leaves `_CALLSITE_PARAM_KINDS`
empty and emits no `__mgco_walk_body` in the importer's unit, and the
defining module (`lib.py`) is compiled on its own with no view of the
importer's call site. So the evidence does not exist in the module that
needs it. Next step: a cross-module call-site contract for generators, the
generator analogue of the plain-function literal contract
(`test_cross_module_unannotated_param_takes_the_callers_literal_type`):
the importer's `_scan_callsite_param_kinds` results for an imported
generator must reach the defining module's `register` pass, and that
module's compiled artifact (CAS key, see `CAS cache-key completeness`) must
depend on the importer's call-site evidence. Quick test: the two-file
`lib.py` / `main.py` pair at the top of this doc, compared against CPython
(`['r0', 'r1', 'r2']`).
