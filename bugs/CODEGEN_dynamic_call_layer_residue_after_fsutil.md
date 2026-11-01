# Residue of the dynamic call/iteration layer for compiled generators

Found 2026-10-30 while closing `c_common/fsutil.py` (which now builds, links and
runs; `iter_files`/`walk_tree`/`glob_tree`/`process_filenames` match CPython on
the call shapes below that work). Each item is a small, separate defect with a
repro; none is a regression of that work.

Layer, for orientation: a compiled generator FUNCTION used as a value is its
`<base>_start` address; each C++-path unit registers a runtime signature
(`mojo_gen_sig_register`), `mojo_dyn_call` binds positional/keyword arguments by
name, and `mojo_iter_word` drains a handle it started. Generators that are used
as values, or that call one of their own parameters, are kept on the C++ path
(`coro._eligible`).

## Status (2026-10-30)

- **Item 1 FIXED** (`test_link_mode.py::test_bare_submodule_import_keyword_call`).
  The module-alias fallback in `emit_methods._lower_method_call` carried a
  `not node.kwargs` guard, so `mod.gen(..., kw=...)` / `mod.f(..., kw=...)`
  fell through to the module-marker stub (`mojo_module_not_compiled`). The
  fallback already forwards kwargs into the bare-name call, so the guard was
  the defect; removed. Measured before/after: test FAIL (rc=1, no output) ->
  PASS (`0 10 20 30 15`, CPython-identical).
- **Item 2 FIXED, with its real cause** (2026-10-31,
  `test_link_mode.py::test_cross_module_generator_default_is_padded`). The
  `len(list(mod.gen(...)))` spelling was never the defect (it works). The real
  shape is a generator reached through another module with a defaulted
  parameter OMITTED, consumed by anything that drains it:
  `sum(lib.counter(4))` printed 0 and `tuple(lib.counter(3))` printed
  `(0, 0, 0)` (CPython 6 / `(0, 1, 2)`), and a `flag=None` default arrived as
  the non-None word 0, so `walk_tree`'s `suffix=None` took the wrong branch.
  Both `lib.counter(4)` and `from pkg.lib import counter` were affected.
  `_emit_generator_start_call` padded from the CALLER's
  `_func_param_defaults`, which never saw the defining module's pass; the api
  entry's own `defaults` snapshot is now the fallback. Measured before/after:
  `0 / (0, 0, 0) / 0` -> `6 / (0, 1, 2) / 6`, CPython-identical.
- **Item 3 FIXED** (`test_link_mode.py::test_str_affix_method_on_unsolved_word_is_bool`).
  The word-receiver branch of `emit_methods._lower_str_method`'s
  `startswith`/`endswith` arm declared its runtime result as a plain C `int`
  (`mojo_str_startswith_word` returns an int), while `exprtypes` types the
  same call `_Bool` and the bytes arm wraps with `!= 0`. `print` therefore
  rendered the int. All four runtime forms now return `_Bool` via `!= 0`.
  Measured before/after: stdout `1 0 0 1 1 0` -> `True False False True True
  False` (CPython-identical).
- **Item 4 FIXED** (`test_link_mode.py::test_generator_none_default_reaches_callee_as_null`).
  The item's own repro was misattributed: the failure is not the
  try/except after the loop. The first `for a, b in im([])` already raises.
  `im`'s `onempty=None` default is padded at the generator-start call site
  (`emit_calls._lower_generator_start`) without the callee's declared slot
  type, so the integer 0 is coerced through `mojo_cstr_or_int_str` into the
  non-NULL string `"0"`. `if onempty is None:` is then False, the coroutine
  throws `ValueError("empty")` on its first resume, and the pending exception
  reaches a `mojo_raise` with no try frame (`_mojo_exc_top == -1`, hence
  "Unhandled exception: empty"). Plain functions were already correct
  (`_default_expr_to_pair(..., param_ctype=...)`); the generator padding sites
  now pass the same declared slot type, and the no-default fallback uses
  `_null_default_pair`. Measured: test FAIL (rc=1, stdout empty) -> PASS
  (`caught empty`, CPython-identical). Generated C for the repro changes only
  in `_mojogen_im_start (_t1, _t4)` with `_t4 = mojo_cstr_or_int_str(0)` ->
  `_mojogen_im_start (_t1, 0)`. Variants measured while isolating: loop over an
  empty generator + explicit-arg try (no default) passes; a plain-function
  default passes; the failure needs the defaulted `None` on a generator.
