# Frames: a real `f_locals`, `sys.settrace`, and running test_frame.py through its imports

Split out of `CODEGEN_frame_model_for_test_frame.md` (deleted 2026-11-01 with the frame model it asked for). That doc asked whether the compiler gets a frame
model and which of `sys._getframe`, `f_back`, `clear`, `f_generator`, `gi_frame`, `tb_frame` it can support; the answer (b, staged, off unless the program asks)
is implemented and tested, so the question is closed. What was LEFT is a different feature set, kept here.

## What landed (do not redo; each has a run-compare test in test_gimple_runner.py / test_gimple_generator_runner.py)
Shadow frame stack per instrumented module (`mojo_frame_enter/leave/set_line`, `<module>` frame, names/lines/callers, tracebacks with `tb_frame/tb_next/tb_lineno`),
per-coroutine frame slices (a suspended generator's frame is not live), `gi_frame` / `cr_frame` objects, `f_generator`, `frame.clear()` (refuses executing and
suspended frames), `StopIteration.value`, settable `f_trace` / `f_trace_lines` / `f_trace_opcodes`, `f_locals` refused by name, and the generator-side walls test_frame.py
hit (lifting of capture-free nested defs, Python scoping for nested generators, `gi_frame` as a non-escape). `MOJO_DEBUG=1 python3 fire.py build Lib/test/test_frame.py`
names no generator or async refusal in the file itself.

## Still open
1. A real `f_locals` (design below, option (A)); today it is a named compile error.
2. `sys.settrace` / a tracer that is CONSULTED (the `f_trace` words only read back).
3. The type/delete errors test_f_trace_lines_and_opcodes asserts (`TypeError` for a non-bool, `del f.f_trace_lines`).
4. Running test_frame.py through its real imports: the first refusal is a `match` MAPPING PATTERN (`case {"k": v}:`) in the `unittest` closure; beyond it `TestCase`,
   `assertRaises*`, `support`, `threading_helper`, `FrameLocalsProxy`.

## Plan (2026-11-01): `f_locals` and `f_trace` — decisions, mechanism, ordering, tests

State measured: both are unlowered (`frame.f_locals` reads fall to the generic attribute path; `f_trace` assignment is an attribute store on an int64 word).
Everything else test_frame.py needs from the frame model is landed (slices 1-9 above). What these two need is a mechanism, because compiled C locals have no
runtime names or addresses: `-fgimple` rejects address-taken locals, so a frame record cannot simply point at the function's variables.

### `f_locals` (a dict of the frame's locals, read through `frame.f_locals` / `f_back.f_locals[...]`)
Decision needed, with the readings laid out:
- (A) **Box-all-locals for functions that can be observed.** Reuse the capture machinery (`coro._apply_nested_async_capture` / `__mojo_box_new_*`): when a compile
  mentions `f_locals` anywhere (same trigger family as `gen._frames_mods`), every instrumented function boxes its locals, and `mojo_frame_enter` takes a
  descriptor array `{name, kind, box handle}` built at entry. `f_locals` builds a dict from the live boxes (`mojo_frame_locals(word)`), kinds drive the
  value spelling (`mojo_box_*`). Cost: slower and larger C for modules that use frames; zero cost for every other module (the trigger gates it).
  Writes through the returned dict are a CPython 3.13 `FrameLocalsProxy` feature (write-through): with boxes it is a store into the box, which is exact.
- (B) **Snapshot at call sites.** Spill named locals to a table before each call that could reach `f_locals`. Needs interprocedural knowledge of who reads
  `f_locals`; rejected: unsound for `f_back.f_locals` from any callee.
- (C) **Refuse** (`NotImplementedError`) until (A). Today it silently answers garbage, so refusal is the minimum.
Recommendation: land (C) first (one lowering arm in `emit_exprs._lower_MemberExpr` raising a named compile error, so nothing answers silently), then (A).
Plan for (A): `emit_methods._frame_enter` emits the descriptor build after the prologue; a new pass `coro`-style `_box_all_locals(fn)` (reuse `_cap_rewrite_stmts`)
rewrites reads/writes of every local; runtime `MojoFrameRec` gains `locals`/`nlocals`; generator frames keep them in the per-coroutine slice (already copied
by value; the boxes are heap, so they survive). Tests: `f_back.f_locals["xs"]` read and write (test_frame `test_overwrite_locals`), a generator's `gi_frame.f_locals`,
and the byte-identical-C check that a module without `f_locals` is unchanged (`compile_stdlib.py` GCC CAS hit count).

