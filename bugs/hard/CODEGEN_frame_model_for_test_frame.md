# Frame introspection for test_frame.py: research for Sonnet 5.5

Owner direction (2026-10-30): maximal compatibility with Python; eventually fix all bugs. The owner has latitude on how to frame the model, but compiled code must coexist with the C API (external calls such as fopen and write) and its usual limits. Research and ANSWER, do not start a fix.

## The question
Does the compiler get a frame model (option b) or keep test_frame.py refused (option a)?
The surface in question: sys._getframe, f_back, clear, f_generator, gi_frame, tb_frame.

## What to answer
1. What is the smallest frame model that makes these work for generators and ordinary functions, and what does it cost at run time?
2. Which of these can never be exact in compiled C (for example a live f_locals), and what limit should the owner accept?
3. Recommend (a) or (b) and give the first step.

Source context: frame model feature for test_frame.py (bug fixed: generator division-by-zero and method self-capture); not the frame-model feature itself.

## Status (2026-10-31) — the answer; no code landed

Measured this round: neither engine has any frame model today. `grep` finds no `_getframe`, `f_back`,
`tb_frame`, `gi_frame` or `f_generator` in `myinterpreter.py`, `gimple_codegen.py`, `mojo/` or `runtime/`;
the only run-time exception state is `mojo_exc_*` (a message, a type tag and one object pointer,
fire_runtime.h:528) and source positions exist only as compile-time `#line` directives
(`emit_stmts.py:70-95`). `Lib/test/test_frame.py` uses exactly the surface the doc lists
(`sys._getframe(n)`, `f_back`, `f_lineno`, `f_code.co_firstlineno`, `f_generator`, `gi_frame`,
`tb_frame`, `tb_next`, `frame.clear()`, `f_trace`).

### Recommendation: (b), staged, and OFF unless the program asks for it

1. **The model: a shadow frame stack, enabled per compile by a static scan.** The scan looks for
   `sys._getframe`, `inspect.currentframe/stack/getframeinfo`, `traceback`, `__traceback__`, `tb_frame`,
   `gi_frame`, `cr_frame`, `f_back`, `f_generator` over the compile's closure. When it finds none, nothing
   is emitted and the cost is zero, so every existing program and the byte-identical-C rule are untouched.
   The flag is part of the compile's CAS key (it changes the OUTPUT, same reasoning as `auto_gpu` in
   `cas.compile_key`).
2. **When on, per call:** a function whose frame is reachable gets a stack-allocated
   `MojoFrame { MojoFrame *back; const MojoCodeInfo *code; int32_t lineno; void *gen; uint8_t flags; }`,
   pushed in the prologue and popped on every exit path (the same exit paths `exc_depth` cleanup already
   walks in `emit_funcs`). `MojoCodeInfo` is a static per-function table (`co_name`, `co_qualname`,
   `co_filename`, `co_firstlineno`), emitted next to the `#line` data. `lineno` is updated by one store per
   statement, where `emit_stmts.py` already emits `#line`. A `try` records the frame top at entry and the
   catch path restores it, so a `longjmp` unwind cannot leave stale frames.
3. **Tracebacks:** `mojo_raise` snapshots the live chain into heap `MojoFrameObj`s (frames are stack
   objects and die on pop; `tb_frame` must outlive them), attached to the exception object as
   `__traceback__` with `tb_next/tb_lineno/tb_frame`. This is also what makes `e.__traceback__.tb_frame.f_back`
   work after the raise.