- **Item 5 FIXED for the call shape the doc names**
  (`test_gimple_generator_runner.py::cpp_generator_double_param_called_by_keywords`).
  `_cpp_generator_sig_lines` now registers a unit with `double` parameters:
  `mojo_gen_sig_register` takes a per-parameter `is_double` mask, and
  `_gen_sig_call` passes the integer and floating-point words in separate
  register files (assigned independently on AAPCS64 and SysV x86-64), so a
  unit is registered up to 6 integer + 8 double parameters. Defaults that are
  int/float literals travel as `mojo_double_to_bits`. The call site
  (`cpp_core._cpp_dyn_call_expr`) used to refuse a `double` argument; it now
  packs it as bits and tags it (positional kind string `d`,
  `mojo_dict_set_double`), and `mojo_dyn_call` raises a catchable `TypeError`
  for a tagged double that reaches anything other than a registered generator
  (a plain function pointer / variadic thunk would read garbage).
  Still open, found while measuring (each its own gap, not filed as a doc
  because they are the same family as items 2/5):
  an UNANNOTATED generator parameter with a float default (`scale=0.5`) is
  typed `int64_t`, and a `for` over a call through a callable parameter yields
  an unsolved word that cannot be re-yielded as a float
  (`a yield of a float value is typed 'int64_t'`), so a consumer must reduce
  the values to ints. Float values in a `**kw` pack (`run(g, scale=2.5)` into
  `def run(g, **kw)`) fail to compile in gcc (`cannot convert to a pointer
  type`). Item 5 is otherwise closed; item 2 still needs its real shape.
- **Item 5's open gaps, FIXED 2026-10-31**
  (`test_link_mode.py::test_statement_call_packs_keywords_into_kwargs_slot`,
  `...::test_generator_value_called_with_kwargs_spread_and_float_default`).
  Four defects, found by building the doc's own repro (`run(g, scale=2.5)` into
  `def run(f, **kw): for v in f(3, **kw)`):
  1. A bare statement call `run(g, scale=2.5)` never packed its keywords into
     the callee's `**kw` slot (the expression twin `_lower_named_call` did);
     the raw value landed where the `MojoDict *` goes (`(MojoDict *)2.5`, the
     gcc error the doc names; a wild pointer for an int, which is why the int
     form printed nothing). The packing is now one shared helper,
     `emit_calls._pack_kwargs_slot_call`, called from both paths.
  2. `_pack_kwargs_dict` stored a float keyword with `mojo_dict_set_int`
     (truncating 2.5 to 2); it now uses `mojo_dict_set_double` (and
     `_KNOWN_SIGS` gained that prototype).
  3. `f(3, **kw)` through a callable parameter was lowered as
     `mojo_fnptr_call_2(f, 3, kw)`, the dict's address as one positional word.
     `_lower_fnptr_call_value` now sends any call with a `*x`/`**x` spread
     through `_lower_fnptr_spread_call` (packed list + dict, merged at run
     time, `mojo_dyn_call`), the GIMPLE twin of the C++-path
     `cpp_core._cpp_dyn_call_expr`.
  4. An UNANNOTATED generator parameter with a float-literal default
     (`scale=2.0`) was typed `int64_t`, so its unit could not register a
     runtime signature; it is `double` now (`cpp_async`'s parameter loop). And
     a `for` over a dynamic generator handle read a double-valued drain
     through the int arm (printing the bit pattern); `emit_loops` now has a
     `double` arm next to the string and int ones.
  A float read back out of the callee's `kw["scale"]` prints its bits (the
  dict slot read loses its value kind, a separate gap in
  `bugs/CODEGEN_dict_slot_read_loses_its_value_kind.md`).
  Measured: both tests FAIL before (gcc error / empty output) and PASS after
  (CPython-identical `0.0 2.5 5.0 0.0 2.0 4.0`). Still open from that list:
  a double beside a `*` spread in a call through a function value is refused
  at compile time (the kind string is positional); the unannotated-float-default
  rule is applied to generator parameters only, not plain functions.