### `f_trace` / `sys.settrace`
`mojo_frame_set_line` already runs once per statement. Add `_mojo_trace_fn` (the registered tracer) and a per-frame `f_trace` word; when either is set,
`set_line` calls `mojo_trace_event(frame, "line")` (and enter/leave emit "call"/"return"), invoking the compiled callable through `mojo_dyn_call`. Cost is a
branch on a global in `set_line`. Needs the callable-value ABI (`mojo_dyn_call`, landed) and a frame word the tracer can read (`f_lineno`, `f_code`, landed).
Test: test_frame's `test_lineno_with_tracing` (`sys._getframe(0).f_trace = True` then three `record_line()` calls expecting `[1, 4, 5]`).

Ordering: (C) refusal for f_locals -> f_trace -> (A). Neither needs the unittest closure; both can be tested with small programs first.

## Status (2026-11-01, stage 3 tenth slice): `f_locals` refused by name; `f_trace` / `f_trace_lines` / `f_trace_opcodes` are stored attributes

- `frame.f_locals` in a frame-instrumented module is a named compile error (was: read as a generic attribute of an int64 word, garbage at exit 0).
  Test `gimple_frame_f_locals_is_refused`. This is step (C) of the Plan above.
- `f.f_trace = x`, `f.f_trace_lines = b`, `f.f_trace_opcodes = b` store a word on the frame record (`mojo_frame_set_attr`), and reading them returns it
  (`f_trace` None by default, `f_trace_lines` True, `f_trace_opcodes` False; `f.f_trace is None` and `True`/`False` printing work through boxed words).
  Test `gimple_frame_f_trace_attributes_read_back` matches CPython. Nothing CONSULTS them yet: there is no `sys.settrace` and `set_line` does not call a tracer, which
  is the next step of the f_trace plan above (test_lineno_with_tracing only needs the stored attribute). Gate: `compile_stdlib.py` 0 unexpected.
## Status (2026-11-01, stage 3 eleventh slice): `f_trace_lines` / `f_trace_opcodes` require a bool

- `f.f_trace_lines = <literal>` and `f.f_trace_opcodes = <literal>` with an int, float or str LITERAL raise `TypeError("attribute value type must be bool")`
  at runtime and store nothing (`emit_stmts.py`, the frame-attribute store arm). `f_trace` itself still takes any value. Test
  `gimple_frame_f_trace_lines_requires_bool` (matches CPython; `= False` and `= 2 > 1` still store).
  Limit: the check is on the AST, not the type. Bool literals lower to the same `'int'` as `1`/`0` and there is no separate bool static type to test, so a
  variable holding an int (`x = 1; f.f_trace_lines = x`) is still stored unchecked. Remaining piece: a bool tag on the value, or a bool static type for
  comparisons/names, so the store can decide at compile time or at runtime.
## Status (2026-11-01, stage 3 twelfth slice): `del` on the frame attributes

- `del f.f_trace` clears the hook back to None; `del f.f_trace_lines` raises `TypeError: can't delete numeric/char attribute`; `del f.f_trace_opcodes`
  raises `AttributeError` (CPython 3.15, measured). Neither of the two raising forms removes the stored value. Lowered in `emit_stmts._gen_stmt_DelStmt` to
  `mojo_frame_del_attr` (runtime/fire_runtime.c), which holds the three answers in one place. Test `gimple_frame_del_trace_attributes`.
- The id table `f_trace`/`f_trace_lines`/`f_trace_opcodes` -> 0/1/2 was duplicated between the read lowering and the store arm; it is now one definition,
  `mojo/middle/calls_shared.FRAME_SETTABLE_IDS`, used by all three.
- Known difference: the `AttributeError` for `f_trace_opcodes` carries the attribute name through `mojo_raise_attribute_error`'s existing message format, not
  CPython's full text ("attribute 'f_trace_opcodes' of 'frame' objects cannot be deleted"). Only the type is asserted by the test.

## Status (2026-11-01, stage 3 thirteenth slice): non-bool values rejected for `f_trace_lines` / `f_trace_opcodes` even if not literals

- `f.f_trace_lines = x` / `f.f_trace_opcodes = y` where `x`/`y` hold a non-bool value now raise `TypeError("attribute value type must be bool")` at runtime (using `is_python_bool_expr` so variables, params, fields recognized as bool are accepted; arbitrary ints/other values are rejected). `f_trace` still accepts any value. Tests: `gimple_frame_f_trace_lines_requires_bool` extended coverage and `reg_f_trace_lines_rejects_int_var`.

Remaining: (A) box-all-locals for a real `f_locals`; `sys.settrace`; and running test_frame.py through its real imports.