4. **Generators and coroutines:** the frame record is embedded in the generator object (the A3 stack-switch
   runtime's handle), pushed on resume and popped on yield or finish. That gives `gi_frame`, `gi_running`,
   `f_generator` (the handle; `None` for plain functions, as the test asserts), `f_back` = the resumer while
   running and `None` while suspended, and the `suspended`/`executing` flags `frame.clear()` needs to raise
   `RuntimeError`.
5. **C API coexistence:** only compiled-Python functions have frames. A C callee (`fopen`, `write`, a qsort
   callback trampoline) is invisible, exactly as CPython shows only Python frames, so the chain stays
   correct across external calls. A Python callback called from C pushes its own frame on top of whatever is
   current, and `f_back` skips the C frames.

### What can never be exact in compiled C (the limits to accept)

- **Live `f_locals`.** C locals live in registers or the stack, and under `-fgimple` the compiler does not
  keep an addressable name table. A read-only SNAPSHOT dict of the locals the codegen spilled to the frame is
  possible later (stage 2); writes through `f_locals`, and `f_locals` aliasing the real variables
  (the PEP 667 view), are not.
- **Tracing.** `sys.settrace`, `f_trace`, `f_trace_lines/opcodes` and `test_lineno_with_tracing`'s
  trace-dependent line reporting: `f_lineno` is exact at statement granularity, per-opcode events are not.
- **Reference-lifetime assertions.** Tests like "the reference was released by `.clear()`" and the
  refcycle checks rest on CPython's refcount and cycle GC. The compiled runtime frees by ownership analysis,
  not refcounts, so those cases cannot pass and should be listed in `EXPECTED_FAILURES`-style with that
  reason rather than chased.
- **`f_code` identity and mutation** beyond the read-only metadata above (`replace()`, bytecode, `co_code`).

### Cost

Estimate, NOT measured (no frame code exists to measure): about two stores and two loads per instrumented
call plus one store per statement, so low single-digit percent on call-heavy code when the flag is on and
exactly zero when it is off. Gate cost: edits under `mojo/backend_gimple/*` and `runtime/` change
`compiler_fingerprint()`, so one cold rebuild (~8 min dylib, ~32 min bootstrap, measured elsewhere in this
queue) plus `make gate`; the stdlib-dylib `skip` count and `compile_stdlib.py` `U` must not rise, and the C
of a large program with no frame use must be byte-identical before and after.

### First step (next round)

Runtime: `mojo_frame_push/pop/top` and the `MojoFrame`/`MojoCodeInfo` structs in `fire_runtime.[ch]`
(update the ABI census). Compiler: the static scan in `module_gen.py` (sets `gen._frames_enabled`), prologue/
epilogue emission in `emit_funcs.py`, the per-statement line store in `emit_stmts.py`. Lowering of
`sys._getframe(n).f_code.co_name` / `.f_lineno` / `.f_back` in `emit_methods.py`. Test: a three-function chain
printing `sys._getframe(0..2).f_code.co_name` and `f_lineno`, run-compared with CPython (the
`test_interp_oracle.py` pattern), plus one program with no frame use whose `.ci` must `cmp` identical to
master's.

## Status (2026-11-01) — stage 1 LANDED: shadow frame stack for sys._getframe / f_back / f_lineno / f_code.co_name

Implemented the design above, first slice, for plain functions and methods of any module that says `_getframe`:

- **Runtime** (`runtime/fire_runtime.[ch]`, "Python-level frames"): a frame stack of `{name, file, firstlineno, lineno}`;
  `mojo_frame_enter/leave/set_line`, `mojo_getframe(depth)` (raises `ValueError: call stack is not deep enough`), and
  `mojo_frame_back/lineno/firstlineno/name/file`. A frame "object" is a word (its 1-based stack index, 0 is None). Enter pushes a
  `MOJO_CLEANUP_FRAME` record on the existing cleanup stack, so an exception unwinding past a frame pops it too (exact pairing with
  `mojo_frame_leave`, same discipline as the class-attribute cell records).
- **Compiler**: `module_gen` marks a module that mentions `_getframe` (`gen._frames_mods`); `emit_methods._frame_enter` runs before
  `_cattr_restore_begin` and `_frame_leave` rides `_cattr_leave` (every `return`, and fall-off-the-end); `emit_stmts.gen_stmt` sets
  the line per statement; `emit_methods._lower_method_call` lowers `sys._getframe(n)`; `emit_exprs._lower_MemberExpr` lowers
  `f_code`/`f_back`/`f_lineno`/`co_name`/`co_qualname`/`co_filename`/`co_firstlineno`; `resolve_shared._quick_type` types the string
  attributes. A module that never says `_getframe` emits nothing new: `compile_stdlib.py` GCC CAS 610/610 with the compiler change
  reversed (generated C unchanged for every stdlib module).
- **Tests**: `gimple_sys_getframe_names_lines_and_callers` (test_gimple_runner.py: names, lines, callers through a raise/catch, recursion,
  branches that return from two places) matches CPython; `test_selfhost.py` 3/3.

**Not done (stage 2+)**: the `<module>` frame (module-level code is not a frame, so a walk up `f_back` ends one frame earlier than
CPython); generators/coroutines (`gi_frame`, `f_generator`, `cr_frame`; their frames are not pushed); exception tracebacks
(`__traceback__`, `tb_frame`, `tb_next`: `mojo_raise` does not snapshot the chain yet); `frame.clear()` and its executing/suspended
checks; a frame word kept past its function's return (it names whatever frame reuses the slot); a read-only `f_locals` snapshot;
frames in modules that do not themselves mention `_getframe` (their functions are invisible, like C frames in CPython).
Next step: the exception snapshot (heap frame records captured in `mojo_raise`, attached as `__traceback__`), which `tb_frame`,
`tb_next`, `tb_lineno` and test_frame's `clear()` cases need.

## Status (2026-11-01, later) — stage 2 LANDED: tracebacks and the `<module>` frame

- **`<module>` is a frame** (`emit_methods._frame_enter_module`, emitted around `_gen_toplevel`'s statements), so a walk up `f_back` or a
  traceback ends where CPython's does.
- **Tracebacks**: `mojo_raise` snapshots the live frame stack once per exception (keyed by the exception's message/object pointers, so a bare
  `raise` keeps the original), before the unwind pops it. `e.__traceback__` lowers to `mojo_traceback(<current depth>)`, which builds the
  chain from the catching frame down to the raising one; `tb_frame`, `tb_next`, `tb_lineno` read an entry, and the heap snapshot records
  are valid frames for `f_code`/`f_lineno`/`f_back`. Test `gimple_traceback_chain_names_and_lines` matches CPython (names and lines through
  a re-raise).
- **Statement lines**: the parser built `if`/`while`/`raise`/`def`/... with `line=0`, so those statements carried no line (neither for
  `f_lineno` nor for the `#line` directives of the generated C). `Parser._parse_stmt_into` now stamps the line the statement starts on
  (`_stamp_stmt_line`). This is global: every module's C gains `#line` directives for those statements (semantics unchanged;
  `compile_stdlib.py` 0 failed, `test_selfhost` 3/3, `test_gimple.py` 421 pass with the same 2 failures as before).

Still open: generator/coroutine frames (`gi_frame`, `f_generator`, `cr_frame`, the suspended/executing flags `frame.clear()` checks),
`frame.clear()` itself, `__traceback__` on an exception object other than the one currently handled (it reads the last snapshot),
`f_locals`, `f_trace`, and instrumented-module-only visibility (a module that never mentions `_getframe`/`__traceback__`/`tb_frame`/`f_back`/
`f_lineno` has no frames). Run `Lib/test/test_frame.py` through the compiler next to see which of its cases now compile and which refusal is first.

## Status (2026-11-01, stage 3 first slice): a suspended generator no longer leaves its frame live

Measured first: `test_frame.py` does not compile yet (`fire.py build` refuses: generator functions with `nonlocal`/try-finally yields,
`async def t3`, `frame.f_generator`), and while looking for the first refusal a stage-1 defect turned up: the generator body's frame
(`__mgco_g_body`) stayed on the shadow frame stack across a `yield`, so `sys._getframe()` in the consuming loop named the generator,
and the resumer's `mojo_frame_leave` cancelled the generator's cleanup record instead of its own.

Landed: `mojo_coro_slice_save/restore` (`runtime/fire_runtime.c`) called from `__mojo_coro_yield`/`coro_run` (`runtime/fire_coro.c`):
a yield detaches the frame and cleanup records the body pushed since it was resumed, the next resume re-pushes them above the
resumer's current depth (so it also covers async coroutines, and the cleanup records of any kind the body holds across a yield).
`_frame_enter` names the frame after the source function (`g`, not `__mgco_g_body`; a method generator drops its struct prefix).
Test `gimple_generator_frame_is_live_only_while_running`; the stage 1/2 frame tests unchanged.

Still open: `f_generator`/`gi_frame`/`cr_frame`, `frame.clear()` and its executing/suspended checks, `f_locals`, `f_trace`, and the
generator shapes above that make test_frame.py refuse at the module level (nonlocal + try/finally yield, nested async def).
Also fixed, because master's self-host was red on it: `mojo_bytes_from_str` gained an `errors` parameter (a492e9c71) and three
callers still passed two arguments (`bytearray(text)`, `_coerce_to_bytes`, the cpp path's `bytes(text, enc)`).

## Status (2026-11-01, stage 3 second slice): the generator walls test_frame.py hits, measured

`MOJO_DEBUG=1 python3 fire.py build test_frame.py` now names every generator/async refusal. One was a bug, FIXED: the
tagged-consumer scan (`coro._tagged_consumers_ok`) is keyed by NAME, so a local `g = gen()` in one method counted as a consumer of
a nested generator `def g` in another and refused a compilable module; a function that binds the name as a local without defining
its own nested `def` of it is now skipped (test `gimple_local_named_like_a_generator_elsewhere`). `MOJO_DEBUG` also prints why a
nested generator stayed out of the stack-switch hoist (`_hoist_note`).

What remains, each a feature rather than a bug:
1. `test_clear_generator`: `gen = g(); next(gen); gen.gi_frame.clear()`. The bare-`yield` generator's handle has a use beyond
   `next()`/`close()` (`gi_frame`), so the None-yield tagging refuses it. Needs the generator frame object (`gi_frame`, built from the
   frame slice the runtime now saves per coroutine) and `frame.clear()` with its suspended/executing checks.
2. `test_clear_executing_generator`: `yield f` where `f` is assigned inside an `except` block of the generator (capture plan None).
3. `test_f_generator`: `async def t3(): return frame.f_generator` returns a frame object, not a scalar (the async return kind rule), and
   `gen` there calls an ordinary nested helper (`nested()`), which the C++ companion cannot resolve.
Next step: model a frame object as a first-class value (a heap record shared by `sys._getframe`, `gi_frame`, `__traceback__`) so
`gi_frame`, `f_generator` and `clear()` have something to return; the per-coroutine slice in `fire_coro.c` is where the saved frame lives.

## Status (2026-11-01, stage 3 third slice): `frame.clear()` refuses an executing frame

`mojo_frame_clear(word)` (runtime/fire_runtime.c): every frame activation now carries an identity (`MojoFrameRec.id`, copied by the
traceback snapshot); `clear()` raises `RuntimeError: cannot clear an executing frame` when an activation with that identity is on the live
stack, else it is a no-op (a finished frame, e.g. a traceback frame kept past its function's return). Compile side: a frame is an int64
word, so `x.clear()` cannot be told from `list.clear()` by type; `emit_methods._is_frame_expr` decides by origin (`sys._getframe(...)`, a
`f_back`/`tb_frame`/`gi_frame`/`cr_frame` attribute, or a name bound to one: `gen._frame_vars`, filled by `_gen_stmt_AssignStmt`).
Test `gimple_frame_clear_refuses_an_executing_frame` matches CPython. This covers test_frame's `test_clear_executing`.

Still open: `gi_frame`/`f_generator`/`cr_frame` VALUES (the `.clear()` receiver recognition already accepts the attribute names, but nothing
produces the frame yet), the suspended-generator refusal ("cannot clear a suspended frame": needs a snapshot of the coroutine's saved
slice marked suspended), `f_locals`, `f_trace`.

## Status (2026-11-01, stage 3 fourth slice): `gen.gi_frame` is a frame object

`gen.gi_frame` / `cr_frame` / `ag_frame` on a stack-switch generator handle lowers to `__mojo_gen_frame(handle)` (runtime/fire_coro_gen.c): a
heap frame record (`mojo_frame_for_gen`, runtime/fire_runtime.c) that names the generator, refreshed from the frame records its parked
coroutine holds, with the generator's state answered through `_mojo_gen_state_hook` (0 not started, 1 suspended, 2 running, 3 finished).
`frame.clear()` on it raises `RuntimeError: cannot clear an executing frame` (running) or `cannot clear an suspended frame` (suspended,
CPython's own wording) and is a no-op otherwise. A module that only mentions `gi_frame`/`cr_frame`/`ag_frame` is now instrumented too.
Test `gimple_generator_gi_frame_clear_refuses_suspended` matches CPython; `test_coro_runtime.py` is 16/20, the same 4 layer1-shim failures as master.

Differences from CPython that remain: `gi_frame` should be `None` once the generator is exhausted; a generator that has not started
reports the placeholder name `<generator>`; `f_generator`, `f_locals`, `f_trace`; C++20-coroutine generators (`_mojogen_*`) have no frame
object. NOT gated by `test_selfhost.py`: master's self-host closure compile has been red since 18f122b7c (see the note in the commit).

## Status (2026-11-01, stage 3 fifth slice): `f_generator`, and `gi_frame` is None once exhausted

`frame.f_generator` lowers to `mojo_frame_generator(word)`: a generator body's own frame is bound to its generator on first entry
(`__mojo_gen_resume` sets `_mojo_resuming_gen`, the body's `mojo_frame_bind_gen()` -- emitted for `__mgco_*_body` functions right after
`mojo_frame_enter` -- stores it in the frame record), and the binding survives yields because the per-coroutine slice copies the record.
A plain function's frame answers None. `gen.gi_frame` of a finished generator is None. Test
`gimple_frame_f_generator_and_exhausted_gi_frame` matches CPython. Not gated by `test_selfhost.py` (master's self-host closure compile is red
since 18f122b7c, unrelated).

Still open: `f_locals`, `f_trace`, a not-yet-started generator's real name (placeholder `<generator>`), and frame objects for C++20-coroutine
generators and async functions (`cr_frame` of an `async def`, whose return kind is not a scalar: test_frame's `t3`).

## Status (2026-11-01, stage 3 sixth slice): three generator walls test_frame.py hit are gone; two remain

`MOJO_DEBUG=1 python3 fire.py build test_frame.py` now refuses only `gen` and `t3` (was: g, g, gen, t3). Fixed:
1. A nested generator's handle used as `gen.gi_frame...` (or `gi_running`/`gi_code`/`gi_suspended`) no longer counts as a non-consumer of its
   None-yield (`_tagged_consumers_ok`) nor as the generator escaping the method (`_generator_result_escapes`): test_clear_generator.
2. `_tagged_consumers_ok` is keyed by NAME; calls of an ordinary nested `def g` (or a local `g` binding) in another function are skipped.
3. REAL silent-wrong bug, found on the way: `_nested_async_free_vars` counted only `var` declarations as the inner function's locals, so in
   Python source `f = 1` inside a nested generator whose enclosing function also binds `f` aliased the outer `f`'s box (outer printed 2, CPython
   10). Python scoping now holds for `.py` sources (`coro._PY_SRC`, set by the root compile and each imported module); Mojo source keeps by-reference
   capture (a plain `x += 1` in a nested `def` mutates the captured variable: `nested_async_*` runner cases). Names declared `nonlocal`/`global` stay captures.
   Gate: `test_gimple_generator_runner.py` 438 passed / 5 failed, identical failures to master's (star_args x3, cpp_coroutine_unpack_boxed_source_refused,
   async_for_over_nonparking_await); `compile_stdlib.py` 0 unexpected. Tests: gimple_nested_generator_local_shadowing_an_outer_name (filename='shadow.py'),
   gimple_nested_generator_gi_frame_use_is_not_an_escape.
`MOJO_DEBUG` now names why a nested generator missed the stack-switch hoist and which call/reference blocks the tagged-word consumer decision.

Still refused: `gen` (calls an ordinary nested helper `nested()` -- the hoist leaves such generators alone, and the C++ companion cannot resolve the callee) and
`t3` (`async def` returning `frame.f_generator`, not a scalar kind).

## Status (2026-11-01, stage 3 seventh slice): `test_frame.py` now refuses ONLY `t3`

`coro._lift_capture_free_nested_scopes` (runs first in `lower`): a nested plain `def h` of a top-level function/method that (a) defines a
generator / `async def` of its own, or is called by one of the enclosing function's nested generators/coroutines, and (b) captures nothing
from the enclosing function (every name it reads that the enclosing function binds is bound inside `h`), is only ever CALLED (never passed as a
value), and has no decorators / star params / defaults, is lifted to module level as `__lift_<owner>_<m>_<h>` (frame records keep `display_name`).
A capture-free nested function has no closure cells in CPython, so behaviour is unchanged, and its nested generators become direct children
of a top-level function, which the existing hoist reaches (test_frame's `t0` / `nested` / `gen`). Test `generator_two_levels_deep_calls_a_sibling_helper`
(generator runner, which links the companion). Gate: generator runner 439 passed, the same 5 failures as master; `compile_stdlib.py` 0 unexpected.

The one remaining refusal is `t3`: `async def t3(): ... return frame.f_generator`, driven by hand (`c = t3(); c.send(None)` expecting
`StopIteration` whose `value` is `c`). That needs the coroutine OBJECT protocol on a bare `async def` result (`send`, `StopIteration.value`,
`cr_frame`) and a non-scalar return kind for coroutines, which is its own feature. After it, running test_frame.py end to end also needs
`unittest` machinery (`TestCase`, `assertRaises*`) in the compiled closure and `f_locals` / `f_trace`.

## Status (2026-11-01, stage 3 eighth slice): `StopIteration.value` (what `t3` needs from the coroutine protocol)

`ex.value` after `c.send(None)` on a coroutine (and after a generator's `return x`, and `raise StopIteration(x)`) is now the value, not None
(`bugs/CODEGEN_exception_object_attributes_args_and_stopiteration_value_are_none.md` has the mechanism and test). That is the exception half of
test_frame's `t3`; the remaining half is a coroutine whose RESULT is its own frame/coroutine object (`StopIteration.value is c`): a non-scalar return kind
for a bare `async def`, still refused by the C++ async path ("every return must carry a scalar").