- **Double beside a `*` spread FIXED 2026-11-01**
  (`test_link_mode.py::test_generator_value_called_with_double_beside_star_spread`).
  Both call-through-a-function-value lowerings
  (`emit_calls._lower_fnptr_spread_call`, `cpp_core._cpp_dyn_call_expr`)
  refused `f(1.5, *a)` / `f(*a, 0.5)` because the argument list's kind string
  was positional. A double is now appended with
  `mojo_list_append_double_kinded`, which records that slot's `d` kind at run
  time, so the static kind string (and the refusal) is gone. Measured: FAIL
  (`ValueError: ... mixes a double argument with a `*` spread`) -> PASS
  (CPython-identical). Still open: a FLOAT ELEMENT inside the spread list
  itself (`mojo_args_extend_word` appends words via `mojo_list_append_int`, so
  it loses its `d` kind), and the unannotated-float-default rule is applied to
  generator parameters only, not plain functions.
- Regressions: item 1 `test_link_mode.py::test_bare_submodule_import_keyword_call`,
  item 3 `...::test_str_affix_method_on_unsolved_word_is_bool`, item 4
  `...::test_generator_none_default_reaches_callee_as_null`, item 2 `...::test_cross_module_generator_default_is_padded`, item 5 above (+ its 2026-10-31 entry). (The
  placeholder `test_regress_dynamic_call_layer_residue.py`, which asserted
  `True`, is removed.)

## 1. (FIXED — see Status) `mod.gen(..., kw=...)` through a module attribute

    from c_common import fsutil
    for f in fsutil.walk_tree("runtime", suffix=".h"): ...

compiled, then died at run time with `NotImplementedError: ... module
'c_common.fsutil' is not compiled into this binary`. Fixed as above.

## 2. (FIXED — see Status) omitted default of a cross-module generator padded as 0

Originally written as `len(list(fsutil.walk_tree("runtime")))` raising
NotImplementedError; the real defect was the omitted-default padding.

## 3. A bool result off an unsolved word prints `1`

    for f in iter_files("runtime", ".h", "."):
        print(f.startswith("runtime"))     # CPython: True; compiled: 1

`f` is the unsolved word a registered generator yielded; the method call on a
word returns an int and loses the bool kind.

## 4. (FIXED — see Status) try/except after an earlier loop over an empty generator

    def im(items, onempty=None):
        if not items:
            if onempty is None:
                return
            raise ValueError("empty")
        for item in items: yield item, True
    for a, b in im([]): print(a, b)
    try:
        for a, b in im([], "msg"): print(a, b)
    except ValueError as ex: print("caught", ex)     # compiled: Unhandled exception

Reproduces without any of the dynamic layer (`if len(items) == 0:` too); the
consumer's `setjmp`-based `try` is not entered correctly after an earlier
`return`-terminated generator loop in the same function.

## 5. (FIXED — see Status) Generators with `double` parameters have no runtime signature

`_cpp_generator_sig_lines` declines a unit with a `double` parameter (it would
travel in a float register, which the word-typed `_gen_sig_call` cannot
reproduce), so such a generator used as a value and called with keywords raises
a catchable `TypeError`. A signature carrying per-parameter kinds, and a call
thunk per arity/kind shape, would close it.

