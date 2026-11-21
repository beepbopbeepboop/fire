# GIR stages 2b and 3c: the IR builder and `Instr` statements

Plan source: `doc/GIR.md`, Stage 2b (`mojo/ir/build.py`) and Stage 3c (`gen.body_lines` holds `Instr`).

## Measured now

- `gen._emit(` text calls: 235 (ratchet `gen._emit( text`; 266 at the start of
  this round, 245 of those under the corrected pattern — the 21 removed were
  `emit_metal.py`'s own MSL `self._emit` calls, not gimple statements).
- `build.raw(` sites: 1 (`_emit_raw`, the adapter; new ratchet).
- `gen.body_lines` holds `Instr`; the four function-assembly sites print it
  through `ginf.body_text` (stage 3c is landed).

## Status

**2026-11-21 — stage 3c landed and stage 2b's first families are in.**
`mojo/ir/build.py` exists with `raw`, `copy`, `cast_into`, `binop_into`,
`call_into`, `call_void`, `label`; one chokepoint (`build.append`) applies the
`#line` rule. Moved: copies, casts, arithmetic, runtime calls, `_emit_call`'s
three result/void sites, and labels. `gen.body_lines` is a list of `Instr`,
rendered by `Instr.line()`; `mojo/ir/types.py` gained `type_named` (a C
spelling to `Type` bridge, used by the cast shape).

Verified by `python3 test_gir_builder.py` (new, 27 checks) and the corpus: all
285 `tools/pydiff_corpus` programs dumped before and after are **byte-identical**
(280 compile; the 5 that fail — `containers/21_dict_del_pop`,
`containers/22_dict_setdefault_update`, `funcs/16_map_lambda_list`,
`funcs/21_gen_two_yields_return`, `funcs/22_gen_with_args` — produce an empty
`.ci` before and after). `test_gimple.py` 471 passed, `test_gimple_lint.py`
clean after lowering `TEXT_ANY_CALL_BASELINE` 7 -> 4, and
`test_line_directives_per_generated_line.py` clean.

The ratchet also stopped counting `mojo/backend_gimple/emit_metal.py` for
`gen._emit(`: that file is a Metal Shading Language emitter with its own
`_emit` method and no gimple statement, so its 21 `self._emit(` calls made
the ratchet's floor 21 rather than 0 and a regression could hide behind them.
With that correction the target below is reachable.

## Next step

1. Stage 2b, the cast family: the remaining `_new_val(T, f"(T2){x}")` sites
   become `gen._cast(T, x)` (which already routes through the builder via
   `_copy`); then the `_emit(` families in `emit_exprs.py` (48),
   `emit_calls.py` (55), `emit_methods.py` (32), `emit_stmts.py` (31) and
   `emit_loops.py` (20), one family at a time, each with a corpus diff.
2. Stage 2b's remaining shapes: `load_field`, `store_field`, `br`, `cond_br`,
   `ret`. The control-flow four need `_emit_cf` to take an `Instr` instead of
   its statement text (only the `level < 0` leaf prints it), which is the
   stage-3a teardown code — do that one alone.
3. Then the coercion moves in: `rt_call.copy_needs_cast`, `_rt_args` /
   `_repr_fix_args` and `_binop_operands` decide which operands need a
   conversion; the builder should own that, so a statement's operands are
   typed values rather than already-rendered text (the stage-4 boundary).
4. `build.raw(` is the debt counter; it may only go down, and `_emit_raw`
   must stay its only backend caller.

## Acceptance

- The `gen._emit( text` ratchet only shrinks.
- Generated C byte-identical per family.

## Done when

`python3 test_gir_builder.py` passes and `python3 test_type_string_ratchet.py`
reports `gen._emit( text` **0** and `build.raw( text` **1** (the adapter itself).
